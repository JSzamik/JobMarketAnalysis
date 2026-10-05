PRAGMA foreign_keys = ON;

CREATE TABLE dim_date (
    date_id   INTEGER PRIMARY KEY,   -- np. 20261002
    full_date TEXT NOT NULL,
    year      INTEGER,
    month     INTEGER,
    week      INTEGER
);

CREATE TABLE dim_companies (
    company_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT UNIQUE NOT NULL
);

CREATE TABLE dim_locations (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    city        TEXT UNIQUE NOT NULL
);

CREATE TABLE dim_roles (
    role_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name TEXT UNIQUE NOT NULL
);

CREATE TABLE dim_skills (
    skill_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT UNIQUE NOT NULL,
    category   TEXT
);

CREATE TABLE fact_job_postings (
    posting_id          TEXT PRIMARY KEY,
    date_id             INTEGER REFERENCES dim_date(date_id),
    company_id          INTEGER REFERENCES dim_companies(company_id),
    location_id         INTEGER REFERENCES dim_locations(location_id),
    role_id             INTEGER REFERENCES dim_roles(role_id),
    work_mode           TEXT,
    employment_type     TEXT,
    salary_min_pln      REAL,
    salary_max_pln      REAL,
    salary_avg_pln      REAL,
    salary_is_predicted INTEGER,      -- 1 = szacunek Adzuny, 0 = widełki z oferty
    title               TEXT
);

CREATE TABLE bridge_job_skills (
    posting_id TEXT    REFERENCES fact_job_postings(posting_id),
    skill_id   INTEGER REFERENCES dim_skills(skill_id),
    PRIMARY KEY (posting_id, skill_id)
);

CREATE INDEX idx_fact_role    ON fact_job_postings(role_id);
CREATE INDEX idx_bridge_skill ON bridge_job_skills(skill_id);
