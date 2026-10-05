"""
Krok 1: Pobieranie ofert pracy (Adzuna API) -> czyszczenie -> pliki CSV.

Uruchomienie:
    python job_pipeline.py --pages 3
Wyniki w katalogu data/:
    raw_<data>.json     - surowe odpowiedzi API (do odtwarzalności)
    job_postings.csv    - jedna oferta = jeden wiersz (przyszła fact_job_postings)
    job_skills.csv      - oferta x umiejętność (przyszła bridge_job_skills)
"""
import argparse
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jobs")

COUNTRY = "pl"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/?format=json"
DATA_DIR = Path("data")

# Frazy wyszukiwania - każda dostaje własne zapytanie do API
SEARCH_QUERIES = [
    "data analyst", "data engineer", "analytics engineer", "bi developer",
    "data scientist", "machine learning engineer",
]

# ---------------------------------------------------------------------------
# Słownik umiejętności: nazwa -> (kategoria, regex)
# Lookarounds zamiast \b, bo \b psuje się na "C++", "C#", ".NET".
# ---------------------------------------------------------------------------
SKILLS = {
    # --- Języki ---
    "SQL": ("Language", r"sql(?!\s*server)|t-sql|pl/sql|postgres\w*|mysql"),
    "Python": ("Language", r"python"),
    "R": ("Language", r"r(?=\s+(?:language|studio|programming))|rstudio"),
    "Scala": ("Language", r"scala"),
    "Java": ("Language", r"java(?!\s*script)"),
    # --- Big Data / Data Engineering ---
    "Spark": ("Big Data", r"(?:py|apache\s+)?spark"),
    "Kafka": ("Big Data", r"kafka"),
    "Hadoop": ("Big Data", r"hadoop"),
    "Airflow": ("Orchestration", r"airflow"),
    "dbt": ("Transformation", r"dbt"),
    "Snowflake": ("Warehouse", r"snowflake"),
    "BigQuery": ("Warehouse", r"big\s?query"),
    "Redshift": ("Warehouse", r"redshift"),
    "Databricks": ("Warehouse", r"databricks"),
    # --- BI ---
    "Tableau": ("BI", r"tableau"),
    "Power BI": ("BI", r"power\s?bi"),
    "Looker": ("BI", r"looker"),
    "Excel": ("BI", r"excel"),
    # --- Cloud ---
    "AWS": ("Cloud", r"aws|amazon\s+web\s+services"),
    "Azure": ("Cloud", r"azure"),
    "GCP": ("Cloud", r"gcp|google\s+cloud"),
    # --- DevOps ---
    "Docker": ("DevOps", r"docker"),
    "Kubernetes": ("DevOps", r"kubernetes|k8s"),
    "Git": ("DevOps", r"git(?:hub|lab)?"),
    # --- Biblioteki do danych ---
    "Pandas": ("Library", r"pandas"),
    "NumPy": ("Library", r"numpy"),
    "Jupyter": ("Library", r"jupyter"),
    # --- ML: frameworki ---
    "scikit-learn": ("ML Framework", r"scikit[-\s]?learn|sklearn"),
    "TensorFlow": ("ML Framework", r"tensorflow"),
    "PyTorch": ("ML Framework", r"pytorch"),
    "Keras": ("ML Framework", r"keras"),
    "XGBoost/LightGBM": ("ML Framework", r"xgboost|lightgbm|catboost"),
    "Hugging Face": ("ML Framework", r"hugging\s?face"),
    # --- ML: obszary ---
    "Machine Learning": ("ML Area", r"machine\s+learning|uczenie\s+maszynowe|ml"),
    "Deep Learning": ("ML Area", r"deep\s+learning|neural\s+networks?"),
    "NLP": ("ML Area", r"nlp|natural\s+language\s+processing"),
    "LLM / GenAI": ("ML Area", r"llms?|large\s+language\s+models?|gen(?:erative)?\s?ai|langchain"),
    "Computer Vision": ("ML Area", r"computer\s+vision|opencv"),
    "Time Series": ("ML Area", r"time[\s-]series|forecasting"),
    # --- Statystyka / eksperymenty ---
    "Statistics": ("Statistics", r"statistic\w*|statystyk\w*"),
    "A/B Testing": ("Statistics", r"a/b\s+test\w*|ab\s+test\w*|experimentation"),
    # --- MLOps ---
    "MLOps": ("MLOps", r"mlops"),
    "MLflow": ("MLOps", r"mlflow"),
    "Kubeflow": ("MLOps", r"kubeflow"),
    "SageMaker": ("MLOps", r"sagemaker"),
    "Vertex AI": ("MLOps", r"vertex\s?ai"),
    "FastAPI": ("MLOps", r"fastapi"),
}
SKILL_PATTERNS = {
    name: (cat, re.compile(rf"(?<![\w+#.])(?:{pat})(?![\w+#])", re.IGNORECASE))
    for name, (cat, pat) in SKILLS.items()
}

ROLE_RULES = [  # kolejność ma znaczenie: pierwsze trafienie wygrywa
    ("Analytics Engineer", r"analytics\s+engineer"),
    ("ML Engineer", r"\bml\s+engineer|machine\s+learning\s+engineer|mlops|\bai\s+engineer|deep\s+learning\s+engineer|\bllm\b"),
    ("Data Engineer", r"data\s+engineer|\betl\b|big\s?data\s+(?:engineer|developer)|\(big\s?data\)|engineer\s*\(data\)|data\s+(?:platform|software)|databricks|data\s+model(?:l)?ing"),
    ("Data Scientist", r"data\s+scien(?:tist|ce)|modelowani\w*\s+predykcyjn|predictive\s+model|machine\s+learning|\bml\b|\bai\b|\bnlp\b|computer\s+vision"),
    ("BI Developer", r"\bbi\b|business\s+intelligence|power\s?bi|tableau"),
    ("Data Analyst", r"data\s+analy|analityk\s+danych|analyst"),
]
REMOTE_RE = re.compile(r"remote|zdaln|home\s?office|work\s+from\s+home", re.I)
HYBRID_RE = re.compile(r"hybrid|hybryd", re.I)

# ---------------------------------------------------------------------------
# Pobieranie
# ---------------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch_adzuna(session, query: str, pages: int, per_page: int = 50) -> list[dict]:
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise SystemExit("Brak ADZUNA_APP_ID / ADZUNA_APP_KEY w pliku .env")

    out = []
    for page in range(1, pages + 1):
        resp = session.get(
            ADZUNA_URL.format(country=COUNTRY, page=page),
            params={
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": per_page,
                "what": query,
                "content-type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        log.info("'%s' strona %d: %d ofert", query, page, len(results))
        out.extend(results)
        if len(results) < per_page:
            break
        time.sleep(0.5)  # grzecznie wobec API
    return out


def get_fx_rates(session, currencies=("EUR", "USD", "GBP", "CHF")) -> dict[str, float]:
    """Kursy średnie NBP (tabela A). Fallback: kursy orientacyjne."""
    rates = {"PLN": 1.0}
    fallback = {"EUR": 4.3, "USD": 4.0, "GBP": 5.0, "CHF": 4.5}
    for code in currencies:
        try:
            r = session.get(NBP_URL.format(code=code), timeout=15)
            r.raise_for_status()
            rates[code] = r.json()["rates"][0]["mid"]
        except Exception as exc:  # noqa: BLE001
            log.warning("NBP %s niedostępny (%s) - używam kursu orientacyjnego", code, exc)
            rates[code] = fallback[code]
    return rates


# ---------------------------------------------------------------------------
# Czyszczenie
# ---------------------------------------------------------------------------
HOURS_PER_MONTH = 168
DAYS_PER_MONTH = 21
TO_MONTHLY = {
    "hour": HOURS_PER_MONTH,
    "day": DAYS_PER_MONTH,
    "month": 1,
    "year": 1 / 12,
}


def to_monthly_pln(value, period: str, currency: str, rates: dict) -> float | None:
    """Stawka (godz./dzień/mies./rok, dowolna waluta) -> miesięcznie w PLN."""
    if value is None or pd.isna(value) or currency not in rates:
        return None
    monthly = float(value) * TO_MONTHLY[period] * rates[currency]
    # sanity check - odrzucamy oczywiste błędy (np. brakujące zera)
    return round(monthly, 2) if 2_000 <= monthly <= 100_000 else None


def classify_role(title: str) -> str:
    for role, pattern in ROLE_RULES:
        if re.search(pattern, title, re.I):
            return role
    return "Other"


def work_mode(text: str) -> str:
    if HYBRID_RE.search(text):
        return "hybrid"
    if REMOTE_RE.search(text):
        return "remote"
    return "onsite/unspecified"


def extract_skills(text: str) -> list[tuple[str, str]]:
    return [(n, cat) for n, (cat, rx) in SKILL_PATTERNS.items() if rx.search(text)]


def clean_offers(raw: list[dict], rates: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    postings, skills = [], []
    for o in raw:
        title = o.get("title") or ""
        desc = re.sub(r"<[^>]+>", " ", o.get("description") or "")
        text = f"{title} {desc}"
        pid = f"adzuna_{o['id']}"
        predicted = str(o.get("salary_is_predicted", "0")) == "1"

        # Adzuna zwraca zarobki roczne; przy predicted=1 to estymata serwisu,
        # nie prawdziwe widełki -> zostawiamy NaN, żeby nie fałszować analizy.
        s_min = None if predicted else to_monthly_pln(o.get("salary_min"), "year", "PLN", rates)
        s_max = None if predicted else to_monthly_pln(o.get("salary_max"), "year", "PLN", rates)

        postings.append({
            "posting_id": pid,
            "source": "adzuna",
            "title": title.strip(),
            "role": classify_role(title),
            "company": (o.get("company") or {}).get("display_name", "Unknown").strip(),
            "location": (o.get("location") or {}).get("display_name", "Unknown"),
            "posted_date": o.get("created"),
            "contract_time": o.get("contract_time"),   # full_time / part_time
            "contract_type": o.get("contract_type"),   # permanent / contract
            "salary_min_pln": s_min,
            "salary_max_pln": s_max,
            "salary_is_predicted": predicted,
            "work_mode": work_mode(text),
            "url": o.get("redirect_url"),
        })
        for name, cat in extract_skills(text):
            skills.append({"posting_id": pid, "skill_name": name, "category": cat})

    df = pd.DataFrame(postings).drop_duplicates("posting_id")
    df["posted_date"] = pd.to_datetime(df["posted_date"], errors="coerce", utc=True).dt.date
    df["salary_avg_pln"] = df[["salary_min_pln", "salary_max_pln"]].mean(axis=1)

    df_sk = pd.DataFrame(skills, columns=["posting_id", "skill_name", "category"]).drop_duplicates()
    return df, df_sk


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2, help="stron na zapytanie (50 ofert/strona)")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    session = make_session()

    raw = []
    for q in SEARCH_QUERIES:
        raw.extend(fetch_adzuna(session, q, args.pages))
    log.info("Pobrano łącznie %d surowych ofert", len(raw))

    (DATA_DIR / f"raw_{date.today()}.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )

    rates = get_fx_rates(session)
    df, df_sk = clean_offers(raw, rates)

    df.to_csv(DATA_DIR / "job_postings.csv", index=False, encoding="utf-8")
    df_sk.to_csv(DATA_DIR / "job_skills.csv", index=False, encoding="utf-8")

    log.info("Oferty po deduplikacji: %d | z widełkami: %d | wpisów skill: %d",
             len(df), df["salary_avg_pln"].notna().sum(), len(df_sk))
    print(df["role"].value_counts().to_string())
    print(df_sk["skill_name"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()