"""
traceability_dataset.py
=======================
Reads the six markdown files in ./dataset, cleans the names and returns ONE
clean Dataset object.

Both the Prolog side (First Order Logic) and the Z3 side (Propositional Logic)
use this loader, so they are guaranteed to reason about exactly the same data.

Cleaning rules are all visible in this file (see MANUAL DECISIONS below).
Nothing is changed silently: every fix is written to `Dataset.cleaning_log`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _default_dir() -> Path:
    """Use ./dataset if it exists (zip layout), otherwise the folder of this script
    (flat layout: all files downloaded into one folder)."""
    sub = _HERE / "dataset"
    return sub if sub.is_dir() else _HERE


DEFAULT_DIR = _default_dir()

# The same file may be saved with spaces or underscores in its name.
FILE_CANDIDATES = {
    "requirements":   ["requirements.md"],
    "design_classes": ["design_classes.md", "design classes.md"],
    "source_codes":   ["source_codes.md", "source codes.md"],
    "req_to_design":  ["req-to-design.md"],
    "design_to_code": ["design-to-code.md"],
    "req_to_code":    ["req-to-code.md"],
}

# ----------------------------------------------------------------------------
# MANUAL DECISIONS  (edit here if you disagree with them)
# ----------------------------------------------------------------------------
# req-to-design.md uses M_Account, but the design class list only has M_User,
# and design-to-code.md maps M_User -> app/Models/User.php.
DESIGN_ALIASES = {"m_account": "m_user"}

# source_codes.md lists Nilai.php, but both link tables use Grades.php
# ("nilai" is Indonesian for "grades"). source_codes.md is treated as the
# authority on which files exist, so Grades.php is renamed to Nilai.php.
# Keys are lower-case paths with forward slashes.
CODE_ALIASES = {"app/models/grades.php": "app/models/nilai.php"}

STEREOTYPES = {"c": "controller", "m": "model", "v": "view"}


@dataclass
class Dataset:
    requirements: dict            # 'fr01' -> 'Administrator adds user'
    designs: dict                 # 'c_account' -> 'controller'
    declared_designs: set         # designs that appear in design_classes.md
    codes: list                   # canonical file paths (forward slashes)
    declared_codes: set           # files that appear in source_codes.md
    req_design: list              # [('fr01', 'c_account'), ...]
    design_code: list             # [('c_account', 'app/Http/...'), ...]
    req_code: list               # [('fr01', 'app/Http/...'), ...]
    no_link_rows: list = field(default_factory=list)   # rows marked 0
    cleaning_log: list = field(default_factory=list)   # every automatic fix


# ----------------------------------------------------------------------------
# Low level reading helpers
# ----------------------------------------------------------------------------
def _find(data_dir: Path, key: str) -> Path:
    for name in FILE_CANDIDATES[key]:
        p = data_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Cannot find any of {FILE_CANDIDATES[key]} in {data_dir}\n"
        f"Put the six .md files next to the scripts, or in a folder called 'dataset'.")


def _lines(path: Path) -> list:
    """Non-empty lines. splitlines() also removes Windows CRLF endings."""
    text = path.read_text(encoding="utf-8-sig")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _split(line: str) -> list:
    """Split on TAB (or 2+ spaces if an editor turned tabs into spaces)."""
    return [f.strip() for f in re.split(r"\t+|\s{2,}", line.strip())]


def _add(store: list, seen: set, item: tuple):
    if item not in seen:
        seen.add(item)
        store.append(item)


# ----------------------------------------------------------------------------
# Main loader
# ----------------------------------------------------------------------------
def load_dataset(data_dir=DEFAULT_DIR) -> Dataset:
    data_dir = Path(data_dir)
    notes: dict = {}                                    # message -> how many times it happened

    def log_note(msg: str):
        notes[msg] = notes.get(msg, 0) + 1

    # ---------- name normalisers ----------
    def norm_design(raw: str) -> str:
        raw = raw.strip()
        compact = re.sub(r"\s+", "", raw)              # 'M_ User' -> 'M_User'
        if compact != raw:
            log_note(f"design name whitespace removed: {raw!r} -> {compact!r}")
        key = compact.lower()
        if key in DESIGN_ALIASES:
            log_note(f"design alias applied: {key} -> {DESIGN_ALIASES[key]}")
            key = DESIGN_ALIASES[key]
        return key

    # ---------- 1. requirements ----------
    requirements = {}
    for ln in _lines(_find(data_dir, "requirements")):
        rid, text = re.split(r"\t+|\s{2,}", ln, maxsplit=1)   # split ONLY at the first gap
        requirements[rid.strip().lower()] = re.sub(r"\s+", " ", text.strip())

    # ---------- 2. design classes (only lines after the ------ separator) ----------
    designs, declared_designs = {}, set()
    after_separator = False
    for ln in _lines(_find(data_dir, "design_classes")):
        if ln.startswith("---"):
            after_separator = True
            continue
        if not after_separator:
            continue                                    # skip the 'Prefix:' legend
        key = norm_design(ln)
        designs[key] = STEREOTYPES[key[0]]
        declared_designs.add(key)

    # ---------- 3. source files ----------
    canon = {}                                          # lower-case path -> canonical spelling
    codes, declared_codes = [], set()
    for ln in _lines(_find(data_dir, "source_codes")):
        p = ln.replace("\\", "/")
        canon[p.lower()] = p
        codes.append(p)
        declared_codes.add(p)

    def norm_code(raw: str) -> str:
        p = raw.strip().replace("\\", "/")
        low = p.lower()
        if low in CODE_ALIASES:
            low = CODE_ALIASES[low]
            log_note(f"file alias applied: {p} -> {canon[low]}")
        elif low not in canon:                          # not in source_codes.md
            canon[low] = p
            codes.append(p)
        elif canon[low] != p:
            log_note(f"file spelling unified: {p} -> {canon[low]}")
        return canon[low]

    # ---------- 4. link tables ----------
    req_design, design_code, req_code = [], [], []
    seen_rd, seen_dc, seen_rc = set(), set(), set()
    no_link = []

    def rid_ok(r: str) -> str:
        r = r.lower()
        if r not in requirements:
            requirements[r] = ""
            log_note(f"requirement {r} used in a link table but missing in requirements.md")
        return r

    def design_ok(d: str) -> str:
        d = norm_design(d)
        designs.setdefault(d, STEREOTYPES[d[0]])
        return d

    for ln in _lines(_find(data_dir, "req_to_design")):
        a, b, flag = _split(ln)
        if flag != "1" or a == "-" or b == "-":
            no_link.append(("req_to_design", a, b))
            if a != "-":
                rid_ok(a)
            continue
        _add(req_design, seen_rd, (rid_ok(a), design_ok(b)))

    for ln in _lines(_find(data_dir, "design_to_code")):
        a, b, flag = _split(ln)
        if flag != "1" or a == "-" or b == "-":
            no_link.append(("design_to_code", a, b))
            if b != "-":
                norm_code(b)
            continue
        _add(design_code, seen_dc, (design_ok(a), norm_code(b)))

    for ln in _lines(_find(data_dir, "req_to_code")):
        a, b, flag = _split(ln)
        if flag != "1" or a == "-" or b == "-":
            no_link.append(("req_to_code", a, b))
            if a != "-":
                rid_ok(a)
            continue
        _add(req_code, seen_rc, (rid_ok(a), norm_code(b)))

    return Dataset(requirements, designs, declared_designs, codes, declared_codes,
                   req_design, design_code, req_code, no_link,
                   [f"{m} (x{n})" if n > 1 else m for m, n in notes.items()])


# ----------------------------------------------------------------------------
# Independent "oracle": the same rule written as plain Python sets.
# verify_all.py compares Prolog and Z3 against this.
# ----------------------------------------------------------------------------
def derive_traces(ds: Dataset) -> set:
    """derived(r, c)  <=>  there is a design d with  req_design(r, d)  and  design_code(d, c)."""
    return {(r, c)
            for (r, d) in ds.req_design
            for (d2, c) in ds.design_code if d == d2}


def data_quality_report(ds: Dataset) -> list:
    out = []
    for d in ds.designs:
        if d not in ds.declared_designs:
            out.append(f"design element used in links but NOT in design_classes.md: {d}")
    for c in ds.codes:
        if c not in ds.declared_codes:
            out.append(f"code file used in links but NOT in source_codes.md: {c}")
    return out
