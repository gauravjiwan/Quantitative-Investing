"""Fetch two explicitly authorized official French archives; preserve originals."""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import urllib.request
from urllib.parse import urljoin, urlparse
import zipfile

from ps2_extract_daily import ROOT, dump_new, sha256, utc

SOURCES = (
    ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
     "F-F_Research_Data_Factors_daily_CSV.zip"),
    ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_12_ind_port.html",
     "Siccodes12.zip"),
)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.hrefs.extend(v for k, v in attrs if k.lower() == "href" and v)


def official_link(page, html, filename):
    parser = Links()
    parser.feed(html)
    matches = {urljoin(page, href) for href in parser.hrefs
               if Path(urlparse(href).path).name.lower() == filename.lower()}
    if len(matches) != 1:
        raise ValueError("Official archive link absent or ambiguous; no guessed URL fallback")
    url = matches.pop()
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "mba.tuck.dartmouth.edu":
        raise ValueError("Archive link is outside the authorized official HTTPS host")
    return url


def fetch(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "PS2 academic reproducibility audit"})
    with urllib.request.urlopen(request, timeout=60) as response:
        final_url = response.geturl()
        if urlparse(final_url).scheme != "https" or urlparse(final_url).hostname != "mba.tuck.dartmouth.edu":
            raise ValueError("Unexpected response host; stopped")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Authorized small-download size limit exceeded")
    return data, final_url


def run():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "data/raw/ps2/french" / stamp
    records = []
    for page, name in SOURCES:
        html, _ = fetch(page, 2000000)
        url = official_link(page, html.decode("utf-8-sig"), name)
        payload, resolved = fetch(url, 5000000)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None or any(f.file_size > 20000000 for f in archive.infolist()):
                raise ValueError("Archive CRC or uncompressed-size validation failed")
            members = archive.namelist()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        with path.open("xb") as stream:
            stream.write(payload)
        record = {"file": str(path.relative_to(ROOT)), "official_link_page": page,
                  "source_url": url, "resolved_url": resolved, "retrieved_utc": utc(),
                  "bytes": len(payload), "sha256": sha256(path), "archive_members": members}
        dump_new(path.with_suffix(".json"), record)
        records.append(record)
        print(name, len(payload), "bytes; SHA-256", record["sha256"])
    dump_new(folder / "manifest.json", {"created_utc": utc(), "files": records})
    print("Original archives preserved:", folder.relative_to(ROOT))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("PREVIEW ONLY: retrieve only the two official linked archives:")
        for page, name in SOURCES:
            print(page, name)
        return 0
    try:
        return run()
    except Exception as exc:
        print("STOPPED:", type(exc).__name__, "No automatic retry; existing files preserved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
