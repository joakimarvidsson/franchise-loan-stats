"""Build the published aggregates from the raw SBA files.

Only aggregates leave this module. Individual loan records and borrower names are
never written to the repository or the site.

Definitions (also documented on the site's methodology page):
  disbursed       LoanStatus in PIF, CHGOFF, EXEMPT (excludes cancelled and undisbursed)
  charge-off rate charged-off loans / disbursed loans, by count
  seasoned cohort loans approved in the 10 fiscal years ending 5 years before the data date
  recent cohort   loans approved in the last 5 fiscal years (too young to judge outcomes)
"""
from __future__ import annotations

import warnings
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from . import brands as B
from . import common as c

RATED_MIN = 30          # seasoned disbursed loans needed before a rate is ranked
LIMITED_MIN = 10        # below this no rate is shown at all
BRAND_PAGE_MIN_ALL = 25  # all-time disbursed loans that justify a brand page on their own
INDUSTRY_PAGE_MIN = 200  # seasoned disbursed loans needed for an industry page
LENDER_PAGE_MIN = 50    # franchise loans in the last 10 fiscal years needed for a lender page

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def load_directory(xlsx: Path) -> dict[str, dict]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(xlsx, read_only=True)
    ws = wb.active
    out: dict[str, dict] = {}
    header = None
    for row in ws.iter_rows(values_only=True):
        if header is None:
            header = [str(x or "").strip().upper() for x in row]
            if "BRAND" not in header:
                raise RuntimeError(f"Unexpected Franchise Directory header: {header}")
            idx = {
                "code": next(i for i, h in enumerate(header) if "IDENTIFIER CODE" in h and "DATE" not in h),
                "brand": header.index("BRAND"),
                "ftc": next((i for i, h in enumerate(header) if "FTC" in h), None),
                "cert": next((i for i, h in enumerate(header) if "CERTIFICATION" in h), None),
                "start": next((i for i, h in enumerate(header) if "START DATE" in h), None),
                "notes": next((i for i, h in enumerate(header) if h == "NOTES"), None),
            }
            continue
        code = str(row[idx["code"]] or "").strip()
        brand = str(row[idx["brand"]] or "").strip()
        if not code or not brand:
            continue

        def cell(k):
            i = idx[k]
            v = row[i] if i is not None and i < len(row) else None
            return str(v).strip() if v not in (None, "") else None

        start = cell("start")
        iso = None
        if start:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    from datetime import datetime

                    iso = datetime.strptime(start, fmt).date().isoformat()
                    break
                except ValueError:
                    continue
        notes = cell("notes")
        out[code] = {
            "code": code,
            "brand": brand,
            "ftc": cell("ftc"),
            "certified": cell("cert"),
            "listed_since": iso,
            "notes": " ".join(notes.split())[:600] if notes else None,
        }
    if len(out) < 1000:
        raise RuntimeError(f"Franchise Directory parsed only {len(out)} coded brands; expected thousands")
    return out


def _rate(k: int, n: int) -> dict | None:
    if not n:
        return None
    lo, hi = c.wilson(k, n)
    return {"pct": round(100 * k / n, 1), "lo": round(100 * lo, 1), "hi": round(100 * hi, 1)}


def _tier(n: int) -> str:
    return "rated" if n >= RATED_MIN else ("limited" if n >= LIMITED_MIN else "insufficient")


def _r(x, nd=0):
    if x is None:
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def build(csv_paths: list[Path], directory_xlsx: Path, asof: date, db_path: str = ":memory:") -> dict:
    """Return a dict of published datasets: brands, industries, lenders, states, summary."""
    fy = c.fiscal_year(asof)
    s_lo, s_hi = fy - 14, fy - 5      # seasoned: 10 fiscal years
    r_lo, r_hi = fy - 4, fy           # recent: last 5 fiscal years
    w_lo = fy - 9                     # "last 10 fiscal years" for lender and state activity

    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=2")
    files = ", ".join("'" + str(p).replace("'", "''") + "'" for p in csv_paths)
    con.execute(
        f"""create or replace table raw as
            select * from read_csv([{files}], all_varchar=true, union_by_name=true,
                                   quote='"', escape='"', ignore_errors=true)"""
    )
    raw_rows = con.execute("select count(*) from raw").fetchone()[0]
    cols = {r[0] for r in con.execute("describe raw").fetchall()}
    needed = {"ApprovalFY", "GrossApproval", "LoanStatus", "FranchiseCode", "FranchiseName", "BankName",
              "NaicsCode", "ProjectState", "GrossChargeOffAmount", "InitialInterestRate", "TermInMonths",
              "BusinessAge", "ChargeOffDate"}
    missing = needed - cols
    if missing:
        raise RuntimeError(f"Source schema changed, missing columns: {sorted(missing)}")

    con.execute(
        """create or replace table loans as
           select
             try_cast(ApprovalFY as integer) as fy,
             try_cast(GrossApproval as double) as amt,
             coalesce(try_cast(GrossChargeOffAmount as double), 0) as co_amt,
             case replace(upper(trim(LoanStatus)), ' ', '')
               when 'PIF' then 'PIF' when 'CHGOFF' then 'CHGOFF' when 'EXEMPT' then 'EXEMPT'
               when 'CANCLD' then 'CANCLD' when 'COMMIT' then 'COMMIT' else 'OTHER' end as status,
             try_cast(InitialInterestRate as double) as rate,
             try_cast(TermInMonths as double) as term,
             nullif(trim(NaicsCode), '') as naics,
             nullif(trim(NaicsDescription), '') as naics_desc,
             nullif(upper(trim(ProjectState)), '') as state,
             nullif(regexp_replace(trim(BankName), '\\s+', ' ', 'g'), '') as lender_raw,
             nullif(trim(FranchiseCode), '') as fcode,
             nullif(trim(FranchiseName), '') as fname,
             coalesce(trim(BusinessAge), '') as biz_age,
             try_cast(ChargeOffDate as date) as co_date
           from raw"""
    )
    con.execute("drop table raw")
    con.execute("alter table loans add column disb boolean")
    con.execute("update loans set disb = status in ('PIF','CHGOFF','EXEMPT')")
    con.execute("alter table loans add column lender varchar")
    con.execute("update loans set lender = upper(lender_raw)")
    other = con.execute("select count(*) from loans where status='OTHER' or fy is null or amt is null").fetchone()[0]

    # Industries are keyed by NAICS title, so code revisions that kept the title (for example
    # 722211 and 722513, both "Limited-Service Restaurants") land in one industry.
    con.execute(
        """create or replace table nmap as
           select naics, arg_max(d, n) as ind from
             (select naics, regexp_replace(naics_desc, '\\s+', ' ', 'g') as d, count(*) n from loans
               where naics is not null and naics_desc is not null group by 1,2) group by 1"""
    )
    con.execute("alter table loans add column ind varchar")
    con.execute("update loans set ind = nmap.ind from nmap where loans.naics = nmap.naics")
    ind_codes: dict[str, list[str]] = defaultdict(list)
    for ind_name, code in con.execute(
        "select ind, naics from loans where ind is not null group by 1,2 order by 1, count(*) desc"
    ).fetchall():
        ind_codes[ind_name].append(code)

    # ---- brand resolution -------------------------------------------------------------
    directory = load_directory(directory_xlsx)
    pairs = con.execute(
        "select coalesce(fcode,''), fname, count(*) from loans where fname is not null group by 1,2"
    ).fetchall()
    ents, mapping = B.resolve(pairs, directory)
    con.execute("create or replace table bmap(fcode varchar, fname varchar, brand varchar)")
    con.executemany("insert into bmap values (?,?,?)", [(k[0], k[1], v) for k, v in mapping.items()])
    con.execute(
        """create or replace table fl as
           select l.*, m.brand from loans l join bmap m
             on coalesce(l.fcode,'') = m.fcode and l.fname = m.fname"""
    )
    franchise_rows = con.execute("select count(*) from fl").fetchone()[0]

    METRICS = f"""
        count(*) as approved,
        count(*) filter (where disb) as disbursed,
        count(*) filter (where status='PIF') as pif,
        count(*) filter (where status='CHGOFF') as chgoff,
        count(*) filter (where status='EXEMPT') as active,
        count(*) filter (where status='CANCLD') as cancelled,
        count(*) filter (where status='COMMIT') as undisbursed,
        coalesce(sum(amt) filter (where disb), 0) as gross,
        coalesce(sum(co_amt) filter (where status='CHGOFF'), 0) as co_amt,
        min(fy) as first_fy, max(fy) as last_fy,
        count(*) filter (where disb and fy between {s_lo} and {s_hi}) as s_disb,
        count(*) filter (where status='CHGOFF' and fy between {s_lo} and {s_hi}) as s_co,
        coalesce(sum(amt) filter (where disb and fy between {s_lo} and {s_hi}), 0) as s_gross,
        coalesce(sum(co_amt) filter (where status='CHGOFF' and fy between {s_lo} and {s_hi}), 0) as s_co_amt,
        count(*) filter (where fy between {r_lo} and {r_hi}) as r_approved,
        count(*) filter (where disb and fy between {r_lo} and {r_hi}) as r_disb,
        count(*) filter (where status='CHGOFF' and fy between {r_lo} and {r_hi}) as r_co,
        coalesce(sum(amt) filter (where status<>'CANCLD' and fy between {r_lo} and {r_hi}), 0) as r_gross,
        median(amt) filter (where status<>'CANCLD' and fy between {r_lo} and {r_hi}) as r_med_loan,
        median(rate) filter (where status<>'CANCLD' and rate > 0 and fy between {r_lo} and {r_hi}) as r_med_rate,
        median(term) filter (where status<>'CANCLD' and term > 0 and fy between {r_lo} and {r_hi}) as r_med_term,
        count(*) filter (where status<>'CANCLD' and fy between {r_lo} and {r_hi}
                         and (biz_age ilike 'Startup%' or biz_age ilike 'New%')) as r_new,
        count(*) filter (where status<>'CANCLD' and fy between {r_lo} and {r_hi}
                         and biz_age ilike 'Change of Ownership%') as r_coo,
        count(*) filter (where status<>'CANCLD' and fy between {r_lo} and {r_hi}
                         and biz_age not in ('', 'Unanswered')) as r_age_known,
        median(amt) filter (where disb) as med_loan
    """

    def rows(sql: str) -> list[dict]:
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def metric_block(m: dict) -> dict:
        s_rate = _rate(m["s_co"], m["s_disb"]) if m["s_disb"] >= LIMITED_MIN else None
        return {
            "all": {
                "approved": m["approved"], "disbursed": m["disbursed"], "paid_in_full": m["pif"],
                "charged_off": m["chgoff"], "active": m["active"], "cancelled": m["cancelled"],
                "undisbursed": m["undisbursed"], "gross": _r(m["gross"]), "charged_off_amount": _r(m["co_amt"]),
                "first_fy": m["first_fy"], "last_fy": m["last_fy"], "median_loan": _r(m["med_loan"]),
                "rate": _rate(m["chgoff"], m["disbursed"]) if m["disbursed"] >= LIMITED_MIN else None,
            },
            "seasoned": {
                "from_fy": s_lo, "to_fy": s_hi, "disbursed": m["s_disb"], "charged_off": m["s_co"],
                "gross": _r(m["s_gross"]), "charged_off_amount": _r(m["s_co_amt"]),
                "rate": s_rate,
                "rate_dollar_pct": round(100 * m["s_co_amt"] / m["s_gross"], 1)
                if m["s_gross"] and m["s_disb"] >= LIMITED_MIN else None,
                "tier": _tier(m["s_disb"]),
            },
            "recent": {
                "from_fy": r_lo, "to_fy": r_hi, "approved": m["r_approved"], "disbursed": m["r_disb"],
                "charged_off": m["r_co"], "gross": _r(m["r_gross"]),
                "median_loan": _r(m["r_med_loan"]), "median_rate": _r(m["r_med_rate"], 2),
                "median_term_months": _r(m["r_med_term"]),
                "new_business_pct": round(100 * m["r_new"] / m["r_age_known"]) if m["r_age_known"] >= 10 else None,
                "change_of_ownership_pct": round(100 * m["r_coo"] / m["r_age_known"])
                if m["r_age_known"] >= 10 else None,
            },
        }

    # ---- lender display names ----------------------------------------------------------
    lender_name = dict(
        con.execute(
            """select lender, arg_max(lender_raw, n) from
               (select lender, lender_raw, count(*) n from loans where lender is not null group by 1,2)
               group by 1"""
        ).fetchall()
    )
    lender_slug: dict[str, str] = {}

    # ---- industries (all 7(a) loans) ---------------------------------------------------
    ind_rows = rows(f"select ind, {METRICS} from loans where ind is not null group by 1")
    ind_by_year = defaultdict(list)
    for r in rows(
        f"""select ind, fy, count(*) approved, count(*) filter (where disb) disbursed,
                   count(*) filter (where status='PIF') pif, count(*) filter (where status='CHGOFF') chgoff,
                   count(*) filter (where status='EXEMPT') active
            from loans where ind is not null and fy >= {s_lo} group by 1,2 order by 1,2"""
    ):
        ind_by_year[r.pop("ind")].append(r)
    ind_lenders = defaultdict(list)
    for r in rows(
        f"""select * from (select ind, lender, count(*) loans, sum(amt) gross,
                 row_number() over (partition by ind order by count(*) desc, sum(amt) desc) rn
               from loans where ind is not null and lender is not null and status<>'CANCLD'
                 and fy between {r_lo} and {r_hi} group by 1,2) where rn <= 10"""
    ):
        ind_lenders[r["ind"]].append({"lender": r["lender"], "loans": r["loans"], "gross": _r(r["gross"])})
    ind_brands = defaultdict(list)
    for r in rows(
        f"""select * from (select ind, brand, count(*) loans,
                 row_number() over (partition by ind order by count(*) desc) rn
               from fl where ind is not null and disb and fy >= {s_lo} group by 1,2) where rn <= 12"""
    ):
        ind_brands[r["ind"]].append((r["brand"], r["loans"]))

    industries = {}
    ind_slugs: set[str] = set()
    for m in sorted(ind_rows, key=lambda r: -r["s_disb"]):
        name = m["ind"]
        slug = c.slugify(name)[:70].strip("-")
        if m["s_disb"] < INDUSTRY_PAGE_MIN or slug in ind_slugs:
            continue
        ind_slugs.add(slug)
        industries[name] = {
            "name": name, "slug": slug, "codes": ind_codes.get(name, [])[:6],
            **metric_block(m), "by_year": ind_by_year.get(name, []),
            "_lenders": ind_lenders.get(name, []), "_brands": ind_brands.get(name, []),
        }

    # ---- brands ------------------------------------------------------------------------
    brand_rows = {m["brand"]: m for m in rows(f"select brand, {METRICS} from fl group by 1")}
    by_year = defaultdict(list)
    for r in rows(
        """select brand, fy, count(*) approved, count(*) filter (where disb) disbursed,
                  count(*) filter (where status='PIF') pif, count(*) filter (where status='CHGOFF') chgoff,
                  count(*) filter (where status='EXEMPT') active, coalesce(sum(amt) filter (where disb),0) gross
           from fl group by 1,2 order by 1,2"""
    ):
        b = r.pop("brand")
        r["gross"] = _r(r["gross"])
        by_year[b].append(r)
    co_by_year = defaultdict(list)
    for r in rows(
        """select brand, year(co_date) y, count(*) n, sum(co_amt) amt from fl
           where status='CHGOFF' and co_date is not null group by 1,2 order by 1,2"""
    ):
        co_by_year[r["brand"]].append({"year": r["y"], "loans": r["n"], "amount": _r(r["amt"])})
    top_lenders = defaultdict(list)
    for r in rows(
        f"""select * from (select brand, lender, count(*) loans, sum(amt) gross, max(fy) last_fy,
                 row_number() over (partition by brand order by count(*) desc, sum(amt) desc) rn
               from fl where lender is not null and status<>'CANCLD' and fy >= {w_lo} group by 1,2)
            where rn <= 10"""
    ):
        top_lenders[r["brand"]].append(
            {"lender": r["lender"], "loans": r["loans"], "gross": _r(r["gross"]), "last_fy": r["last_fy"]}
        )
    n_lenders = dict(
        con.execute(
            f"select brand, count(distinct lender) from fl where status<>'CANCLD' and fy >= {w_lo} group by 1"
        ).fetchall()
    )
    top_states = defaultdict(list)
    for r in rows(
        f"""select * from (select brand, state, count(*) loans,
                 row_number() over (partition by brand order by count(*) desc) rn
               from fl where state is not null and status<>'CANCLD' and fy >= {w_lo} group by 1,2)
            where rn <= 8"""
    ):
        top_states[r["brand"]].append({"state": r["state"], "loans": r["loans"]})
    dom_ind: dict[str, tuple[str, int]] = {}
    for where in (f"fy >= {s_lo}", "true"):  # prefer the brand's current industry; fall back to all-time
        for r in rows(
            f"""select brand, ind, n, tot from (select brand, ind, count(*) n,
                     sum(count(*)) over (partition by brand) tot,
                     row_number() over (partition by brand order by count(*) desc) rn
                   from fl where ind is not null and disb and {where} group by 1,2) where rn = 1"""
        ):
            if r["brand"] not in dom_ind and r["tot"] >= (10 if where != "true" else 1):
                dom_ind[r["brand"]] = (r["ind"], round(100 * r["n"] / r["tot"]))

    # Industry benchmarks for every industry, including ones too small for a page.
    ind_bench = {m["ind"]: m for m in ind_rows}

    brands = {}
    for eid, m in brand_rows.items():
        e = ents[eid]
        # A page needs enough history to say something: a long record, a seasoned sample, or current activity.
        if not (m["disbursed"] >= BRAND_PAGE_MIN_ALL or m["s_disb"] >= LIMITED_MIN or m["r_approved"] >= LIMITED_MIN):
            continue
        nc = dom_ind.get(eid)
        ind = None
        if nc:
            ib = ind_bench.get(nc[0])
            ind = {
                "name": nc[0], "codes": ind_codes.get(nc[0], [])[:3],
                "share_pct": nc[1], "slug": industries[nc[0]]["slug"] if nc[0] in industries else None,
                "seasoned_rate": _rate(ib["s_co"], ib["s_disb"]) if ib and ib["s_disb"] >= RATED_MIN else None,
                "seasoned_disbursed": ib["s_disb"] if ib else None,
            }
        d = e.directory if (e.directory and not eid.startswith("L:")) else None
        brands[eid] = {
            "id": eid, "slug": e.slug, "name": e.name, "match": e.match,
            "source_codes": sorted(e.codes),
            "source_names": [n for n, _ in sorted(e.names.items(), key=lambda kv: -kv[1])][:8],
            "merged_legacy_codes": len(e.merged),
            "directory": {
                "listed": bool(d), "code": d["code"] if d else None, "name": d["brand"] if d else None,
                "ftc": d["ftc"] if d else None, "certified": d["certified"] if d else None,
                "listed_since": d["listed_since"] if d else None, "notes": d["notes"] if d else None,
            },
            **metric_block(m),
            "by_year": by_year.get(eid, []),
            "chargeoffs_by_year": co_by_year.get(eid, []),
            "lenders": top_lenders.get(eid, []),
            "lender_count": n_lenders.get(eid, 0),
            "states": top_states.get(eid, []),
            "industry": ind,
        }

    # Ranks among rated brands (lower charge-off rate is rank 1).
    rated = sorted(
        (b for b in brands.values() if b["seasoned"]["tier"] == "rated"),
        key=lambda b: (b["seasoned"]["rate"]["pct"], -b["seasoned"]["disbursed"], b["name"]),
    )
    for i, b in enumerate(rated, 1):
        b["rank"] = {"position": i, "of": len(rated)}
    # Peers: other rated brands in the same industry, closest in loan volume.
    by_ind = defaultdict(list)
    for b in rated:
        if b["industry"]:
            by_ind[b["industry"]["name"]].append(b)
    for b in brands.values():
        peers = [p for p in by_ind.get(b["industry"]["name"] if b["industry"] else "", []) if p["id"] != b["id"]]
        peers.sort(key=lambda p: -p["seasoned"]["disbursed"])
        b["peers"] = [p["slug"] for p in peers[:8]]

    slug_of = {eid: b["slug"] for eid, b in brands.items()}
    name_of = {eid: b["name"] for eid, b in brands.items()}

    # ---- lenders -----------------------------------------------------------------------
    lender_rows = rows(
        f"""select l.lender,
                   count(*) filter (where fy >= {w_lo} and status<>'CANCLD') loans10,
                   coalesce(sum(amt) filter (where fy >= {w_lo} and status<>'CANCLD'),0) gross10,
                   count(*) filter (where fy between {r_lo} and {r_hi} and status<>'CANCLD') loans5,
                   median(amt) filter (where fy between {r_lo} and {r_hi} and status<>'CANCLD') med_loan,
                   median(rate) filter (where fy between {r_lo} and {r_hi} and status<>'CANCLD' and rate>0) med_rate,
                   max(fy) last_fy
            from loans l where lender is not null group by 1"""
    )
    fr_l = {
        r["lender"]: r
        for r in rows(
            f"""select lender, count(*) loans, sum(amt) gross, count(distinct brand) brands,
                       median(amt) med_loan, max(fy) last_fy
                from fl where lender is not null and status<>'CANCLD' and fy >= {w_lo} group by 1"""
        )
    }
    l_brands = defaultdict(list)
    for r in rows(
        f"""select * from (select lender, brand, count(*) loans, sum(amt) gross,
                 row_number() over (partition by lender order by count(*) desc, sum(amt) desc) rn
               from fl where lender is not null and status<>'CANCLD' and fy >= {w_lo} group by 1,2)
            where rn <= 15"""
    ):
        l_brands[r["lender"]].append((r["brand"], r["loans"], _r(r["gross"])))
    l_states = defaultdict(list)
    for r in rows(
        f"""select * from (select lender, state, count(*) loans,
                 row_number() over (partition by lender order by count(*) desc) rn
               from fl where lender is not null and state is not null and status<>'CANCLD' and fy >= {w_lo}
               group by 1,2) where rn <= 8"""
    ):
        l_states[r["lender"]].append({"state": r["state"], "loans": r["loans"]})
    l_inds = defaultdict(list)
    for r in rows(
        f"""select * from (select lender, ind, count(*) loans,
                 row_number() over (partition by lender order by count(*) desc) rn
               from fl where lender is not null and ind is not null and status<>'CANCLD' and fy >= {w_lo}
               group by 1,2) where rn <= 6"""
    ):
        l_inds[r["lender"]].append((r["ind"], r["loans"]))

    lenders = {}
    used_slugs: set[str] = set()
    for m in sorted(lender_rows, key=lambda r: -(fr_l.get(r["lender"], {}).get("loans", 0))):
        key = m["lender"]
        f = fr_l.get(key)
        if not f or f["loans"] < LENDER_PAGE_MIN:
            continue
        nm = lender_name.get(key, key)
        slug = c.slugify(nm)
        if slug in used_slugs:
            continue
        used_slugs.add(slug)
        lender_slug[key] = slug
        lenders[key] = {
            "key": key, "name": nm, "slug": slug,
            "window_from_fy": w_lo, "window_to_fy": fy,
            "franchise": {"loans": f["loans"], "gross": _r(f["gross"]), "brands": f["brands"],
                          "median_loan": _r(f["med_loan"]), "last_fy": f["last_fy"]},
            "all": {"loans": m["loans10"], "gross": _r(m["gross10"]), "loans_recent": m["loans5"],
                    "median_loan_recent": _r(m["med_loan"]), "median_rate_recent": _r(m["med_rate"], 2)},
            "franchise_share_pct": round(100 * f["loans"] / m["loans10"]) if m["loans10"] else None,
            "brands": [{"slug": slug_of[b], "name": name_of[b], "loans": n, "gross": g}
                       for b, n, g in l_brands.get(key, []) if b in slug_of],
            "states": l_states.get(key, []),
            "industries": [{"name": nm_, "slug": industries[nm_]["slug"] if nm_ in industries else None, "loans": n}
                           for nm_, n in l_inds.get(key, [])],
        }

    def lender_ref(key: str) -> dict:
        return {"name": lender_name.get(key, key), "slug": lender_slug.get(key)}

    for b in brands.values():
        b["lenders"] = [{**lender_ref(x["lender"]), "loans": x["loans"], "gross": x["gross"], "last_fy": x["last_fy"]}
                        for x in b["lenders"]]
    for ind in industries.values():
        ind["lenders"] = [{**lender_ref(x["lender"]), "loans": x["loans"], "gross": x["gross"]}
                          for x in ind.pop("_lenders")]
        ind["brands"] = [{"slug": slug_of[b], "name": name_of[b], "loans": n,
                          "rate": brands[b]["seasoned"]["rate"], "tier": brands[b]["seasoned"]["tier"]}
                         for b, n in ind.pop("_brands") if b in slug_of]

    # ---- states ------------------------------------------------------------------------
    st_rows = rows(
        f"""select state, count(*) filter (where fy >= {w_lo} and status<>'CANCLD') loans,
                   coalesce(sum(amt) filter (where fy >= {w_lo} and status<>'CANCLD'),0) gross,
                   count(distinct brand) filter (where fy >= {w_lo} and status<>'CANCLD') brands,
                   median(amt) filter (where fy between {r_lo} and {r_hi} and status<>'CANCLD') med_loan,
                   count(*) filter (where disb and fy between {s_lo} and {s_hi}) s_disb,
                   count(*) filter (where status='CHGOFF' and fy between {s_lo} and {s_hi}) s_co
            from fl where state is not null group by 1"""
    )
    st_brands = defaultdict(list)
    for r in rows(
        f"""select * from (select state, brand, count(*) loans,
                 row_number() over (partition by state order by count(*) desc) rn
               from fl where state is not null and status<>'CANCLD' and fy >= {w_lo} group by 1,2)
            where rn <= 15"""
    ):
        st_brands[r["state"]].append((r["brand"], r["loans"]))
    st_lenders = defaultdict(list)
    for r in rows(
        f"""select * from (select state, lender, count(*) loans, sum(amt) gross,
                 row_number() over (partition by state order by count(*) desc, sum(amt) desc) rn
               from fl where state is not null and lender is not null and status<>'CANCLD' and fy >= {w_lo}
               group by 1,2) where rn <= 12"""
    ):
        st_lenders[r["state"]].append({**lender_ref(r["lender"]), "loans": r["loans"], "gross": _r(r["gross"])})
    states = {}
    for m in st_rows:
        code = m["state"]
        if code not in STATES or m["loans"] < 50:
            continue
        states[code] = {
            "code": code, "name": STATES[code], "slug": c.slugify(STATES[code]),
            "window_from_fy": w_lo, "window_to_fy": fy,
            "loans": m["loans"], "gross": _r(m["gross"]), "brands_count": m["brands"],
            "median_loan_recent": _r(m["med_loan"]),
            "seasoned": {"from_fy": s_lo, "to_fy": s_hi, "disbursed": m["s_disb"], "charged_off": m["s_co"],
                         "rate": _rate(m["s_co"], m["s_disb"]) if m["s_disb"] >= RATED_MIN else None},
            "brands": [{"slug": slug_of[b], "name": name_of[b], "loans": n,
                        "rate": brands[b]["seasoned"]["rate"], "tier": brands[b]["seasoned"]["tier"]}
                       for b, n in st_brands.get(code, []) if b in slug_of],
            "lenders": st_lenders.get(code, []),
        }

    # ---- summary -----------------------------------------------------------------------
    tot = rows(f"select {METRICS} from fl")[0]
    tot_all = rows(f"select {METRICS} from loans")[0]
    tot_non = rows(f"select {METRICS} from loans where fname is null")[0]
    cohort = rows(
        """select fy, count(*) approved, count(*) filter (where disb) disbursed,
                  count(*) filter (where status='CHGOFF') chgoff, count(*) filter (where status='PIF') pif,
                  count(*) filter (where status='EXEMPT') active
           from fl where fy is not null group by 1 order by 1"""
    )
    new_dir = sorted(
        ({"code": d["code"], "name": B.display_name(d["brand"], {}), "listed_since": d["listed_since"],
          "slug": brands[d["code"]]["slug"] if d["code"] in brands else None}
         for d in directory.values() if d["listed_since"]),
        key=lambda x: x["listed_since"], reverse=True,
    )[:60]
    summary = {
        "asof": asof.isoformat(), "asof_fy": fy,
        "windows": {"seasoned": [s_lo, s_hi], "recent": [r_lo, r_hi], "activity_from_fy": w_lo},
        "thresholds": {"rated_min": RATED_MIN, "limited_min": LIMITED_MIN, "brand_page_min_all_time": BRAND_PAGE_MIN_ALL,
                       "industry_page_min": INDUSTRY_PAGE_MIN, "lender_page_min": LENDER_PAGE_MIN},
        "counts": {
            "loans_total": raw_rows, "loans_franchise": franchise_rows, "unparsed_rows": other,
            "brands_with_loans": len(brand_rows), "brand_pages": len(brands), "brands_rated": len(rated),
            "industry_pages": len(industries), "lender_pages": len(lenders), "state_pages": len(states),
            "directory_brands": len(directory),
        },
        "franchise": metric_block(tot), "all_7a": metric_block(tot_all), "non_franchise": metric_block(tot_non),
        "franchise_by_year": cohort,
        "directory_recent": new_dir,
    }
    con.close()
    return {
        "brands": sorted(brands.values(), key=lambda b: b["slug"]),
        "industries": sorted(industries.values(), key=lambda i: i["slug"]),
        "lenders": sorted(lenders.values(), key=lambda l: l["slug"]),
        "states": sorted(states.values(), key=lambda s: s["code"]),
        "summary": summary,
    }
