"""
verify_all.py  -  "Is everything running correctly?"
====================================================

    python verify_all.py

Three independent implementations of the SAME rule
    derived(r, f)  <=>  exists d : req_design(r, d) AND design_code(d, f)
are computed and compared:

    1. plain Python sets     (traceability_dataset.derive_traces)
    2. Prolog / FOL          (traceability_fol.pl, run with swipl)
    3. Z3 / PL               (traceability_pl_z3.py)

If they all agree, the logic is doing what the dataset says.
A final MUTATION TEST changes the dataset on purpose and checks that all three
implementations notice the change in the same way.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_prolog_data import render
from traceability_dataset import (DEFAULT_DIR, FILE_CANDIDATES, _find, derive_traces,
                                  load_dataset)
from traceability_pl_z3 import sets_from_z3

HERE = Path(__file__).resolve().parent

# Numbers for the dataset as shipped. If you edit the dataset, update these.
EXPECTED_COUNTS = dict(requirements=17, designs=25, codes=25,
                       req_design=69, design_code=21, req_code=69)

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def prolog_pairs(workdir: Path, predicate: str):
    """Run  swipl ... -g 'dump(<predicate>)'  and parse the  Req|File  lines."""
    out = subprocess.run(
        ["swipl", "-q", "-s", "traceability_fol.pl", "-g", f"dump({predicate})", "-t", "halt"],
        cwd=workdir, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return {tuple(line.split("|", 1)) for line in out.stdout.splitlines() if "|" in line}


def run_prolog_available():
    return shutil.which("swipl") is not None


def all_three(ds, workdir: Path):
    """Return (python, prolog, z3) derived sets for a dataset."""
    (workdir / "traceability_data.pl").write_text(render(ds), encoding="utf-8")
    shutil.copy(HERE / "traceability_fol.pl", workdir / "traceability_fol.pl")
    py = derive_traces(ds)
    pl = prolog_pairs(workdir, "derived_trace") if run_prolog_available() else None
    z3_derived, _ = sets_from_z3(ds)
    return py, pl, z3_derived


def main():
    ds = load_dataset()
    has_swipl = run_prolog_available()

    print("\n1. DATASET LOADED CORRECTLY")
    actual = dict(requirements=len(ds.requirements), designs=len(ds.designs), codes=len(ds.codes),
                  req_design=len(ds.req_design), design_code=len(ds.design_code),
                  req_code=len(ds.req_code))
    for k, v in EXPECTED_COUNTS.items():
        check(f"{k} = {v}", actual[k] == v, f"found {actual[k]}")

    print("\n2. THREE IMPLEMENTATIONS AGREE")
    with tempfile.TemporaryDirectory() as tmp:
        py, pl, z3d = all_three(ds, Path(tmp))
        check("Python derived count", len(py) > 0, f"{len(py)} traces")
        check("Z3 == Python", z3d == py)
        if has_swipl:
            check("Prolog == Python", pl == py)
            only_pl = prolog_pairs(Path(tmp), "derived_only")
            truth_pl = prolog_pairs(Path(tmp), "truth_only")
            rec = set(ds.req_code)
            check("Prolog derived_only == Python (derived - recorded)", only_pl == py - rec,
                  f"{len(only_pl)} pairs")
            check("Prolog truth_only == Python (recorded - derived)", truth_pl == rec - py,
                  f"{len(truth_pl)} pairs")
        else:
            print("  [SKIP] swipl not found - install SWI-Prolog to check the Prolog side")
        z3_derived, z3_recorded = sets_from_z3(ds)
        check("Z3 recorded set == req-to-code.md", z3_recorded == set(ds.req_code))

    print("\n3. GENERATED FILE IS UP TO DATE")
    on_disk = (HERE / "traceability_data.pl").read_text(encoding="utf-8")
    check("traceability_data.pl matches ./dataset", on_disk == render(ds),
          "if FAIL: run  python build_prolog_data.py")

    print("\n4. HAND-CHECKED EXAMPLES")
    fr01 = {c for r, c in py if r == "fr01"}
    check("FR01 -> exactly AccountController, User, account/add view",
          fr01 == {"app/Http/Controllers/AccountController.php",
                   "app/Models/User.php",
                   "resources/views/account/add.blade.php"})
    check("FR06 has no derived trace (no design link)", not any(r == "fr06" for r, _ in py))
    check("FR17 has no derived trace (its design classes have no code link)",
          not any(r == "fr17" for r, _ in py))

    print("\n5. MUTATION TEST  (change the data on purpose)")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "dataset").mkdir()
        for key in FILE_CANDIDATES:                     # copy only the six dataset files
            src = _find(DEFAULT_DIR, key)
            shutil.copy(src, tmp / "dataset" / src.name)
        # new fact: FR06 is implemented by the design class C_Schedule
        with open(tmp / "dataset" / "req-to-design.md", "a", encoding="utf-8", newline="") as fh:
            fh.write("\r\nFR06\tC_Schedule\t1")
        mutated = load_dataset(tmp / "dataset")
        work = tmp / "work"
        work.mkdir()
        py2, pl2, z3_2 = all_three(mutated, work)
        target = ("fr06", "app/Http/Controllers/ScheduleController.php")
        check("new trace appears in Python", target in py2 and len(py2) == len(py) + 1)
        check("new trace appears in Z3", target in z3_2 and z3_2 == py2)
        if has_swipl:
            check("new trace appears in Prolog", target in pl2 and pl2 == py2)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
