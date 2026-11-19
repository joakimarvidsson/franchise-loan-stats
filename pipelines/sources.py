"""Source discovery and download.

Two public sources, both U.S. Government works:
  1. SBA 7(a) FOIA loan files (data.sba.gov), published quarterly.
  2. SBA Franchise Directory spreadsheet (sba.gov), revised frequently.

Discovery is cheap (two small page fetches plus HEAD requests) and produces a
fingerprint. The expensive download and rebuild only run when it changes.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin

from . import common as c

LOAN_RE = re.compile(r"https?://[^\"'\s<>]+/FOIA_7a_[A-Za-z0-9_]+_asof_(\d{6})\.csv")
XLSX_RE = re.compile(r"href=\"([^\"]+\.xlsx[^\"]*)\"", re.I)


def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def discover_loan_files() -> list[dict]:
    """Return the current 7(a) file URLs. HTML page first, catalogue API as fallback."""
    urls: set[str] = set()
    errors: list[str] = []
    try:
        html = c.http_get(c.LOAN_DATASET_PAGE).text
        urls.update(m.group(0) for m in LOAN_RE.finditer(html))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"page: {exc}")
    if not urls:
        try:
            meta = c.http_get(c.LOAN_DATASET_API).json()
            for s in _walk_strings(meta):
                m = LOAN_RE.search(s)
                if m:
                    urls.add(m.group(0))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"api: {exc}")
    if not urls:
        raise RuntimeError("No 7(a) FOIA files discovered. " + "; ".join(errors))
    files = []
    for u in sorted(urls):
        asof = LOAN_RE.search(u).group(1)
        head = c.http_head(u)
        files.append(
            {
                "name": u.rsplit("/", 1)[1],
                "url": u,
                "asof": f"20{asof[0:2]}-{asof[2:4]}-{asof[4:6]}",
                "bytes": int(head.get("content-length", 0)),
                "etag": head.get("etag", "").strip('"'),
                "last_modified": head.get("last-modified", ""),
            }
        )
    asofs = {f["asof"] for f in files}
    if len(asofs) != 1:
        # Mixed quarters mid-publication: keep only the newest complete-looking set.
        newest = max(asofs)
        files = [f for f in files if f["asof"] == newest]
    if len(files) < 4:
        raise RuntimeError(f"Expected 4 decade files for 7(a), found {len(files)}: {[f['name'] for f in files]}")
    return files


def discover_directory() -> dict:
    r = c.http_get(c.DIRECTORY_PAGE)
    links = XLSX_RE.findall(r.text)
    links = [l for l in links if "franchise" in unquote(l).lower()]
    if not links:
        raise RuntimeError("Franchise Directory spreadsheet link not found")
    url = urljoin(r.url, links[0].replace("&amp;", "&"))
    head = c.http_head(url)
    return {
        "name": unquote(url.rsplit("/", 1)[1]),
        "url": url,
        "bytes": int(head.get("content-length", 0)),
        "etag": head.get("etag", "").strip('"'),
        "last_modified": head.get("last-modified", ""),
    }


def fingerprint(loan_files: list[dict], directory: dict | None) -> dict:
    return {
        "loans": sorted([f["name"], f["bytes"], f["etag"]] for f in loan_files),
        "directory": [directory["name"], directory["bytes"], directory["etag"]] if directory else None,
    }


def download(item: dict, dest_dir: Path, *, min_bytes: int) -> Path:
    """Download one file into the cache. Skips when a complete copy is already there."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / item["name"].replace(" ", "_")
    if dest.exists() and item["bytes"] and dest.stat().st_size == item["bytes"]:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with c.http_get(item["url"], stream=True, timeout=600) as r, tmp.open("wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    size = tmp.stat().st_size
    if size < min_bytes or (item["bytes"] and size != item["bytes"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download size check failed for {item['name']}: got {size}, expected {item['bytes']}")
    tmp.replace(dest)
    return dest


def asof_date(loan_files: list[dict]) -> date:
    return date.fromisoformat(loan_files[0]["asof"])
