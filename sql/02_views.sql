-- Płace liczone tylko z prawdziwych widełek (salary_is_predicted = 0 lub brak flagi)

-- KPI do sekcji Overview
CREATE VIEW v_overview AS
SELECT COUNT(*) AS total_postings,
       COUNT(CASE WHEN COALESCE(salary_is_predicted,0)=0 THEN salary_avg_pln END) AS postings_with_salary,
       ROUND(AVG(CASE WHEN COALESCE(salary_is_predicted,0)=0 THEN salary_avg_pln END)) AS avg_salary_pln,
       ROUND(100.0 * SUM(work_mode IN ('remote','hybrid')) / COUNT(*), 1) AS pct_remote_or_hybrid,
       ROUND(100.0 * SUM(work_mode IN ('remote','hybrid','onsite')) / COUNT(*), 1) AS pct_mode_declared
FROM fact_job_postings;

-- Tryb pracy (z jawnym "Not specified")
CREATE VIEW v_work_mode AS
SELECT CASE work_mode
         WHEN 'remote' THEN 'Remote'
         WHEN 'hybrid' THEN 'Hybrid'
         ELSE 'Not specified'
       END AS work_mode,
       COUNT(*) AS postings,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM fact_job_postings), 1) AS pct
FROM fact_job_postings
GROUP BY 1;

-- Tech Stack Benchmark: % ofert danej roli wymagających skilla
CREATE VIEW v_skill_demand_by_role AS
SELECT r.role_name,
       s.skill_name,
       s.category,
       COUNT(*) AS postings,
       ROUND(100.0 * COUNT(*) / rt.total, 1) AS pct_of_role_postings
FROM bridge_job_skills b
JOIN fact_job_postings f ON f.posting_id = b.posting_id
JOIN dim_roles  r ON r.role_id  = f.role_id
JOIN dim_skills s ON s.skill_id = b.skill_id
JOIN (SELECT role_id, COUNT(*) AS total
      FROM fact_job_postings GROUP BY role_id) rt ON rt.role_id = f.role_id
GROUP BY r.role_name, s.skill_name, s.category, rt.total;

-- Płace per skill i rola
CREATE VIEW v_salary_by_skill AS
SELECT s.skill_name,
       r.role_name,
       COUNT(f.salary_avg_pln)       AS n_with_salary,
       ROUND(AVG(f.salary_avg_pln))  AS avg_salary_pln,
       ROUND(MIN(f.salary_min_pln))  AS min_salary_pln,
       ROUND(MAX(f.salary_max_pln))  AS max_salary_pln
FROM bridge_job_skills b
JOIN fact_job_postings f ON f.posting_id = b.posting_id
JOIN dim_roles  r ON r.role_id  = f.role_id
JOIN dim_skills s ON s.skill_id = b.skill_id
WHERE f.salary_avg_pln IS NOT NULL
  AND COALESCE(f.salary_is_predicted,0) = 0
GROUP BY s.skill_name, r.role_name;

-- Płace per rola (baza pod kalkulator)
CREATE VIEW v_salary_by_role AS
SELECT r.role_name,
       COUNT(f.posting_id) AS postings,
       COUNT(CASE WHEN COALESCE(f.salary_is_predicted,0)=0 THEN f.salary_avg_pln END) AS n_with_salary,
       ROUND(AVG(CASE WHEN COALESCE(f.salary_is_predicted,0)=0 THEN f.salary_avg_pln END)) AS avg_salary_pln
FROM fact_job_postings f
JOIN dim_roles r ON r.role_id = f.role_id
GROUP BY r.role_name;

-- Płaska tabela oferta x skill, do kalkulatora w Tableau (flagę salary_is_predicted filtrujesz w Tableau)
CREATE VIEW v_postings_skills_flat AS
SELECT f.posting_id, f.title, r.role_name, f.work_mode,
       f.salary_min_pln, f.salary_max_pln, f.salary_avg_pln, f.salary_is_predicted,
       s.skill_name, s.category
FROM fact_job_postings f
JOIN dim_roles r ON r.role_id = f.role_id
LEFT JOIN bridge_job_skills b ON b.posting_id = f.posting_id
LEFT JOIN dim_skills s ON s.skill_id = b.skill_id;
