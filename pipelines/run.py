"""Pipeline entry point.

    python -m pipelines.run --check     discover sources, report whether anything changed
    python -m pipelines.run             refresh if sources changed (idempotent)
    python -m pipelines.run --force     rebuild even if unchanged
    python -m pipelines.run --offline   rebuild from files already in the cache (development)
    python -m pipelines.run --allow-shift   publish a deliberate methodology change (skips drift gates)

Exit codes: 0 = published or nothing to do, 1 = failed (previous snapshot left in place).
Published and failed runs append one line to state/pipeline_runs.jsonl.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import traceback
from datetime import date
from pathlib import Path

from . import aggregate, sources, validate
from . import common as c

RUN_LOG = c.STATE / "pipeline_runs.jsonl"


def _gh_output(**kv) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for k, v in kv.items():
                fh.write(f"{k}={v}\n")


def _history_snapshot(out: dict) -> dict:
    return {
        "asof": out["summary"]["asof"],
        "brands": {
            b["slug"]: [b["all"]["disbursed"], b["all"]["charged_off"], b["seasoned"]["disbursed"],
                        b["seasoned"]["charged_off"], b["seasoned"]["tier"]]
            for b in out["brands"]
        },
    }


def _changes(prev: dict | None, cur: dict, names: dict[str, str]) -> dict:
    """Brand-level differences between two snapshots. Empty for the first snapshot."""
    if not prev or prev["asof"] == cur["asof"]:
        return {"from": prev["asof"] if prev else None, "to": cur["asof"], "new_brands": [], "new_chargeoffs": [],
                "newly_rated": []}
    p, q = prev["brands"], cur["brands"]
    new_brands = sorted(s for s in q if s not in p)
    new_co = sorted(
        ({"slug": s, "name": names.get(s, s), "added": q[s][1] - p[s][1], "total": q[s][1]}
         for s in q if s in p and q[s][1] > p[s][1]),
        key=lambda x: -x["added"],
    )
    newly_rated = sorted(s for s in q if q[s][4] == "rated" and (s not in p or p[s][4] != "rated"))
    return {
        "from": prev["asof"], "to": cur["asof"],
        "new_brands": [{"slug": s, "name": names.get(s, s)} for s in new_brands],
        "new_chargeoffs": new_co[:200],
        "newly_rated": [{"slug": s, "name": names.get(s, s)} for s in newly_rated],
    }


def _brands_csv(out: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    s = out["summary"]["windows"]["seasoned"]
    w.writerow([
        "brand", "slug", "sba_directory_code", "on_sba_directory", "all_time_disbursed_loans",
        "all_time_charged_off_loans", f"seasoned_fy{s[0]}_{s[1]}_disbursed_loans",
        f"seasoned_fy{s[0]}_{s[1]}_charged_off_loans", "seasoned_charge_off_rate_pct", "rate_ci95_low_pct",
        "rate_ci95_high_pct", "seasoned_charge_off_rate_by_dollars_pct", "sample_tier",
        "recent_5fy_approved_loans", "recent_median_loan_usd", "recent_median_initial_rate_pct",
        "primary_industry", "data_as_of",
    ])
    for b in out["brands"]:
        se, r = b["seasoned"], b["seasoned"]["rate"]
        w.writerow([
            b["name"], b["slug"], b["directory"]["code"] or "", "yes" if b["directory"]["listed"] else "no",
            b["all"]["disbursed"], b["all"]["charged_off"], se["disbursed"], se["charged_off"],
            r["pct"] if r else "", r["lo"] if r else "", r["hi"] if r else "",
            se["rate_dollar_pct"] if se["rate_dollar_pct"] is not None else "", se["tier"],
            b["recent"]["approved"], b["recent"]["median_loan"] or "", b["recent"]["median_rate"] or "",
            b["industry"]["name"] if b["industry"] else "", out["summary"]["asof"],
        ])
    return buf.getvalue()


def publish(out: dict, manifest: dict) -> dict:
    """Write staging, then promote. Called only after validation has passed."""
    st = c.STAGING
    st.mkdir(parents=True, exist_ok=True)
    for name in ("brands", "industries", "lenders", "states"):
        c.write_json(st / f"{name}.json", out[name], compact=True)
    c.write_json(st / "summary.json", out["summary"])
    c.write_json(st / "manifest.json", manifest)
    (st / "brands.csv").write_text(_brands_csv(out), encoding="utf-8")

    asof = out["summary"]["asof"]
    snap = _history_snapshot(out)
    prev_files = sorted(p for p in c.HISTORY.glob("*.json") if p.stem < asof) if c.HISTORY.exists() else []
    prev = c.read_json(prev_files[-1]) if prev_files else None
    names = {b["slug"]: b["name"] for b in out["brands"]}
    changes = _changes(prev, snap, names)

    c.PUBLISHED.mkdir(parents=True, exist_ok=True)
    for f in st.iterdir():
        f.replace(c.PUBLISHED / f.name)
    c.write_json(c.HISTORY / f"{asof}.json", snap, compact=True)
    c.write_json(c.CHANGES / f"{asof}.json", changes)
    c.write_json(c.CHANGES / "latest.json", changes)
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--allow-shift", action="store_true",
                    help="skip comparison with the previous snapshot; only for deliberate methodology changes")
    args = ap.parse_args(argv)

    started = time.time()
    rec: dict = {"at": c.utcnow(), "mode": "check" if args.check else ("offline" if args.offline else "refresh")}
    prev_manifest = c.read_json(c.PUBLISHED / "manifest.json")
    prev_summary = c.read_json(c.PUBLISHED / "summary.json")
    try:
        if args.offline:
            csvs = sorted(c.CACHE.glob("FOIA_7a_*.csv"))
            xlsx = sorted(c.CACHE.glob("*.xlsx"))
            if len(csvs) < 4 or not xlsx:
                raise RuntimeError(f"--offline needs 4 loan CSVs and the directory xlsx in {c.CACHE}")
            asof_s = csvs[0].stem.rsplit("_", 1)[1]
            asof = date(2000 + int(asof_s[0:2]), int(asof_s[2:4]), int(asof_s[4:6]))
            loan_files = [{"name": p.name, "url": None, "asof": asof.isoformat(), "bytes": p.stat().st_size,
                           "etag": "", "last_modified": ""} for p in csvs]
            directory = {"name": xlsx[-1].name, "url": None, "bytes": xlsx[-1].stat().st_size, "etag": "",
                         "last_modified": ""}
            if prev_manifest:  # keep the real source URLs and validators when rebuilding offline
                by_name = {f["name"]: f for f in prev_manifest["sources"]["loans"]}
                loan_files = [by_name.get(f["name"], f) for f in loan_files]
                if prev_manifest["sources"]["directory"]["bytes"] == directory["bytes"]:
                    directory = prev_manifest["sources"]["directory"]
            csv_paths, xlsx_path = csvs, xlsx[-1]
        else:
            loan_files = sources.discover_loan_files()
            try:
                directory = sources.discover_directory()
            except Exception as exc:  # noqa: BLE001 - the directory is secondary; fall back to the last copy
                rec["directory_warning"] = str(exc)[:300]
                directory = prev_manifest["sources"]["directory"] if prev_manifest else None
                if directory is None:
                    raise
            asof = sources.asof_date(loan_files)

        fp = sources.fingerprint(loan_files, directory)
        changed = not prev_manifest or prev_manifest.get("fingerprint") != fp
        rec.update({"asof": asof.isoformat(), "changed": changed})
        print(f"data as of {asof}; sources {'CHANGED' if changed else 'unchanged'}")
        _gh_output(changed=str(changed).lower(), asof=asof.isoformat())
        if args.check or (not changed and not args.force and not args.offline):
            rec["result"] = "checked" if args.check else "unchanged"
            return 0

        if not args.offline:
            csv_paths = [sources.download(f, c.CACHE, min_bytes=50_000_000) for f in loan_files]
            xlsx_path = sources.download(directory, c.CACHE, min_bytes=50_000)

        out = aggregate.build(csv_paths, xlsx_path, asof)
        checks = validate.validate(out, None if args.allow_shift else prev_summary)
        rec["allow_shift"] = bool(args.allow_shift)
        for line in checks:
            print("ok:", line)
        manifest = {
            "built_at": c.utcnow(),
            "asof": asof.isoformat(),
            "fingerprint": fp,
            "licence": {"name": "U.S. Government Works (public domain)", "url": c.LICENCE_URL},
            "sources": {
                "loans_landing": c.LOAN_DATASET_PAGE, "directory_landing": c.DIRECTORY_PAGE,
                "loans": loan_files, "directory": directory,
            },
            "counts": out["summary"]["counts"],
        }
        changes = publish(out, manifest)
        rec.update({"result": "published", "counts": out["summary"]["counts"],
                    "new_brands": len(changes["new_brands"]), "new_chargeoffs": len(changes["new_chargeoffs"])})
        _gh_output(published="true")
        return 0
    except Exception as exc:  # noqa: BLE001
        rec.update({"result": "failed", "error": f"{type(exc).__name__}: {exc}"[:800]})
        traceback.print_exc()
        print("FAILED - previously published snapshot left untouched", file=sys.stderr)
        return 1
    finally:
        rec["seconds"] = round(time.time() - started, 1)
        # Routine "nothing changed" checks are visible in the workflow history; only log real events.
        if rec.get("result") in ("published", "failed"):
            c.append_jsonl(RUN_LOG, rec)


if __name__ == "__main__":
    sys.exit(main())
