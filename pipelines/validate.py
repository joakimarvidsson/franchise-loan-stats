"""Validation gates. A build that fails any gate is never published."""
from __future__ import annotations

from collections import Counter


class ValidationError(Exception):
    pass


def _check(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _rate_ok(r: dict | None) -> bool:
    return r is None or (0 <= r["lo"] <= r["pct"] <= r["hi"] <= 100)


def validate(out: dict, previous_summary: dict | None = None) -> list[str]:
    """Return a list of human-readable check results. Raises ValidationError on failure."""
    errors: list[str] = []
    s = out["summary"]
    cnt = s["counts"]

    # Volume floors: the 7(a) file has held well over a million rows for years.
    _check(cnt["loans_total"] >= 1_500_000, f"too few loan rows: {cnt['loans_total']}", errors)
    _check(cnt["loans_franchise"] >= 100_000, f"too few franchise rows: {cnt['loans_franchise']}", errors)
    _check(cnt["unparsed_rows"] <= 0.005 * cnt["loans_total"], f"unparsed rows: {cnt['unparsed_rows']}", errors)
    _check(cnt["brand_pages"] >= 800, f"too few brand pages: {cnt['brand_pages']}", errors)
    _check(cnt["brands_rated"] >= 200, f"too few rated brands: {cnt['brands_rated']}", errors)
    _check(cnt["industry_pages"] >= 100, f"too few industries: {cnt['industry_pages']}", errors)
    _check(cnt["lender_pages"] >= 50, f"too few lenders: {cnt['lender_pages']}", errors)
    _check(cnt["state_pages"] >= 45, f"too few states: {cnt['state_pages']}", errors)

    for kind in ("brands", "industries", "lenders", "states"):
        dup = [k for k, n in Counter(x["slug"] for x in out[kind]).items() if n > 1]
        _check(not dup, f"duplicate {kind} slugs: {dup[:5]}", errors)
        _check(all(x["slug"] and x["name"] for x in out[kind]), f"{kind} with empty slug or name", errors)

    dup_names = [k for k, n in Counter(x["name"].strip().lower() for x in out["brands"]).items() if n > 1]
    _check(not dup_names, f"two brand pages share a name (add an alias): {dup_names[:8]}", errors)

    for b in out["brands"] + out["industries"]:
        a, se = b["all"], b["seasoned"]
        _check(a["disbursed"] == a["paid_in_full"] + a["charged_off"] + a["active"],
               f"{b['slug']}: disbursed does not equal PIF + charged off + active", errors)
        _check(a["approved"] >= a["disbursed"] + a["cancelled"] + a["undisbursed"],
               f"{b['slug']}: approved is smaller than its parts", errors)
        _check(se["charged_off"] <= se["disbursed"] <= a["disbursed"], f"{b['slug']}: seasoned counts inconsistent", errors)
        _check(_rate_ok(se["rate"]) and _rate_ok(a["rate"]), f"{b['slug']}: rate out of bounds", errors)
        if se["rate"] is not None:
            _check(abs(se["rate"]["pct"] - 100 * se["charged_off"] / se["disbursed"]) < 0.06,
                   f"{b['slug']}: rate does not match counts", errors)
        _check((se["rate"] is None) == (se["disbursed"] < s["thresholds"]["limited_min"]),
               f"{b['slug']}: rate shown below the minimum sample", errors)
        if len(errors) > 25:
            break

    fr = s["franchise"]["seasoned"]["rate"]
    _check(fr is not None and 1 <= fr["pct"] <= 30, f"implausible overall franchise rate: {fr}", errors)

    if previous_summary:
        p = previous_summary
        pc = p["counts"]
        _check(s["asof"] >= p["asof"], f"data date went backwards: {s['asof']} < {p['asof']}", errors)
        _check(cnt["loans_total"] >= 0.98 * pc["loans_total"],
               f"loan rows fell more than 2%: {pc['loans_total']} -> {cnt['loans_total']}", errors)
        _check(abs(cnt["brand_pages"] - pc["brand_pages"]) <= 0.15 * pc["brand_pages"],
               f"brand pages moved more than 15%: {pc['brand_pages']} -> {cnt['brand_pages']}", errors)
        pr = p["franchise"]["seasoned"]["rate"]
        if pr and fr:
            _check(abs(fr["pct"] - pr["pct"]) <= 3.0,
                   f"overall franchise rate moved more than 3 points: {pr['pct']} -> {fr['pct']}", errors)

    if errors:
        raise ValidationError("; ".join(errors[:30]))
    return [
        f"{cnt['loans_total']:,} loan rows, {cnt['loans_franchise']:,} franchise-coded",
        f"{cnt['brand_pages']:,} brand pages, {cnt['brands_rated']:,} rated",
        f"{cnt['industry_pages']:,} industries, {cnt['lender_pages']:,} lenders, {cnt['state_pages']} states",
        f"overall franchise seasoned charge-off rate {fr['pct']}%",
    ]
