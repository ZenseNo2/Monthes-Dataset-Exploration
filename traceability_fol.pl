% ============================================================
% traceability_fol.pl  -  Software traceability with FIRST ORDER LOGIC
% ============================================================
%
% HOW TO RUN
%   swipl traceability_fol.pl          (then type:  ?- report.  )
%   swipl -q -s traceability_fol.pl -g report -t halt      (one shot)
%
% The FACTS come from traceability_data.pl (generated from ./dataset).
% This file contains only RULES and QUERIES.
%
% Predicates (all written  predicate(Arg1, Arg2, ...) ):
%   requirement(R, Text)     a requirement, e.g. fr01
%   design_class(D)          a design element, e.g. c_account
%   stereotype(D, Kind)      controller / model / view
%   code_file(F)             a source file
%   req_design(R, D)         recorded link  requirement -> design
%   design_code(D, F)        recorded link  design      -> code
%   req_code(R, F)           recorded link  requirement -> code  (ground truth)
%
% Prolog convention:  lower-case word = constant,  Capital word = variable.
% ============================================================

:- consult(traceability_data).


% ------------------------------------------------------------
% RULE 1  -  the core trace rule (indirect trace through design)
%
%   FOL:  forall r, d, f :
%           ReqDesign(r, d) AND DesignCode(d, f)  ->  DerivedTrace(r, f)
%
%   Prolog writes  "Head :- Body"  for  "Body -> Head",
%   and the comma means AND.  Variables are implicitly "for all".
% ------------------------------------------------------------
derived_trace(R, F) :-
    req_design(R, D),
    design_code(D, F).


% ------------------------------------------------------------
% RULE 2  -  compare the derived trace with the recorded req_code table
% ------------------------------------------------------------
% both sources agree
confirmed_trace(R, F) :- derived_trace(R, F), req_code(R, F).

% derived by the rule, but req-to-code.md does not list it
%   FOL:  DerivedTrace(r,f) AND NOT ReqCode(r,f)
derived_only(R, F) :- derived_trace(R, F), \+ req_code(R, F).

% listed in req-to-code.md, but the design chain cannot explain it
truth_only(R, F) :- req_code(R, F), \+ derived_trace(R, F).


% ------------------------------------------------------------
% RULE 3  -  gaps  (existential quantifier + negation)
%
%   FOL:  Requirement(r) AND NOT exists d . ReqDesign(r, d)
%   Prolog:  \+  means "cannot be proven" (negation as failure).
%   The "_" is an anonymous variable = "some d, I do not care which".
% ------------------------------------------------------------
requirement_without_design(R) :- requirement(R, _), \+ req_design(R, _).
requirement_without_code(R)   :- requirement(R, _), \+ req_code(R, _).
requirement_untraced(R)       :- requirement(R, _), \+ derived_trace(R, _).

design_without_code(D)        :- design_class(D), \+ design_code(D, _).
design_without_requirement(D) :- design_class(D), \+ req_design(_, D).

code_without_requirement(F)   :- code_file(F), \+ req_code(_, F).
code_without_design(F)        :- code_file(F), \+ design_code(_, F).

% items that are used in link tables but never declared in the plain lists
undeclared_design(D) :- design_class(D), \+ declared_design(D).
undeclared_code(F)   :- code_file(F),    \+ declared_code(F).


% ------------------------------------------------------------
% RULE 4  -  MVC layers  (uses the stereotype predicate)
% ------------------------------------------------------------
layer_of_requirement(R, Kind) :- req_design(R, D), stereotype(D, Kind).

% a requirement is "fully MVC" if it touches a controller AND a model AND a view
full_mvc(R) :-
    layer_of_requirement(R, controller),
    layer_of_requirement(R, model),
    layer_of_requirement(R, view).


% ------------------------------------------------------------
% RULE 5  -  UNIVERSAL statements
%
%   FOL:  forall r ( Requirement(r) -> exists f . ReqCode(r, f) )
%
%   Prolog has no direct "forall" in rules, so we use the equivalent
%       NOT exists r ( Requirement(r) AND NOT exists f . ReqCode(r,f) )
%   i.e. "there is no counter-example".  (De Morgan for quantifiers.)
% ------------------------------------------------------------
all_requirements_have_design :- \+ ( requirement(R, _), \+ req_design(R, _) ).
all_requirements_have_code   :- \+ ( requirement(R, _), \+ req_code(R, _) ).
derived_agrees_with_recorded :- \+ derived_only(_, _), \+ truth_only(_, _).


% ------------------------------------------------------------
% RULE 6  -  change-impact analysis (a practical use of traceability)
%   "If I change file F, which requirements are affected?"
% ------------------------------------------------------------
impacted_requirement(F, R) :- req_code(R, F).

impact(F) :-
    findall(R, impacted_requirement(F, R), L0), sort(L0, L),
    format("Changing ~w affects: ~w~n", [F, L]).


% ============================================================
% REPORT  (everything below is only printing)
% ============================================================
section(Title) :- format("~n=== ~w ===~n", [Title]).

% print each row with a format string; "(none)" if the list is empty
rows([], _) :- !, writeln('  (none)').
rows(Rows, Fmt) :- forall(member(Args, Rows), format(Fmt, Args)).

collect(Template, Goal, Sorted) :- findall(Template, Goal, L), sort(L, Sorted).

yes_no(Goal, Answer) :- ( call(Goal) -> Answer = yes ; Answer = no ).

derived_pairs(Pairs) :- findall(R-F, derived_trace(R, F), L), sort(L, Pairs).

count(Goal, Template, N) :- findall(Template, Goal, L), sort(L, S), length(S, N).

report :-
    section('1. COUNTS'),
    aggregate_all(count, requirement(_, _), NReq),
    count(derived_trace(R1, F1),  R1-F1, NDer),
    aggregate_all(count, req_code(_, _), NRec),
    count(confirmed_trace(R2, F2), R2-F2, NConf),
    count(derived_only(R3, F3),    R3-F3, NDO),
    count(truth_only(R4, F4),      R4-F4, NTO),
    format("  requirements                         : ~d~n", [NReq]),
    format("  derived traces (req->design->code)   : ~d~n", [NDer]),
    format("  recorded traces (req-to-code.md)     : ~d~n", [NRec]),
    format("  in both                              : ~d~n", [NConf]),
    format("  derived only (not in req-to-code)    : ~d~n", [NDO]),
    format("  recorded only (not explained)        : ~d~n", [NTO]),

    section('2. UNIVERSAL CHECKS  (forall ...)'),
    yes_no(all_requirements_have_design, A1),
    yes_no(all_requirements_have_code,   A2),
    yes_no(derived_agrees_with_recorded, A3),
    format("  every requirement has a design link  : ~w~n", [A1]),
    format("  every requirement has a code link    : ~w~n", [A2]),
    format("  derived == recorded                  : ~w~n", [A3]),

    section('3. REQUIREMENTS WITHOUT A DESIGN LINK'),
    collect([R5], requirement_without_design(R5), L5), rows(L5, "  ~w~n"),

    section('4. REQUIREMENTS WITHOUT A DERIVED TRACE TO CODE'),
    collect([R6], requirement_untraced(R6), L6), rows(L6, "  ~w~n"),

    section('5. DESIGN ELEMENTS WITHOUT A CODE LINK'),
    collect([D7], design_without_code(D7), L7), rows(L7, "  ~w~n"),

    section('6. CODE FILES WITHOUT ANY REQUIREMENT (recorded)'),
    collect([F8], code_without_requirement(F8), L8), rows(L8, "  ~w~n"),

    section('7. USED IN LINKS BUT NOT DECLARED IN THE PLAIN LISTS'),
    collect([D9], undeclared_design(D9), L9),  rows(L9,  "  design: ~w~n"),
    collect([F9], undeclared_code(F9),  L9b),  rows(L9b, "  code  : ~w~n"),

    section('8. DERIVED BUT NOT RECORDED  (derived_only)'),
    collect([R10, F10], derived_only(R10, F10), L10), rows(L10, "  ~w -> ~w~n"),

    section('9. RECORDED BUT NOT EXPLAINED BY DESIGN  (truth_only)'),
    collect([R11, F11], truth_only(R11, F11), L11), rows(L11, "  ~w -> ~w~n"),

    section('10. REQUIREMENTS THAT TOUCH CONTROLLER + MODEL + VIEW'),
    collect([R12], full_mvc(R12), L12), rows(L12, "  ~w~n"),

    section('11. CHANGE-IMPACT EXAMPLE'),
    impact('app/Models/Proposal.php').


% ------------------------------------------------------------
% Machine-readable dump, used by verify_all.py to cross-check
% Prolog against Z3 and against plain Python.
% ------------------------------------------------------------
% dump(Pred): print every  Req|File  pair of a two-argument predicate
dump(Pred) :-
    Goal =.. [Pred, R, F],
    findall(R-F, Goal, L0), sort(L0, L),
    forall(member(R1-F1, L), format("~w|~w~n", [R1, F1])).

dump_derived :- dump(derived_trace).
