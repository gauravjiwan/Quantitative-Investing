# Reproducibility and submission notes

The starting point is the accepted report_v2.pdf identified and hashed in build.json.
Its11 exhibit pages are imported directly; no table or plot is regenerated.
All original page-content streams remain byte-identical. New main text is stored
in main_writeup.md/JSON and authored in docs/ps2_submission_narrative.json.
The PDF assembler supports only the repository's classic-xref ReportLab files;
unsupported/encrypted/incrementally updated PDFs are rejected. It renumbers
object references outside strings/streams, attaches a new page tree, and checks
all11 exhibit content streams against the accepted baseline.

Reproduce with the existing virtual environment (no package installation):

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_polish_submission.py --baseline outputs/ps2/empirical_20261019T054917302234Z/revision_v2_20261019T112854522734Z/report_v2.pdf
```

The command creates a fresh version directory, runs the full test suite, and
checks that every accepted baseline artifact is unchanged. Rendering uses
scripts/ps2_render_pdf.ps1 with Windows.Data.Pdf; inspect all generated pages.
Its interactive invocation is documented in the accepted revision's REPRODUCE.md.
No estimates, daily data processing, premium forecasts, WLS regressions or WRDS
queries are executed by this report-only command.

Existing numerical provenance, validation/test logs, source hashes, elapsed times,
memory/storage measures and preserved failed technical attempts remain in the
accepted empirical run and revision directories. In particular:

- source_data.json fingerprints saved tables, manifests and matched products.
- data_validation.json documents common keys, monthly counts and forecast horizons.
- The parent empirical run's final_validation.json covers accepted daily hashes.
- The parent runtime_and_storage.json records processing performance and qualifications.
- Original failures (local SIC memory/join attempts, beta date conversion, SQL alias
  and Q2 finalization path) remain audit history; they are not submission narrative.

Numerical policies: daily same-date RF; monthly PS1 RF for monthly models; PERMNO
security returns and current security ME; annual PS1 company fundamentals linked
at the origin. Positive origin ME and common stock-month samples are required.
Daily beta eligibility retains valid NA missing flags and D1-D4/DU single-trading-
period durations, with minimum counts stated in the main writeup. Monthly losses
normalize EW/VW within month and average months equally. HAC uses Bartlett lags12
without finite-sample correction. Accounting follows prior-year/June formation,
without historical release-date vintages; missing/invalid SIC is not Other.

Q1 k=1 makes the shrinkage rule identical to Welch. Original saved SQL summaries
contain roundoff-scale nonzero loss differences and SEs; their ratios are not
meaningful t-statistics. Table3 preserves these raw numbers and states undefined
for the identity-case t. Q3 no-profitability coefficients other than value were
not saved and remain Not estimated. No additional regressions populate them.

Submission still requires the group's Canvas upload plus code or a repository
link, as stated on assignment p.1. This script does not upload or submit anything.
