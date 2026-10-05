"""Krok 2: CSV -> SQLite (star schema) -> widoki -> eksport CSV dla Tableau.
Uruchomienie: python load_to_db.py
"""
import sqlite3
from pathlib import Path
import pandas as pd

DATA = Path("data")
DB_PATH = DATA / "jobs.db"
OUT_DIR = DATA / "tableau"

# Nazwa wewnętrzna -> nazwa kolumny w CSV
POSTINGS_COLS = {
    "posting_id": "posting_id",
    "title": "title",
    "company": "company",
    "city": "location",
    "role": "role",
    "work_mode": "work_mode",
    "employment_type": "contract_time",
    "salary_min": "salary_min_pln",
    "salary_max": "salary_max_pln",
    "salary_avg": "salary_avg_pln",
    "date": "posted_date",
    "is_predicted": "salary_is_predicted",
}
SKILLS_COLS = {"posting_id": "posting_id", "skill": "skill_name", "category": "category"}
OPTIONAL = {"employment_type", "date", "category", "company", "city", "is_predicted"}


def pick(df, mapping, name):
    """Zwraca DataFrame z kolumnami przemianowanymi na nazwy wewnętrzne."""
    missing = [v for k, v in mapping.items()
               if v not in df.columns and k not in OPTIONAL]
    if missing:
        raise SystemExit(f"[{name}] brak kolumn {missing}.\n"
                         f"Dostępne: {list(df.columns)}\n"
                         f"Popraw słownik na górze skryptu.")
    out = pd.DataFrame()
    for k, v in mapping.items():
        out[k] = df[v] if v in df.columns else None
    return out


def main():
    postings = pick(pd.read_csv(DATA / "job_postings.csv"), POSTINGS_COLS, "postings")
    skills = pick(pd.read_csv(DATA / "job_skills.csv"), SKILLS_COLS, "skills")

    postings["posting_id"] = postings["posting_id"].astype(str)
    skills["posting_id"] = skills["posting_id"].astype(str)
    postings = postings.drop_duplicates("posting_id")
    postings["company"] = postings["company"].fillna("Unknown")
    postings["city"] = postings["city"].fillna("Unknown")
    postings["role"] = postings["role"].fillna("Other")
    postings["is_predicted"] = pd.to_numeric(
        postings["is_predicted"].replace({"True": 1, "False": 0, True: 1, False: 0}),
        errors="coerce")

    dates = pd.to_datetime(postings["date"], errors="coerce", utc=True)
    dates = dates.dt.tz_localize(None).fillna(pd.Timestamp.today().normalize())
    postings["full_date"] = dates.dt.normalize()
    postings["date_id"] = postings["full_date"].dt.strftime("%Y%m%d").astype(int)

    if DB_PATH.exists():
        DB_PATH.unlink()  # CSV jest źródłem prawdy, budujemy bazę od nowa
    con = sqlite3.connect(DB_PATH)
    con.executescript(Path("sql/01_schema.sql").read_text(encoding="utf-8"))

    # --- wymiary ---
    d = postings[["date_id", "full_date"]].drop_duplicates("date_id")
    con.executemany(
        "INSERT INTO dim_date VALUES (?,?,?,?,?)",
        [(int(r.date_id), r.full_date.strftime("%Y-%m-%d"), r.full_date.year,
          r.full_date.month, int(r.full_date.isocalendar().week))
         for r in d.itertuples()])

    def load_dim(table, col, key, values):
        con.executemany(f"INSERT INTO {table} ({col}) VALUES (?)",
                        [(v,) for v in sorted(set(values))])
        return dict(con.execute(f"SELECT {col}, {key} FROM {table}").fetchall())

    company_map = load_dim("dim_companies", "company_name", "company_id", postings["company"])
    city_map = load_dim("dim_locations", "city", "location_id", postings["city"])
    role_map = load_dim("dim_roles", "role_name", "role_id", postings["role"])

    sk = skills.dropna(subset=["skill"]).drop_duplicates(["posting_id", "skill"])
    sk_dim = sk.drop_duplicates("skill")[["skill", "category"]]
    con.executemany("INSERT INTO dim_skills (skill_name, category) VALUES (?,?)",
                    [(r.skill, None if pd.isna(r.category) else r.category)
                     for r in sk_dim.itertuples()])
    skill_map = dict(con.execute("SELECT skill_name, skill_id FROM dim_skills").fetchall())

    # --- fakty ---
    nn = lambda x: None if pd.isna(x) else x
    con.executemany(
        "INSERT INTO fact_job_postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.posting_id, int(r.date_id), company_map[r.company], city_map[r.city],
          role_map[r.role], nn(r.work_mode), nn(r.employment_type),
          nn(r.salary_min), nn(r.salary_max), nn(r.salary_avg),
          None if pd.isna(r.is_predicted) else int(r.is_predicted),
          nn(r.title))
         for r in postings.itertuples()])

    # --- bridge ---
    valid = set(postings["posting_id"])
    con.executemany(
        "INSERT OR IGNORE INTO bridge_job_skills VALUES (?,?)",
        [(r.posting_id, skill_map[r.skill])
         for r in sk.itertuples() if r.posting_id in valid])

    # --- widoki ---
    con.executescript(Path("sql/02_views.sql").read_text(encoding="utf-8"))
    con.commit()

    # --- kontrola ---
    print("Liczba wierszy:")
    for t in ["dim_date", "dim_companies", "dim_locations", "dim_roles",
              "dim_skills", "fact_job_postings", "bridge_job_skills"]:
        print(f"  {t:20s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    print("\nv_overview:")
    print(pd.read_sql("SELECT * FROM v_overview", con).to_string(index=False))
    print("\nv_salary_by_role:")
    print(pd.read_sql("SELECT * FROM v_salary_by_role ORDER BY postings DESC", con)
          .to_string(index=False))

    # --- eksport widoków dla Tableau ---
    OUT_DIR.mkdir(exist_ok=True)
    views = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='view'")]
    for v in views:
        pd.read_sql(f"SELECT * FROM {v}", con).to_csv(OUT_DIR / f"{v}.csv", index=False)
    print(f"\nWyeksportowano {len(views)} widoków do {OUT_DIR}/")
    con.close()


if __name__ == "__main__":
    main()
