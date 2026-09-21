"""
traceability_pl_z3.py  -  Software traceability with PROPOSITIONAL LOGIC (Z3)
=============================================================================

HOW TO RUN
    pip install z3-solver
    python traceability_pl_z3.py

PROPOSITIONAL LOGIC has no objects and no variables like "for all r".
It only has TRUE/FALSE statements.  So we create ONE Boolean for every
possible pair, and a loop writes the repetitive part for us:

    RD_fr01_c_account          "requirement fr01 is linked to design c_account"
    DC_c_account_Http_..._php  "design c_account is implemented in that file"
    RC_fr01_..._php            "req-to-code.md says fr01 is linked to that file"
    TR_fr01_..._php            "a trace fr01 -> file is DERIVED"

Then we write three kinds of formulas:
    1. FACTS   (unit clauses)   RD_fr01_c_account          /   Not(RD_fr06_c_account)
    2. RULES   (biconditional)  TR(r,f)  <->  OR over d of ( RD(r,d) AND DC(d,f) )
    3. QUERIES (entailment)     to prove a statement Q, add NOT Q and ask Z3:
                                   unsat -> Q is always true   (PROVED)
                                   sat   -> Q can be false     (a counter-example exists)
"""

import re

from z3 import And, Bool, Implies, Not, Or, Solver, is_true, sat, unsat

from traceability_dataset import (data_quality_report, derive_traces,
                                  load_dataset)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def label(path: str) -> str:
    """Short readable name for a file, used inside Z3 variable names."""
    p = re.sub(r"^(app/|resources/)", "", path)
    p = re.sub(r"(\.blade)?\.php$", "", p)
    return re.sub(r"[^A-Za-z0-9]+", "_", p)          # Http_Controllers_AccountController


def entails(solver: Solver, formula):
    """Does the solver's knowledge force `formula` to be true?
    Returns (True, None) if proved, else (False, counter-example model)."""
    solver.push()
    solver.add(Not(formula))
    result = solver.check()
    model = solver.model() if result == sat else None
    solver.pop()
    return result == unsat, model


# ----------------------------------------------------------------------------
# build the propositional model
# ----------------------------------------------------------------------------
def build(ds):
    reqs = list(ds.requirements)
    designs = list(ds.designs)
    codes = list(ds.codes)

    # --- one Boolean per possible pair ------------------------------------
    RD = {(r, d): Bool(f"RD_{r}_{d}") for r in reqs for d in designs}
    DC = {(d, f): Bool(f"DC_{d}_{label(f)}") for d in designs for f in codes}
    RC = {(r, f): Bool(f"RC_{r}_{label(f)}") for r in reqs for f in codes}
    TR = {(r, f): Bool(f"TR_{r}_{label(f)}") for r in reqs for f in codes}

    # --- FACTS: a row marked 1 is TRUE, every pair not listed is FALSE ----
    #     (closed-world assumption: what the dataset does not say is false)
    rd_set, dc_set, rc_set = set(ds.req_design), set(ds.design_code), set(ds.req_code)
    facts = []
    facts += [v if k in rd_set else Not(v) for k, v in RD.items()]
    facts += [v if k in dc_set else Not(v) for k, v in DC.items()]
    facts += [v if k in rc_set else Not(v) for k, v in RC.items()]

    # --- RULE: TR(r,f) <-> OR_d ( RD(r,d) AND DC(d,f) ) --------------------
    rules = [TR[(r, f)] == Or([And(RD[(r, d)], DC[(d, f)]) for d in designs])
             for r in reqs for f in codes]

    return dict(reqs=reqs, designs=designs, codes=codes,
                RD=RD, DC=DC, RC=RC, TR=TR, facts=facts, rules=rules)


def make_solver(m, with_facts=True):
    s = Solver()
    if with_facts:
        s.add(m["facts"])
    s.add(m["rules"])
    return s


def sets_from_z3(ds):
    """Ask Z3 for a model; return (derived, recorded) = the pairs whose TR / RC is true."""
    m = build(ds)
    s = make_solver(m)
    assert s.check() == sat
    model = s.model()
    true_pairs = lambda D: {k for k, v in D.items()
                            if is_true(model.eval(v, model_completion=True))}
    return true_pairs(m["TR"]), true_pairs(m["RC"])


# ----------------------------------------------------------------------------
# demo / report
# ----------------------------------------------------------------------------
def section(title):
    print(f"\n=== {title} ===")


def main():
    ds = load_dataset()
    m = build(ds)
    reqs, codes, TR, RC, RD, DC = m["reqs"], m["codes"], m["TR"], m["RC"], m["RD"], m["DC"]
    expected = derive_traces(ds)                       # independent Python answer

    s = make_solver(m)

    section("0. SIZE OF THE PROPOSITIONAL MODEL")
    print(f"  Boolean variables : {len(RD) + len(DC) + len(RC) + len(TR)}")
    print(f"    RD {len(RD)} | DC {len(DC)} | RC {len(RC)} | TR {len(TR)}")
    print(f"  fact clauses      : {len(m['facts'])}")
    print(f"  rule formulas     : {len(m['rules'])}")

    section("1. IS THE MODEL CONSISTENT?")
    res = s.check()
    print(f"  solver.check() = {res}   (sat = no contradiction in facts + rules)")

    model = s.model()
    val = lambda v: is_true(model.eval(v, model_completion=True))
    derived = {k for k, v in TR.items() if val(v)}
    recorded = {k for k, v in RC.items() if val(v)}
    print(f"  derived traces (TR true)  : {len(derived)}")
    print(f"  recorded traces (RC true) : {len(recorded)}")
    print(f"  Python oracle says        : {len(expected)}  ->  "
          f"{'MATCH' if derived == expected else 'MISMATCH'}")

    section("2. PER-REQUIREMENT TRACEABILITY  (proved with entailment queries)")
    print(f"  {'req':<6}{'has design link':<18}{'has derived trace to code'}")
    for r in reqs:
        has_design, _ = entails(s, Or([RD[(r, d)] for d in m["designs"]]))
        has_trace, _ = entails(s, Or([TR[(r, f)] for f in codes]))
        print(f"  {r:<6}{'yes' if has_design else 'NO':<18}{'yes' if has_trace else 'NO'}")

    section("3. PROVE / REFUTE STATEMENTS")
    # 3a: a statement that IS true
    proved, _ = entails(s, Not(Or([TR[("fr06", f)] for f in codes])))
    print(f"  'FR06 has no derived trace to any file'           -> "
          f"{'PROVED' if proved else 'REFUTED'}")

    # 3b: derived ⊆ recorded   (every TR implies RC)
    subset = And([Implies(TR[k], RC[k]) for k in TR])
    proved, cex = entails(s, subset)
    print(f"  'every derived trace is also recorded'            -> "
          f"{'PROVED' if proved else 'REFUTED'}")
    if cex is not None:
        bad = sorted(k for k in TR if is_true(cex.eval(TR[k], model_completion=True))
                     and not is_true(cex.eval(RC[k], model_completion=True)))
        for r, f in bad:
            print(f"        counter-example: {r} -> {f}")

    # 3c: recorded ⊆ derived   (every RC implies TR)
    superset = And([Implies(RC[k], TR[k]) for k in TR])
    proved, cex = entails(s, superset)
    print(f"  'every recorded trace is explained by the design' -> "
          f"{'PROVED' if proved else 'REFUTED'}")
    if cex is not None:
        bad = sorted(k for k in RC if is_true(cex.eval(RC[k], model_completion=True))
                     and not is_true(cex.eval(TR[k], model_completion=True)))
        print(f"        {len(bad)} recorded traces have no design chain, e.g.:")
        for r, f in bad[:5]:
            print(f"        counter-example: {r} -> {f}")

    section("4. WHAT-IF  (open world: no 'everything else is false' facts)")
    # Keep only the RULES (no negative facts) and ADD a hypothesis.
    what_if = make_solver(m, with_facts=False)
    f_ctrl = "app/Http/Controllers/ScheduleController.php"
    what_if.add(RD[("fr06", "c_schedule")], DC[("c_schedule", f_ctrl)])
    proved, _ = entails(what_if, TR[("fr06", f_ctrl)])
    print("  IF  RD(fr06, c_schedule)  AND  DC(c_schedule, ScheduleController)")
    print(f"  THEN TR(fr06, ScheduleController) follows?  -> {'PROVED' if proved else 'NOT proved'}")
    proved, _ = entails(what_if, TR[("fr06", "app/Models/User.php")])
    print("  ... and does TR(fr06, User.php) follow from the same hypothesis?  -> "
          f"{'PROVED' if proved else 'NOT proved (nothing forces it)'}")

    section("5. DATA WARNINGS (same as the Prolog side)")
    for w in data_quality_report(ds):
        print("  -", w)


if __name__ == "__main__":
    main()
