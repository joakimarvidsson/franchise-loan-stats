"""Shared paths, HTTP helpers and small utilities for the Franchise Loan Stats pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PUBLISHED = DATA / "published"
STAGING = DATA / "staging"
HISTORY = DATA / "history"
CHANGES = DATA / "changes"
STATE = ROOT / "state"
CACHE = Path(os.environ.get("FLS_CACHE", ROOT / ".cache"))

USER_AGENT = "franchise-loan-stats/1.0 (+https://github.com/joakimarvidsson/franchise-loan-stats)"

LOAN_DATASET_PAGE = "https://data.sba.gov/dataset/7a-504-foia"
LOAN_DATASET_API = (
    "https://data.sba.gov/api/1/metastore/schemas/dataset/items/SBA-OHA-2016-08-001?show-reference-ids=true"
)
DIRECTORY_PAGE = "https://www.sba.gov/document/support-sba-franchise-directory"
LICENCE_URL = "https://www.usa.gov/publicdomain/label/1.0/"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str, *, stream: bool = False, timeout: int = 60, retries: int = 2) -> requests.Response:
    """GET with a small bounded retry. Raises on final failure; never loops forever."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=stream, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries + 1} attempts: {url}: {last}")


def http_head(url: str, timeout: int = 30) -> dict[str, str]:
    r = requests.head(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return {k.lower(): v for k, v in r.headers.items()}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ").replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unnamed"


def fiscal_year(d: date) -> int:
    """US federal fiscal year: FY2026 runs 1 Oct 2025 to 30 Sep 2026."""
    return d.year + 1 if d.month >= 10 else d.year


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, as fractions."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
