-- Metadata only; no research observations.
SELECT table_schema,table_name,ordinal_position,column_name,data_type
FROM information_schema.columns WHERE (table_schema ILIKE '%crsp%' OR table_schema ILIKE '%comp%')
AND (table_name ILIKE '%mth%' OR table_name ILIKE '%monthly%' OR table_name ILIKE '%security%'
OR table_name ILIKE '%name%' OR table_name ILIKE '%index%' OR table_name ILIKE '%funda%'
OR table_name ILIKE '%link%') ORDER BY table_schema,table_name,ordinal_position;
