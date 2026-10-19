-- Run against local ps1.duckdb after the panel and formation stages.
SELECT permno, month, COUNT(*) AS n FROM security_month GROUP BY 1,2 HAVING COUNT(*) <> 1;
SELECT permco, month, COUNT(*) AS n FROM company_month GROUP BY 1,2 HAVING COUNT(*) <> 1;
SELECT permco, formation_year, COUNT(*) AS n FROM formation GROUP BY 1,2 HAVING COUNT(*) <> 1;
SELECT COUNT(DISTINCT month) AS research_months FROM security_month WHERE month BETWEEN DATE '1963-07-01' AND DATE '2025-12-01';
SELECT month, COUNT(*) AS company_count, SUM(CASE WHEN partial_share_class_return THEN 1 ELSE 0 END) AS partial_class_count
FROM company_month GROUP BY month ORDER BY month;
