"""Brand entity resolution.

The loan files identify a franchise by (FranchiseCode, FranchiseName). Two code
systems exist: legacy numeric codes (loans approved up to roughly FY2018) and
"S" codes from the SBA Franchise Directory (FY2018 onward). The same brand
therefore appears under several codes and spellings.

Resolution rules, in order, most conservative first:
  1. An S code is its own entity. Display name comes from the directory.
  2. A legacy code merges into an S-code entity only when its normalised name
     equals a normalised directory name segment or S-code loan name (exact).
  3. A curated alias in brand_aliases.csv (reviewed by hand) merges or renames.
  4. A legacy name that differs from exactly one known brand only by trailing generic
     descriptor words ("Orange Leaf" / "Orange Leaf Frozen Yogurt") merges into it.
  5. Otherwise legacy codes that share a normalised name form a legacy entity.

Nothing is merged on fuzzy similarity alone. Every entity records how it was
matched so the site can show it.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .common import slugify

ALIASES_CSV = Path(__file__).with_name("brand_aliases.csv")

_TRAILING = {
    "INC", "INCORPORATED", "LLC", "LLP", "LP", "LTD", "CORP", "CORPORATION", "CO", "COMPANY",
    "FRANCHISE", "FRANCHISES", "FRANCHISING", "FRANCHISOR", "SYSTEMS", "SYSTEM", "INTERNATIONAL",
    "INTL", "USA", "US", "ENTERPRISES", "HOLDINGS", "GROUP", "WORLDWIDE", "THE",
}
_PLACEHOLDER = re.compile(r"^(0+|1|N/?A|NONE|NULL|-+)?$", re.I)


def norm_key(name: str) -> str:
    """Normalised comparison key for a brand name."""
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"['’`\.]", "", s)
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    toks = s.split()
    while toks and toks[0] == "THE":
        toks.pop(0)
    while len(toks) > 1 and toks[-1] in _TRAILING:
        toks.pop()
    return " ".join(toks)


def is_placeholder_code(code: str | None) -> bool:
    return _PLACEHOLDER.match((code or "").strip()) is not None


_FKA = re.compile(r"\s*[\(\[,-]?\s*\b(?:f/k/a|f\.k\.a\.?|fka|formerly known as|formerly)\b[:\s]*", re.I)


def split_former(brand: str) -> tuple[str, str | None]:
    """("Experimax f/k/a Experimac") -> ("Experimax", "Experimac"). No former name -> (brand, None)."""
    m = _FKA.search(brand or "")
    if not m or m.start() == 0:
        return (brand or "").strip(), None
    cur = brand[: m.start()].strip()
    old = brand[m.end():].strip().rstrip(")]").strip()
    return (cur, old or None) if cur else (brand.strip(), None)


def directory_segments(brand: str) -> list[str]:
    """Every name a directory entry uses for the brand, including a stated former name."""
    cur, old = split_former(brand or "")
    names = [cur] + ([old] if old else [])
    parts = [p.strip() for n in names for p in re.split(r"\s*[/;]\s*", n) if p.strip()]
    return [p for p in parts if len(p) >= 3] or ([brand.strip()] if brand and brand.strip() else [])


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("\u2019", "'").strip()


def display_name(directory_brand: str | None, loan_names: dict[str, int]) -> str:
    """Directory entries list alternates after a slash, so the first segment is the brand.
    Loan-file names are used whole: a slash there usually marks a co-brand, not an alternate."""
    if directory_brand:
        cur, old = split_former(directory_brand)
        segs = directory_segments(cur)
        if segs:
            first = segs[0]
            if len(first) < 5 and len(segs) > 1:
                first = f"{segs[0]} / {segs[1]}"
            if old:
                first = f"{first} (formerly {directory_segments(old)[0]})"
            return _clean(first)
    if loan_names:
        raw = max(loan_names.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        if raw == raw.upper():
            return titlecase(raw)
        cur, old = split_former(raw)
        return _clean(f"{cur} (formerly {old})" if old else raw)
    return "Unknown"


_SMALL = {"and", "of", "the", "for", "by", "in", "at", "on", "to", "a", "an"}
_KEEP_UPPER = {"UPS", "USA", "US", "BBQ", "IHOP", "KFC", "GNC", "AAMCO", "TCBY", "CPR", "HVAC", "RV", "II", "III", "IV",
               "ATM", "DQ", "TGI", "ERA", "RE", "MAX", "H&R", "A&W", "UFC", "YMCA", "PJ", "TLC", "CKO", "F45", "KOA"}


def titlecase(name: str) -> str:
    """Readable casing for legacy ALL-CAPS names. Never used for directory names."""
    if name != name.upper():
        return re.sub(r"\s+", " ", name).strip()
    out = []
    for i, w in enumerate(re.sub(r"\s+", " ", name).strip().split(" ")):
        core = re.sub(r"[^A-Z0-9&]", "", w)
        if core in _KEEP_UPPER or (len(core) <= 3 and re.search(r"\d", core)):
            out.append(w)
        elif i > 0 and w.lower() in _SMALL:
            out.append(w.lower())
        else:
            out.append(re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w.lower()).replace("'S", "'s"))
    return " ".join(out)


@dataclass
class Entity:
    id: str                     # S code, or "L:<norm key>" for legacy-only brands
    name: str = ""
    slug: str = ""
    match: str = ""             # directory | name-exact | alias | legacy
    directory: dict | None = None
    codes: set[str] = field(default_factory=set)
    names: dict[str, int] = field(default_factory=dict)
    s_names: dict[str, int] = field(default_factory=dict)  # spellings seen under the S code itself
    merged: dict[str, str] = field(default_factory=dict)  # legacy code -> how it was merged in
    loans: int = 0


# Words that describe what a business is rather than which brand it is. A legacy name may merge
# with a brand when the only difference is a tail made of these. Words that often mark a
# distinct system (EXPRESS, PLUS, GO, JR, numbers) are deliberately absent.
GENERIC_TAIL = set(
    """RESTAURANT RESTAURANTS CAFE GRILL BAR PIZZA PIZZERIA SUBS SUB SANDWICH SANDWICHES SHOP SHOPS SHOPPE
    STORE STORES CENTER CENTERS CENTRE CENTRES FROZEN YOGURT ICE CREAM CUSTARD COFFEE DONUTS BAKERY FITNESS
    GYM STUDIO STUDIOS SALON SALONS TANNING MASSAGE SPA HOTEL HOTELS MOTEL MOTELS INN INNS SUITES AND BY OF
    SERVICE SERVICES AUTO CAR CARE TIRE TIRES LEARNING SCHOOL SCHOOLS ACADEMY CLEANING HOME SENIOR STAFFING
    REALTY REAL ESTATE TAX PRINTING SIGNS KITCHEN EATERY BURGERS CHICKEN WINGS MEXICAN DELI TAKE N BAKE
    FRANCHISE FRANCHISING SYSTEMS SYSTEM INC LLC CORP COMPANY INTERNATIONAL USA DAYCARE CHILDCARE CHILD
    HEALTH FOOD FOODS JUICE SMOOTHIE SMOOTHIES BBQ BARBECUE BARBEQUE PIT STEAKHOUSE TACOS BURRITOS""".split()
)


def descriptor_related(a: str, b: str) -> bool:
    """True when one key is the other plus a tail made only of generic descriptor words."""
    if a == b:
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    if len(short) < 4 or not long_.startswith(short + " "):
        return False
    if all(t in GENERIC_TAIL for t in short.split()):
        return False
    return all(t in GENERIC_TAIL for t in long_[len(short) + 1:].split())


EXCLUDED_KEYS = {"TEMPORARY", "UNKNOWN", "NONE", "NA", "N A", "NOT APPLICABLE", "TBD"}
_SCODE = re.compile(r"^S\d{4}$")


def load_aliases(path: Path = ALIASES_CSV) -> dict:
    """Returns {"names": {norm_key: row}, "codes": {S code: row}}."""
    out: dict = {"names": {}, "codes": {}}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(l for l in fh if not l.startswith("#")):
            src = (row.get("source_name") or "").strip()
            rec = {
                "target": (row.get("target") or "").strip(),
                "display": (row.get("display") or "").strip(),
                "note": (row.get("note") or "").strip(),
            }
            if _SCODE.match(src):
                out["codes"][src] = rec
            elif norm_key(src):
                out["names"][norm_key(src)] = rec
    return out


def resolve(pairs: list[tuple[str, str, int]], directory: dict[str, dict], aliases: dict | None = None):
    """Resolve (code, name, n_loans) pairs to entities.

    Returns (entities by id, mapping (code, name) -> entity id). Pairs whose name is a
    placeholder ("TEMPORARY" and similar) are left unmapped and so excluded.
    """
    aliases = load_aliases() if aliases is None else aliases
    name_alias: dict[str, dict] = aliases.get("names", {})
    code_alias: dict[str, dict] = aliases.get("codes", {})
    code_remap = {src: rec["target"] for src, rec in code_alias.items() if _SCODE.match(rec["target"] or "")}
    ents: dict[str, Entity] = {}
    mapping: dict[tuple[str, str], str] = {}

    def ent(eid: str) -> Entity:
        if eid not in ents:
            ents[eid] = Entity(id=eid)
        return ents[eid]

    # Pass 1: S codes and directory brands.
    key_to_s: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for code, row in directory.items():
        target = code_remap.get(code, code)
        e = ent(target)
        if target == code:
            e.directory = row
        elif e.directory is None and target in directory:
            e.directory = directory[target]
        e.match = "directory"
        for seg in directory_segments(row["brand"]):
            key_to_s[norm_key(seg)][target] += 0
    for code, name, n in pairs:
        if _SCODE.match(code):
            target = code_remap.get(code, code)
            e = ent(target)
            e.match = e.match or "directory"
            e.codes.add(code)
            if target != code:
                e.merged[code] = "alias"
            e.names[name] = e.names.get(name, 0) + n
            e.loans += n
            mapping[(code, name)] = target
            e.s_names[name] = e.s_names.get(name, 0) + n
            for seg in {norm_key(name), *(norm_key(x) for x in split_former(name) if x)}:
                key_to_s[seg][target] += n

    def unique_s(key: str) -> str | None:
        cands = key_to_s.get(key)
        if not cands:
            return None
        if len(cands) == 1:
            return next(iter(cands))
        ranked = sorted(cands.items(), key=lambda kv: (-kv[1], kv[0]))
        # Ambiguous keys only resolve when one candidate clearly dominates.
        if ranked[0][1] >= 5 * max(1, ranked[1][1]):
            return ranked[0][0]
        return None

    # Known brand keys by first word, for the descriptor rule. Legacy keys are added as they are
    # created; processing the largest first lets small spelling variants fold into the main entry.
    by_first: dict[str, dict[str, str]] = defaultdict(dict)
    for k in key_to_s:
        s_code = unique_s(k)
        if s_code and k:
            by_first[k.split()[0]][k] = s_code

    def descriptor_target(key: str) -> str | None:
        hits = {eid for k, eid in by_first.get(key.split()[0], {}).items() if descriptor_related(key, k)}
        return next(iter(hits)) if len(hits) == 1 else None

    # Pass 2: legacy codes, largest first.
    for code, name, n in sorted(pairs, key=lambda p: (-p[2], p[0], p[1])):
        if (code, name) in mapping:
            continue
        key = norm_key(name)
        if not key or key in EXCLUDED_KEYS:
            continue
        how = "legacy"
        target: str | None = None
        alias = name_alias.get(key)
        if alias and alias["target"]:
            t = alias["target"]
            if _SCODE.match(t):
                target = code_remap.get(t, t)
            else:
                tk = norm_key(t)
                target = unique_s(tk) or f"L:{tk}"
            how = "alias"
        elif alias is not None:
            pass  # listed with an empty target: deliberately kept separate
        else:
            s = unique_s(key)
            if s:
                target, how = s, "name-exact"
            elif f"L:{key}" not in ents:
                d = descriptor_target(key)
                if d:
                    target, how = d, "name-descriptor"
        eid = target or f"L:{key}"
        if eid.startswith("L:"):
            by_first[key.split()[0]].setdefault(key, eid)
        e = ent(eid)
        if eid.startswith("L:"):
            if e.match != "alias":
                e.match = "alias" if how == "alias" else "legacy"
            if how == "name-descriptor":
                e.merged[code] = how
        else:
            e.match = e.match or "directory"
            e.merged[code] = how
        e.codes.add(code)
        e.names[name] = e.names.get(name, 0) + n
        e.loans += n
        mapping[(code, name)] = eid

    # Names and slugs. Slugs must be unique and stable: collisions get an id suffix.
    used: dict[str, str] = {}
    for eid in sorted(ents, key=lambda i: (-ents[i].loans, i)):
        e = ents[eid]
        override = ""
        if eid in code_alias and code_alias[eid]["display"]:
            override = code_alias[eid]["display"]
        elif eid.startswith("L:"):
            for nm in e.names:
                a = name_alias.get(norm_key(nm))
                if a and a["display"]:
                    override = a["display"]
        e.name = override or display_name(e.directory["brand"] if e.directory else None, e.s_names or e.names)
        base = slugify(e.name)
        slug = base
        if slug in used and used[slug] != eid:
            slug = f"{base}-{slugify(eid.replace('L:', 'legacy-'))[:24]}"
        used[slug] = eid
        e.slug = slug
    return ents, mapping
