"""Rebuild the private course submission from its bundled raw snapshots."""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], env: dict[str, str]) -> None:
    print("Running:", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> None:
    if not ((3, 11) <= sys.version_info[:2] < (3, 14)):
        raise SystemExit("Python 3.11, 3.12, or 3.13 is required.")
    required = ["crsp_monthly", "crsp_names", "crsp_index", "compustat_annual", "ccm_link"]
    missing = [kind for kind in required if not list((ROOT / "data" / "raw" / kind).glob("*.parquet"))]
    if missing:
        raise SystemExit("Missing bundled raw snapshots: " + ", ".join(missing))

    env = os.environ.copy()
    env["PS1_ROOT"] = str(ROOT)
    env["MPLCONFIGDIR"] = str(ROOT / ".mplconfig")
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    run([sys.executable, "scripts/verify_submission.py"], env)
    environment = ROOT / ".venv"
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        print("Creating a local Python environment.", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    run([str(executable), "-m", "pip", "install", "--no-input", ".", "-c", "requirements.lock"], env)
    run([str(executable), "-m", "unittest", "discover", "-s", "tests", "-v"], env)
    run([str(executable), "-m", "ps1", "all"], env)
    run([str(executable), "scripts/verify_submission.py"], env)
    print("Reproduction complete: outputs/ps1_report.pdf and submission/PS1_Code.zip", flush=True)


if __name__ == "__main__":
    main()
