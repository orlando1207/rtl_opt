# Validation of the initial reconstruction

Validated on branch `ROVER_reconstruct` in the `rover` Conda environment.

## Correctness checks

The initial suite contains 64 passing tests. Tests cover:

- ILP agreement with independent exhaustive enumeration on 20 small randomly
  generated graphs with cycles and repeated dependencies.
- Joint output selection that chooses a globally useful shared child even though
  separate greedy decisions avoid it.
- Zero-cost cycle rejection, repeated operands, output aliases, and invalid costs.
- Modular arithmetic widths 1–4, constant multiplication boundaries through 64 bits,
  oversized shift amounts, and preservation of discarded carry.
- Every explored e-node, including nonselected alternatives, checked against its
  e-class representative using independent SMT semantics on small-width examples.
- Slang elaboration, parameters, net initializers, casts, slices, replication,
  reductions, signed comparisons, and arithmetic shifts.
- Original RTL vs roundtrip RTL and optimized RTL via independent Yosys SAT.
- Command-line artifacts, replayable proof chains, preservation of existing runs,
  and refusal to publish candidates after inconclusive verification.

These tests are evidence for the implementation, not a universal formal proof of
the frontend or every arbitrary-width rule instance.

## Demonstration runs

| Example | Original proxy cost | Extracted proxy cost | CBC status | Z3 / Yosys |
| --- | ---: | ---: | --- | --- |
| 4-bit factoring |199 |114 |Optimal |Both proved |
| 8-bit mux-controlled multiplier |754 |389 |Optimal |Both proved |
| 8-bit MCM(3,7,21) |327 |223 |Optimal |Both proved |
| 16-bit-output 3-tap FIR |913 |660 |Feasible, optimum unproven |Both proved; RTL chain also proved |

The ILP objectives above use `reconstructed_gate_proxy_v1`. They are not standard
cell area or physical timing measurements. A reconstruction does not need to
match the original paper's percentages to demonstrate the same mechanisms.

The FIR search reached the eight-iteration limit with 299 data e-classes and
2,827 data e-nodes. CBC returned a feasible incumbent after approximately 118
seconds under the 120-second budget. Optimality was not proved. All 31 RTL
equivalence checks in its generated decomposition chain passed.

Yosys generic synthesis was also run on original and optimized MCM RTL with the
same installed backend. Final generic cell counts were 107 and 88, respectively.
This is a gate-count comparison without Liberty mapping or timing constraints;
it cannot establish a physical area or delay improvement.

An 8-bit distributive factoring trial obtained an optimal proxy objective of 426
versus 791 for the original, and Z3 proved IR equivalence. Direct Yosys SAT reached
the 60-second timeout. The output directory retained `candidate.sv` and an
inconclusive report, and did not contain `optimized.sv`. This motivates the
replayable decomposition interface and future commercial equivalence integration;
decomposition is not guaranteed to solve every arithmetic proof.

## Reproduce

```bash
conda activate rover
cargo build --release --locked
pytest -q
rover optimize examples/factor_small.sv --output-dir build/check-factor --explain
rover optimize examples/mux_mul.sv --output-dir build/check-mux --explain
rover optimize examples/mcm.sv --output-dir build/check-mcm --proof-chain
rover verify-chain build/check-mcm/proof-chain/manifest.json
rover synth examples/mcm.sv --output-dir build/check-synth-original
rover synth build/check-mcm/optimized.sv --output-dir build/check-synth-optimized
```

Use fresh output directories; the CLI never overwrites an existing experiment.
Generated artifacts under `build/` are ignored by Git. Environment specifications,
Cargo lockfile, source, examples, tests, and this report are repository files.
