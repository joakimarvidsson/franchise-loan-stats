"""Pipeline tests. Run with: python -m pytest tests -q"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from pipelines import aggregate, brands, common, validate

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- small pure functions
def test_fiscal_year_boundaries():
    assert common.fiscal_year(date(2026, 9, 30)) == 2026
    assert common.fiscal_year(date(2026, 10, 1)) == 2027
    assert common.fiscal_year(date(2026, 12, 31)) == 2027


def test_wilson_interval_known_values():
    lo, hi = common.wilson(0, 40)
    assert lo == 0 and hi == pytest.approx(0.0876, abs=0.001)
    lo, hi = common.wilson(63, 230)
    assert lo == pytest.approx(0.220, abs=0.002) and hi == pytest.approx(0.335, abs=0.002)
    assert common.wilson(0, 0) == (0.0, 0.0)
    lo, hi = common.wilson(5, 5)
    assert hi == 1.0 and lo < 1.0


def test_slugify():
    assert common.slugify("Dickey's Barbecue Pit") == "dickeys-barbecue-pit"
    assert common.slugify("A&W") == "a-and-w"
    assert common.slugify("  ") == "unnamed"


def test_norm_key_strips_noise_but_keeps_identity():
    assert brands.norm_key("COLD STONE CREAMERY, INC.") == "COLD STONE CREAMERY"
    assert brands.norm_key("The UPS Store") == "UPS STORE"
    assert brands.norm_key("Jersey Mike’s") == brands.norm_key("JERSEY MIKE'S")
    assert brands.norm_key("SMOOTHIE KING (HEALTH FOOD STORE)") == "SMOOTHIE KING"
    assert brands.norm_key("Holiday Inn Express") != brands.norm_key("Holiday Inn")


def test_descriptor_rule_is_conservative():
    assert brands.descriptor_related("ORANGE LEAF", "ORANGE LEAF FROZEN YOGURT")
    assert brands.descriptor_related("WINGSTOP RESTAURANT", "WINGSTOP")
    assert not brands.descriptor_related("HOLIDAY INN", "HOLIDAY INN EXPRESS")   # EXPRESS marks a distinct system
    assert not brands.descriptor_related("COMPUTER RENAISSANCE", "RENAISSANCE")  # not a tail
    assert not brands.descriptor_related("PIZZA", "PIZZA INN")                   # base is only generic words
    assert not brands.descriptor_related("ACE", "ACE HARDWARE")                  # base too short, tail not generic
    assert not brands.descriptor_related("SUBWAY", "SUBWAY")


def test_former_names_in_the_directory_are_used_for_matching():
    assert brands.split_former("Experimax f/k/a Experimac") == ("Experimax", "Experimac")
    assert brands.split_former("Subway") == ("Subway", None)
    assert brands.directory_segments("Experimax f/k/a Experimac") == ["Experimax", "Experimac"]
    assert brands.display_name("Experimax f/k/a Experimac", {}) == "Experimax (formerly Experimac)"
    for directory in ({"S0590": {"brand": "Experimax f/k/a Experimac"}}, {}):  # listed, or dropped from the directory
        ents, mapping = brands.resolve([("S0590", "Experimax f/k/a Experimac", 15), ("15975", "Experimac", 66)],
                                       directory, {"names": {}, "codes": {}})
        assert mapping[("15975", "Experimac")] == "S0590" and ents["S0590"].loans == 81
        assert ents["S0590"].name == "Experimax (formerly Experimac)"


def test_cobrand_loan_names_do_not_capture_the_parent_brand():
    ents, mapping = brands.resolve(
        [("S1110", "Midas", 90), ("S1111", "Midas/SpeeDee Oil Change & Auto Service", 17), ("12356", "MIDAS", 40)],
        {"S1110": {"brand": "Midas"}}, {"names": {}, "codes": {}})
    assert mapping[("12356", "MIDAS")] == "S1110"
    assert ents["S1111"].name == "Midas/SpeeDee Oil Change & Auto Service"
    assert ents["S1110"].slug != ents["S1111"].slug


# ---------------------------------------------------------------- entity resolution
DIRECTORY = {
    "S1639": {"brand": "Subway"},
    "S0806": {"brand": "Holiday Inn/Holiday Inn & Suites/Holiday Inn Resort"},
    "S2794": {"brand": "Holiday Inn Express/Holiday Inn Express & Suites"},
    "S9999": {"brand": "Orange Leaf Frozen Yogurt"},
}


def _resolve(pairs, aliases=None):
    ents, mapping = brands.resolve(pairs, DIRECTORY, aliases or {"names": {}, "codes": {}})
    return ents, mapping


def test_legacy_code_merges_on_exact_normalised_name():
    ents, mapping = _resolve([("S1639", "Subway", 10), ("13680", "SUBWAY", 5)])
    assert mapping[("13680", "SUBWAY")] == "S1639"
    assert ents["S1639"].loans == 15 and ents["S1639"].merged == {"13680": "name-exact"}


def test_alias_merges_and_unknown_stays_separate():
    aliases = {"names": {"SUBWAY SANDWICH SHOP": {"target": "Subway", "display": "", "note": ""}}, "codes": {}}
    ents, mapping = _resolve(
        [("S1639", "Subway", 10), ("78760", "SUBWAY SANDWICH SHOP", 7), ("50564", "MAIL BOXES ETC. USA", 3)], aliases
    )
    assert mapping[("78760", "SUBWAY SANDWICH SHOP")] == "S1639"
    assert mapping[("50564", "MAIL BOXES ETC. USA")] == "L:MAIL BOXES ETC"
    assert ents["L:MAIL BOXES ETC"].match == "legacy"
    assert ents["L:MAIL BOXES ETC"].name == "Mail Boxes Etc. USA"


def test_distinct_systems_are_never_merged():
    ents, mapping = _resolve(
        [("S0806", "Holiday Inn", 4), ("S2794", "Holiday Inn Express", 6), ("11111", "HOLIDAY INN EXPRESS", 2),
         ("22222", "HOLIDAY INN", 1)]
    )
    assert mapping[("11111", "HOLIDAY INN EXPRESS")] == "S2794"
    assert mapping[("22222", "HOLIDAY INN")] == "S0806"
    assert ents["S0806"].loans == 5 and ents["S2794"].loans == 8


def test_descriptor_merge_and_empty_alias_blocks_it():
    ents, mapping = _resolve([("S9999", "Orange Leaf Frozen Yogurt", 9), ("33333", "ORANGE LEAF", 4)])
    assert mapping[("33333", "ORANGE LEAF")] == "S9999"
    blocked = {"names": {"ORANGE LEAF": {"target": "", "display": "", "note": "kept separate"}}, "codes": {}}
    ents, mapping = _resolve([("S9999", "Orange Leaf Frozen Yogurt", 9), ("33333", "ORANGE LEAF", 4)], blocked)
    assert mapping[("33333", "ORANGE LEAF")] == "L:ORANGE LEAF"


def test_placeholder_names_are_excluded():
    _, mapping = _resolve([("00001", "TEMPORARY", 50)])
    assert mapping == {}


def test_slugs_are_unique():
    ents, _ = _resolve([("S1639", "Subway", 10), ("44444", "SUB-WAY!", 2), ("55555", "SUB WAY", 2)])
    slugs = [e.slug for e in ents.values() if e.loans]
    assert len(slugs) == len(set(slugs))


def test_alias_file_is_well_formed():
    a = brands.load_aliases()
    assert len(a["names"]) > 50 and len(a["codes"]) > 5
    with brands.ALIASES_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    assert all(set(r) == {"source_name", "target", "display", "note"} for r in rows)
    assert all(r["source_name"].strip() for r in rows)


# ---------------------------------------------------------------- end-to-end on a synthetic file
HEADER = ["AsOfDate", "Program", "BorrName", "BankName", "GrossApproval", "ApprovalFY", "InitialInterestRate",
          "TermInMonths", "NaicsCode", "NaicsDescription", "FranchiseCode", "FranchiseName", "ProjectState",
          "BusinessAge", "LoanStatus", "ChargeOffDate", "GrossChargeOffAmount"]


def _loan(fy, status, code="", name="", amt=100000, co=0, bank="First Test Bank", naics="722513",
          desc="Limited-Service Restaurants", state="TX"):
    return ["2026-09-30", "7A", "Private Borrower LLC", bank, amt, fy, 10.5, 120, naics, desc, code, name, state,
            "Existing or more than 2 years old", status, "2020-05-01" if status == "CHGOFF" else "", co]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import openpyxl

    d = tmp_path_factory.mktemp("src")
    rows = []
    rows += [_loan(2015, "P I F", "S1639", "Subway") for _ in range(36)]      # seasoned, paid
    rows += [_loan(2016, "CHGOFF", "S1639", "Subway", co=40000) for _ in range(4)]  # seasoned, charged off
    rows += [_loan(2016, "CANCLD", "S1639", "Subway") for _ in range(5)]      # must not count
    rows += [_loan(2024, "EXEMPT", "S1639", "Subway", amt=250000) for _ in range(6)]  # recent
    rows += [_loan(2009, "CHGOFF", "78760", "SUBWAY SANDWICH SHOP", co=10000) for _ in range(3)]  # legacy, pre-window
    rows += [_loan(2014, "P I F", "", "", naics="621210", desc="Offices of Dentists") for _ in range(20)]
    rows += [_loan(2014, "P I F", "99999", "TEMPORARY") for _ in range(4)]
    p = d / "FOIA_7a_test_asof_260930.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(HEADER)
        w.writerows(rows)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SBA FRANCHISE IDENTIFIER CODE", "BRAND", "MEETS FTC DEFINITION OF A FRANCHISE?",
               "Franchisor/ Distributor Certification Received?", "SBA FRANCHISE IDENTIFIER CODE Start Date",
               "Recertified Date", "NOTES", "Reference Number"])
    ws.append(["S1639", "Subway", "Y", "Y", "10/01/2017", None, None, 1])
    for i in range(1200):  # the loader refuses implausibly small directories
        ws.append([f"S{2000 + i}", f"Filler Brand {i}", "Y", "Y", "01/02/2020", None, None, 10 + i])
    x = d / "Franchise Directory test.xlsx"
    wb.save(x)
    old_all, old_ind = aggregate.BRAND_PAGE_MIN_ALL, aggregate.INDUSTRY_PAGE_MIN
    aggregate.INDUSTRY_PAGE_MIN = 10
    try:
        out = aggregate.build([p], x, date(2026, 9, 30))
    finally:
        aggregate.BRAND_PAGE_MIN_ALL, aggregate.INDUSTRY_PAGE_MIN = old_all, old_ind
    return out


def test_build_counts_match_hand_calculation(built):
    b = {x["slug"]: x for x in built["brands"]}["subway"]
    assert b["all"]["approved"] == 54 and b["all"]["cancelled"] == 5
    assert b["all"]["disbursed"] == 49                       # 36 PIF + 4 + 3 charged off + 6 active
    assert b["all"]["charged_off"] == 7 and b["all"]["active"] == 6
    s = b["seasoned"]
    assert (s["from_fy"], s["to_fy"]) == (2012, 2021)
    assert s["disbursed"] == 40 and s["charged_off"] == 4     # legacy FY2009 loans fall outside the window
    assert s["rate"]["pct"] == 10.0 and s["tier"] == "rated"
    assert s["rate_dollar_pct"] == 4.0                        # 160,000 of 4,000,000
    assert b["recent"]["approved"] == 6 and b["recent"]["median_loan"] == 250000
    assert b["directory"]["listed"] and b["directory"]["listed_since"] == "2017-10-01"
    assert b["merged_legacy_codes"] == 1
    assert b["rank"] == {"position": 1, "of": 1}


def test_build_excludes_placeholders_and_borrower_names(built):
    assert all("temporary" not in x["slug"] for x in built["brands"])
    assert "Private Borrower" not in json.dumps(built)


def test_industry_and_summary(built):
    inds = {i["name"]: i for i in built["industries"]}
    assert inds["Offices of Dentists"]["seasoned"]["rate"]["pct"] == 0.0
    assert inds["Limited-Service Restaurants"]["seasoned"]["disbursed"] == 44  # 40 Subway + 4 placeholder-named loans
    s = built["summary"]
    assert s["counts"]["loans_total"] == 78 and s["counts"]["unparsed_rows"] == 0
    assert s["non_franchise"]["seasoned"]["disbursed"] == 20


# ---------------------------------------------------------------- validation gates
def _published():
    p = ROOT / "data" / "published"
    if not (p / "summary.json").exists():
        pytest.skip("no published snapshot in this checkout")
    return {k: json.loads((p / f"{k}.json").read_text()) for k in ("brands", "industries", "lenders", "states", "summary")}


def test_published_snapshot_passes_validation():
    out = _published()
    assert validate.validate(out, out["summary"])


def test_validation_blocks_a_shrunken_or_shifted_build():
    out = _published()
    prev = json.loads(json.dumps(out["summary"]))
    prev["counts"]["loans_total"] = int(out["summary"]["counts"]["loans_total"] * 1.2)
    with pytest.raises(validate.ValidationError, match="loan rows fell"):
        validate.validate(out, prev)
    prev = json.loads(json.dumps(out["summary"]))
    prev["asof"] = "2099-01-01"
    with pytest.raises(validate.ValidationError, match="went backwards"):
        validate.validate(out, prev)


def test_validation_blocks_inconsistent_counts():
    out = _published()
    broken = json.loads(json.dumps(out))
    broken["brands"][0]["all"]["disbursed"] += 1
    with pytest.raises(validate.ValidationError, match="disbursed does not equal"):
        validate.validate(broken, None)


def test_no_rate_is_published_below_the_minimum_sample():
    out = _published()
    lim = out["summary"]["thresholds"]["limited_min"]
    for b in out["brands"]:
        if b["seasoned"]["disbursed"] < lim:
            assert b["seasoned"]["rate"] is None and "rank" not in b
        if b["seasoned"]["tier"] != "rated":
            assert "rank" not in b
