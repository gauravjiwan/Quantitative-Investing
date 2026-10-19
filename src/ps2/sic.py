"""Closed historical SIC intervals and actual month-end joins; no data repair."""
import duckdb


class SICError(ValueError):
    pass


def validate_intervals(con, relation='history'):
    if relation != 'history':
        raise SICError('Only the registered history relation is supported')
    counts = con.execute('''SELECT count(*),
        count(*) FILTER(WHERE permno IS NULL),
        count(*) FILTER(WHERE secinfostartdt>secinfoenddt),
        count(*) FILTER(WHERE secinfostartdt IS NULL),
        count(*) FILTER(WHERE secinfoenddt IS NULL),
        count(*) FILTER(WHERE siccd IS NULL),
        count(*) FILTER(WHERE siccd<100 OR siccd>9999)
        FROM history''').fetchone()
    duplicates = con.execute('''SELECT count(*) FROM
        (SELECT permno,secinfostartdt,secinfoenddt,count(*) n FROM history
         GROUP BY 1,2,3 HAVING count(*)>1)''').fetchone()[0]
    overlaps = con.execute('''WITH x AS (
      SELECT permno,coalesce(CAST(secinfostartdt AS DATE),DATE '1900-01-01') a,
        max(coalesce(CAST(secinfoenddt AS DATE),DATE '2100-12-31')) OVER
        (PARTITION BY permno ORDER BY coalesce(CAST(secinfostartdt AS DATE),DATE '1900-01-01'),
         coalesce(CAST(secinfoenddt AS DATE),DATE '2100-12-31') ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prev_end
      FROM history)
      SELECT count(*) FROM x WHERE a<=prev_end''').fetchone()[0]
    report = dict(zip(('interval_rows','null_permno','reversed_intervals','open_start',
                      'open_end','null_SIC','invalid_nonnull_SIC'), counts))
    report.update(duplicate_interval_keys=duplicates, overlapping_intervals=overlaps)
    if report['null_permno'] or report['reversed_intervals'] or duplicates or overlaps:
        raise SICError('Invalid, duplicate or overlapping historical intervals: ' + str(report))
    return report


def join_month_ends(con):
    """Register target_keys and history first. Return SQL, never choose a match."""
    invalid = con.execute('''SELECT count(*) FROM target_keys
        WHERE permno IS NULL OR observation_month IS NULL OR as_of_date IS NULL
        OR as_of_date<>last_day(observation_month)''').fetchone()[0]
    duplicate = con.execute('''SELECT count(*) FROM
        (SELECT permno,observation_month FROM target_keys GROUP BY 1,2 HAVING count(*)>1)''').fetchone()[0]
    if invalid or duplicate:
        raise SICError('Target keys must be unique/non-null with actual calendar month ends')
    sql = '''SELECT t.*,h.permco AS sic_permco,h.siccd,
        h.secinfostartdt,h.secinfoenddt,
        h.permno IS NOT NULL AS interval_matched
      FROM target_keys t LEFT JOIN history h ON t.permno=h.permno
       AND coalesce(CAST(h.secinfostartdt AS DATE),DATE '1900-01-01')<=t.as_of_date
       AND coalesce(CAST(h.secinfoenddt AS DATE),DATE '2100-12-31')>=t.as_of_date'''
    multiple = con.execute('''SELECT count(*) FROM (SELECT permno,observation_month
        FROM (''' + sql + ''') GROUP BY 1,2 HAVING count(*)>1)''').fetchone()[0]
    if multiple:
        raise SICError('Multiple historical SIC matches; no arbitrary match selected')
    return sql
