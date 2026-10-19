"""Read-only size, credential-pattern and licensed-data audit of staged Git blobs.

No network, data acquisition or empirical calculations are performed. Findings
contain only paths, line numbers and categories, never matching secret values.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 50_000_000


def git(*args: str) -> bytes:
    # Trust this explicitly selected workspace for this invocation only. This
    # also permits auditing under the Windows sandbox's different user account.
    return subprocess.check_output(
        ['git', '-c', f'safe.directory={ROOT.as_posix()}', *args], cwd=ROOT
    )


def main() -> int:
    entries = git('ls-files', '--stage', '-z').split(b'\0')
    findings = []
    files = []
    patterns = {
        'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
        'aws-access-key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
        'authenticated-url': re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@', re.I),
        'literal-secret': re.compile(r'''(?i)\b(?:[a-z0-9]+_)*(?:password|passwd|api_key|access_token|auth_token|client_secret|secret_key)\s*[:=]\s*["']([^"'\r\n]{8,})["']'''),
    }
    for entry in entries:
        if not entry:
            continue
        info, rawpath = entry.split(b'\t', 1)
        mode, oid, stage = info.decode().split()
        path = rawpath.decode('utf-8')
        blob = git('cat-file', 'blob', oid)
        files.append({'path': path, 'bytes': len(blob)})
        if stage != '0' or mode not in ('100644', '100755'):
            findings.append({'path': path, 'category': 'non-regular-or-unmerged-entry'})
        lower = path.lower()
        parts = lower.split('/')
        if (parts[0] in ('data', '.venv', 'submission')
                or '__pycache__' in parts
                or lower.endswith(('.parquet', '.pq', '.duckdb', '.zip', '.pem', '.key'))
                or any(p.startswith('.env') or p.startswith('.pgpass') for p in parts)):
            findings.append({'path': path, 'category': 'forbidden-data-or-authentication-path'})
        if len(blob) > LIMIT:
            findings.append({'path': path, 'category': 'above-50MB', 'bytes': len(blob)})
        if Path(path).suffix.lower() in ('.pdf', '.png', '.jpg', '.docx'):
            continue
        text = blob.decode('utf-8', errors='replace')
        for line_number, line in enumerate(text.splitlines(), 1):
            for category, pattern in patterns.items():
                if pattern.search(line):
                    findings.append({'path': path, 'line': line_number, 'category': category})
    if not files:
        findings.append({'category': 'empty-index-cannot-audit'})
    summary = {
        'files': len(files), 'total_bytes': sum(f['bytes'] for f in files),
        'largest_files': sorted(files, key=lambda f: f['bytes'], reverse=True)[:5],
        'limit_bytes': LIMIT, 'findings': findings,
        'scope': 'staged blobs; pattern-based secret scan, not a guarantee',
    }
    print(json.dumps(summary, indent=2))
    return int(bool(findings))


if __name__ == '__main__':
    sys.exit(main())
