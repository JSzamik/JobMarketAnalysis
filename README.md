# 📊 Data Job Market Analysis (Poland)

**What does the Polish data job market actually look like, and which tech stack do you need for each role?**

An end-to-end analytics project: live job postings from the **Adzuna API** are cleaned in **Python**, modelled into a **star schema in SQLite**, exposed through **SQL views**, and visualised in an interactive **Power BI** dashboard.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-star_schema-003B57?logo=sqlite&logoColor=white)
![Power BI](https://img.shields.io/badge/Power_BI-dashboard-F2C811?logo=powerbi&logoColor=black)
![Pandas](https://img.shields.io/badge/pandas-ETL-150458?logo=pandas&logoColor=white)

---

## 🖼️ Dashboard

### 1. Overview
KPIs, role distribution, average salary by role and work mode split.

![Overview](images/overview.png)

### 2. Tech Stack Benchmark
Pick a role (and optionally a skill category) and see which skills show up most often in its job postings.

![Tech Stack Benchmark](images/tech_stack.png)

<!-- Optional: add more pages here, e.g. a salary calculator
### 3. Salary by skill
![Salary by skill](images/salary_by_skill.png)
-->

---

## 🔎 Key numbers

| Metric | Value |
|---|---|
| Job postings analysed | **1,807** |
| Unique companies / locations | 532 / 45 |
| Postings with a real salary range | **299** (16.5%) |
| Average monthly salary (PLN, gross) | **~24,300** |
| Remote or hybrid | **10.7%** |
| Most common role | **Data Engineer** (837 postings, 46%) |

**What the data says**

- 🐍 **Python (47.6%) and SQL (38.7%)** are the top two skills in Data Engineer postings, followed by **Databricks (35.8%)**, **Spark (31.9%)** and **Azure (27.0%)**.
- ☁️ Azure is requested more often than AWS or GCP for Data Engineers in this dataset.
- 💰 Salary ranges are disclosed in only ~1 out of 6 postings, so salary figures should be read as indicative, not as market truth.
- 🏠 The vast majority of postings do not state a work mode at all.

---

## 🏗️ Architecture

```
Adzuna API ──► job_pipeline.py ──► CSV ──► load_to_db.py ──► SQLite (star schema)
 (6 queries)    clean + enrich                                       │
                                                                 SQL views
                                                                     │
                                                                CSV exports ──► Power BI
```

### Step 1: extraction & cleaning (`job_pipeline.py`)
- Pulls postings from the Adzuna API for 6 search phrases: *data analyst, data engineer, analytics engineer, bi developer, data scientist, machine learning engineer*. Requests use retries with backoff.
- Saves raw responses as `raw_<date>.json` so every run is reproducible.
- **Salaries** are normalised to **monthly PLN**. Where Adzuna only provides its own *predicted* salary, the value is left empty instead of polluting the analysis. Obvious outliers (outside 2,000 to 100,000 PLN/month) are dropped.
- **Role classification** uses ordered title rules (first match wins), e.g. *Analytics Engineer → ML Engineer → Data Engineer → ...*, with an `Other` fallback.
- **Skill extraction** runs a dictionary of ~45 skills across 12 categories (Language, Big Data, Warehouse, BI, Cloud, ML Framework, MLOps, ...) using regex with lookarounds, so `C++`, `C#` and `.NET` style tokens do not break.
- **Work mode** (remote / hybrid / onsite-unspecified) is detected from title and description in English and Polish.
- NBP exchange rates are fetched for foreign-currency handling, with a fallback if the API is down.

### Step 2: warehouse (`load_to_db.py`)
Builds a SQLite **star schema** from scratch on every run (CSV is the source of truth):

```
dim_date ─┐
dim_companies ─┤
dim_locations ─┼──► fact_job_postings ◄──► bridge_job_skills ◄── dim_skills
dim_roles ─┘
```

`bridge_job_skills` is a many-to-many bridge, because one posting requires many skills.

### Step 3: SQL views (`sql/02_views.sql`)
| View | Purpose |
|---|---|
| `v_overview` | KPI cards: totals, salary coverage, remote share |
| `v_work_mode` | Remote / Hybrid / Not specified split |
| `v_salary_by_role` | Postings, salary coverage and average salary per role |
| `v_salary_by_skill` | Average, min and max salary per skill and role |
| `v_skill_demand_by_role` | % of a role's postings that mention each skill (Tech Stack Benchmark) |
| `v_postings_skills_flat` | Flat posting × skill table for ad-hoc analysis |

Salary metrics always use **real ranges only** (`salary_is_predicted = 0`).

### Step 4: visualisation
Views are exported to CSV and loaded into Power BI (`JobMarketAnalysis.pbix`).

---

## 🚀 Run it yourself

```bash
# 1. Install
git clone <your-repo-url>
cd <repo>
pip install -r requirements.txt

# 2. Add Adzuna credentials (free key from developer.adzuna.com)
echo "ADZUNA_APP_ID=your_id"   >  .env
echo "ADZUNA_APP_KEY=your_key" >> .env

# 3. Fetch + clean (50 postings per page, per query)
python job_pipeline.py --pages 3

# 4. Build the database, views and CSV exports
python load_to_db.py
```

Outputs land in `data/`: `job_postings.csv`, `job_skills.csv`, `jobs.db` and `data/tableau/v_*.csv` (view exports, usable in Power BI as well).

---

## 📁 Project structure

```
├── job_pipeline.py        # API -> cleaning -> CSV
├── load_to_db.py          # CSV -> SQLite star schema -> views -> exports
├── sql/
│   ├── 01_schema.sql      # tables, keys, indexes
│   └── 02_views.sql       # analytical views
├── data/                  # raw JSON, CSVs, jobs.db, view exports
├── images/                # dashboard screenshots
├── JobMarketAnalysis.pbix # Power BI report
├── requirements.txt
└── README.md
```

---

## ⚠️ Limitations

- **Salary coverage is low (16.5%).** Most postings have no declared range, so averages rest on a few hundred records and small roles (e.g. Analytics Engineer, 4 salaries) are statistically weak.
- **Work mode is regex-based** on title and description. Postings that do not mention it are labelled *onsite/unspecified*, so the remote/hybrid share is a lower bound.
- **Role and skill detection are rule-based**, not ML. Edge cases get misclassified or land in `Other`.
- Data is a **snapshot from a single source** (Adzuna), so it reflects that aggregator's coverage, not the whole market.

## 🔮 Ideas for next steps

- Scheduled refresh (GitHub Actions / cron) to build a time series of demand
- Salary calculator by skill set, based on `v_salary_by_skill`
- Better work-mode detection with a text classifier
- Add more sources (e.g. justjoin.it, No Fluff Jobs)

---

## 👤 Author

**Jakub Szamik**
📫 <!-- LinkedIn / GitHub / email -->
