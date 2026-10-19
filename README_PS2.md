# Quantitative Investing — Problem Set 2

This is the PS2 GitHub submission. The inherited `README.md` describes PS1; it is preserved as historical documentation. PS2 extends the PS1 source without including its licensed datasets or private course-submission ZIP.

## Final report

[Final PS2 submission PDF](outputs/ps2/empirical_20261019T054917302234Z/submission_20261019T124637426467Z/PS2_final_submission.pdf): four main-writeup pages, seven numerical tables and four figures. [Assignment](docs/ps2.pdf) and [requirement review](outputs/ps2/empirical_20261019T054917302234Z/submission_20261019T124637426467Z/requirement_review.md) document the scope and remaining qualifications.

## Repository contents

- `src/ps2/`: beta estimation, factor forecasts, weighted residualization, empirical metrics and editable report components.
- `src/ps1/`: inherited source dependencies, preserved unchanged.
- `scripts/`: bounded acquisition tools, empirical integration and report generation. Acquisition requires independent authorized WRDS access; scripts do not contain credentials.
- `tests/`: synthetic and local verification tests.
- `requirements.lock` and `pyproject.toml`: dependency and project configuration.
- `outputs/ps2/empirical_20261019T054917302234Z/`: selected aggregate statistics, monthly aggregate diagnostics, final narrative, display-table CSVs and four original figures. These are saved results, not stock-level datasets.

All raw/processed datasets, WRDS/CRSP/Compustat observations, Parquet files, virtual environments, caches, archives and intermediate generated reports remain local and are ignored. The legacy PS1 ZIP is intentionally excluded because it contains licensed snapshots. A fresh checkout does **not** contain the data needed for an empirical recomputation. Do not run the inherited PS1 ZIP reproduction instructions expecting included snapshots.

## Verification and reproduction

With a compatible Python environment containing the pinned dependencies, synthetic tests can be run with:

```powershell
python -B -m unittest discover -s tests -v
```

Data-dependent checks or report rebuilds may require excluded local artifacts. The last saved complete suite result was 162 passing tests; Git preparation does not rerun empirical computations. See the final report's [reproducibility notes](outputs/ps2/empirical_20261019T054917302234Z/submission_20261019T124637426467Z/REPRODUCIBILITY.md) for original processing commands and local input requirements. Saved monthly loss series, coefficient series and exhibit inputs are provided to inspect the reported results without redistributing stock observations.

The report explicitly discloses the expanding-since-1960 beta benchmark, Welch decay/aging conventions, accounting-vintage limitations, matched-sample comparisons and unavailable no-profitability coefficients. These qualifications are unchanged.

Before committing additional files, inspect `git diff --cached --stat` and run `python -B scripts/ps2_check_git_submission.py`. The checker examines staged blobs for credential indicators, forbidden data paths and files larger than 50,000,000 bytes; it prints paths and categories rather than secret values. Pattern-based checks cannot guarantee detection of every possible secret. Do not force-add licensed datasets or authentication files.
