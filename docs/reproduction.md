# Original ROVER: implementation mapping

Primary source: `reference/ROVER_RTL_Optimization_via_Verified_E-Graph_Rewriting.pdf`.
PDF page numbers below refer to the supplied 14-page journal paper.

## Components

| Paper component | Implementation | Fidelity |
| --- | --- | --- |
| Slang parsing/elaboration, §III pp.4–5 | `rover/frontend.py`, pinned pyslang 9.1.0 | Same frontend family; Python AST binding rather than JSON export |
| VeriLang width/sign semantics | `rover/ir.py`, Rust `Bits` analysis | Explicit bitvector IR; signedness normalized into casts/operators rather than operand triples |
| egg equality saturation, §II/IV | `rust/main.rs`, pinned egg 0.11.0 | Reused e-graph library, conditional width structure and dynamic constants |
| Table II arithmetic identities | `rules()` arithmetic family | Restricted equal-width modular rules |
| Logical simplifications | logic family | Initial general subset |
| Arithmetic–logic exchange | exchange family | Mux/add, mux/mul, left-shift interchange |
| Operator merging | merge family | Three-input SUM and FMA; no MUXAR yet |
| Constant expansion | `ExpandConstant` applier | Power-of-two and floor/ceiling power decomposition |
| Constant folding | Rust `Bits::modify` | E-class analysis with constant and width union checks |
| Gate-count model, §V-A | `rover/cost.py` | Reconstructed approximation, not original formulas |
| Sharing-aware ILP, §V-B equations20–23 | `rover/extract.py` | Global multi-output DAG selection with explicit class activity and bounded ranks |
| Code generation, §V-C | `rover/backend.py` | One wire per shared extracted expression |
| Verification decomposition, §VI | `rover/proof.py`, `--proof-chain` | Intermediate RTL and replayable independent checks; simpler than commercial signal lemmas |
| Commercial formal checker | Z3 bitvectors + Yosys SAT | Open-source substitution; arithmetic scalability differs |
| Experimental synthesis | `rover synth` | Yosys, optionally Liberty; not TSMC5 commercial reproduction |

## Bitvector correctness

Every arithmetic operation produces the low W bits. Inputs to arithmetic nodes
are first explicitly resized to W, using the source/elaborated signedness. Signed
operators act on the same bit patterns with a two's-complement interpretation.
Constants and shift amounts are represented with their own widths. Oversized
logical shifts return zero; oversized arithmetic right shifts return the sign mask.

E-class facts record output width and optional constant value. A union of
inconsistent widths or constants aborts. Arithmetic reassociation patterns match
the same width at both operators, so they cannot cross a source truncation node.
The presence of wider or signed RTL does not permit unrestricted mixed-width
rewrites. These cases are normalized and their semantic boundaries retained.

The two-state contract is intentional. Supporting unknown-value propagation
requires a different equivalence relation and rule set.

## ILP formulation

Let x_n indicate whether e-node n is implemented, y_c indicate whether e-class c
is active, and t_c be an integer topological rank. Let C(n) be n's containing
class, N_c its alternatives, and K the number of classes.

Minimize:

```text
sum_n area(n) * x_n
```

Subject to:

```text
sum_{n in N_c} x_n = y_c                 for every class c
y_c = 1                                for each distinct output class
x_n <= y_k                             for every selected-node dependency n -> k
0 <= t_c <= K-1                        for every class c
t_C(n) >= t_k + 1 - K*(1-x_n)           for every dependency n -> k
x_n, y_c binary; t_c integer
```

This strengthens the paper's child-closure formulation with explicit one-node
selection in every active class. Shared child classes are charged once even if
used by several nodes or outputs. Constant and width metadata are not hardware
and are excluded from the exported extraction graph.

Rank bounds are essential: they make the big-M constraint inactive for unselected
nodes and prohibit selected cycles. These bounds and constraints are tested against
an independent exhaustive oracle on small randomly generated cyclic graphs.

CBC is run with one thread and zero relative gap. The report distinguishes a
proven optimum from an integer feasible incumbent. No feasible incumbent means
failure; a timeout never silently triggers a different extractor. Reachability and
acyclicity are checked again after extraction. Optimality concerns this graph and
proxy objective only, not all possible RTL implementations or mapped circuit area.

The optional greedy extractor minimizes tree cost and uses expression height as
a tie breaker to avoid zero-cost cycles. Its returned DAG cost is reported
separately from its tree objective. This is an ablation, not the default baseline.

## Cost reconstruction

The original paper identifies architecture choices and a gate-count objective,
but does not provide a complete executable costing specification. Current formulas
are deliberately explicit and replaceable:

- Approximate carry-propagate adder cost `8W-3`, lower bounded by one.
- Three-input SUM adds a compressor row to one carry-propagate adder.
- Multiplication estimates partial products, compression, and final addition.
- Constant multiplier row counts use coefficient popcount; power-of-two products
  are wiring. No claim of exact canonical-signed-digit mapping is made.
- FMA models an extra compression row rather than two independent datapaths.
- Slices, extensions, concatenations, constants, and constant shifts are wiring.
- Variable shifts account for selector width and out-of-range behavior.

Before interpreting post-synthesis improvements, calibrate these assumptions
against the chosen backend. Yosys and commercial arithmetic extraction may expose
different benefits. SUM/FMA are emitted as behavioral expressions, so the backend
must recognize their intended clustering for model correlation.

## Adding rules

1. Specify exact bitvector LHS/RHS semantics and supported widths/sign conditions.
2. Add an independently checked representative case and an adversarial boundary
   case to `tests/test_semantics.py`. If the rule changes graph sharing, include an
   extraction test. Preserve tests for nonselected alternatives as well.
3. Register the rule in an appropriate family in Rust `rules()`. Shared `?w`
   annotations enforce the initial equal-width precondition. Add a conditional
   applier for semantic guards that cannot be encoded structurally.
4. For a new operator, implement Rust analysis/export, IR frontend as needed,
   SystemVerilog generation, independent SMT semantics, and a cost model.
5. Build, run the regression suite, and compare both proxy and synthesized results.
6. Retain formal checking before candidate publication.

Future rule proposals should not be accepted merely because they look algebraic
or improve the proxy objective. Subtraction, right-shift interchange, truncation,
and signed-width changes need explicit validity conditions.

## Deferred original features

The automated decision-tree condition synthesis of §IV-B is not implemented.
Its width 1–8 enumeration and extrapolation assumption are separate from the current
conservative guards. Also deferred: complete Table II coverage, MUXAR merged
multiplier arrays, arbitrary widths beyond 64, broader procedural/hierarchical RTL,
original signal-name preservation, and commercial-checker-specific signal lemmas.

Reconstructing these features can be done incrementally without replacing the
IR, e-graph engine, or ILP interface. The later ASSUME, delay, and power papers
remain out of scope for this baseline.
