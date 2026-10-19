# Quantitative Investing — Problem Set 1

This repository contains the Python and SQL analysis for all four questions in FINC-B8420 Problem Set 1. The research window is July 1963–December 2025 (750 monthly returns). A copy of the English answer PDF is included at `outputs/ps1_report.pdf`.

## What is in the course submission

The local delivery folder contains exactly two files:

- `PS1_Answers.pdf`: the answers, methodology, result tables, and figures.
- `PS1_Code.zip`: this code repository, a copy of the answer PDF, pinned dependencies, verified WRDS and French data snapshots, tests, and aggregate portfolio results used in the report. This ZIP is for the private course submission, not a public repository.

The ZIP includes the fixed WRDS and Ken French snapshots needed for a complete offline data-to-report recomputation. It excludes credentials, pilot data, the local DuckDB cache, and virtual environments. No WRDS login or data download is needed to rerun the submitted analysis. The Python packages listed in `requirements.lock` are installed automatically by the one-command runner; this requires Python 3.11–3.13 and access to a Python package index. The code never substitutes public web-price data for the research sources.

## One-command reproduction from the submitted ZIP

Extract the ZIP, open a terminal inside `PS1_Code`, and run this command on macOS or Linux:

```bash
./scripts/run.sh
```

The launcher selects a compatible Python version. On Windows, use `py -3.12 scripts/reproduce.py` (or another installed Python 3.11–3.13 interpreter). The runner creates its own local environment if needed, installs pinned packages, runs the economic unit tests, rebuilds all four questions from the included raw snapshots, regenerates the PDF and ZIP, and checks the saved outputs. It does not contact WRDS. Raw snapshots are checked against their SHA-256 manifests before use.

## Quick start after extracting `PS1_Code.zip`

Use Python 3.11–3.13. The following script creates `.venv` and installs the pinned packages:

```bash
cd PS1_Code
./scripts/setup_env.sh
source .venv/bin/activate
python -m unittest discover -s tests -v
python scripts/render_report_pdf.py
```

The last command rebuilds `outputs/ps1_report.pdf` from the included `outputs/ps1_report.md` and figures; it does not contact WRDS. `python scripts/verify_submission.py` performs a standard-library-only check of the included files, report sections, and 750-month return exports. It can run before package installation.

## Full data-to-results rebuild

The included snapshots make `inventory` and `extract` unnecessary for course grading. The individual analysis stages can also be run in this order from an activated environment:

```bash
python -m ps1 references
python -m ps1 panel
python -m ps1 q1
python -m ps1 characteristics
python -m ps1 q2
python -m ps1 q3
python -m ps1 q4
python -m ps1 report
```

`data/raw/` contains checksum-protected annual snapshots; no password is stored in source files. `python -m ps1 all` reruns the calculations and report. `config/field_map.toml` records the verified CIZ, Compustat, and CCM tables and field names; `config/project.toml` fixes the sample and formation rules. The SQL queries and panel checks are in `sql/`, the calculations are in `src/ps1/`, and method choices are recorded in `decision_log.md`.

All internal returns use decimal units. The report documents portfolio construction choices, comparisons with CRSP/Ken French, known link and coverage limitations, and how AI assistance was used.
