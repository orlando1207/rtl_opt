# ROVER reconstruction

A working first-stage reconstruction of **ROVER: RTL Optimization via Verified
E-Graph Rewriting**, TCAD 2024, DOI 10.1109/TCAD.2024.3410154. It targets the
original combinational area-optimization flow and sharing-aware ILP extraction.
This is a restricted reconstruction, not the authors' implementation or a
reproduction of their TSMC 5-nm numerical results.

## Setup

The `rover` Conda environment has been created on this machine. From this checkout:

```bash
conda activate rover
cargo build --release --locked
rover doctor
pytest -q
```

On another Linux machine, create the environment first:

```bash
conda env create -f environment.yml
conda activate rover
cargo build --release --locked
```

`environment.lock.yml` records the installed Linux package versions without a
machine-specific prefix. It can be used instead of `environment.yml`. Rust
dependencies are recorded in `Cargo.lock`. The Python package is installed in
editable mode, so Python changes take effect immediately; Rust changes require
rebuilding. The Rust executable can be overridden with `ROVER_EGRAPH_BIN`.

## Optimize and verify RTL

```bash
rover optimize examples/mcm.sv --output-dir build/mcm-run --explain
rover optimize examples/mux_mul.sv --output-dir build/mux-run
rover optimize examples/factor_small.sv --output-dir build/factor-run
```

Each run requires a new or empty output directory. Artifacts include:

| File | Contents |
| --- | --- |
| `original.sv` | Snapshot of the input RTL |
| `input.ir.json` | Explicit-width IR after Slang elaboration |
| `egraph.json` | Explored e-classes, e-nodes, output roots, rule list |
| `extraction.lp` | CBC/PuLP ILP, including acyclicity constraints |
| `selected.json` | One selected implementation per reachable e-class |
| `candidate.sv` | Generated implementation, possibly unverified |
| `optimized.sv` | Published only after formal verification succeeds |
| `report.json` | Configuration, versions, proxy costs, limits, solver and proof statuses |
| `equivalence.log` | Independent RTL-level Yosys verification log |
| `explanations.json` | Optional egg rewrite explanations |

Both Z3 IR equivalence and independent RTL-level Yosys equivalence must pass.
If `--proof-chain` is requested, a fully checked decomposition can establish
equivalence when a direct check is inconclusive. A timeout never counts as proof.
Exit codes are 0 for verified output, 2 for inconclusive/failed verification,
and 1 for input, configuration, or tool errors.

```bash
rover optimize examples/mcm.sv --output-dir build/mcm-chain --proof-chain
rover verify-chain build/mcm-chain/proof-chain/manifest.json
```

The chain includes original RTL → normalized RTL → rewrite intermediates →
extracted candidate, with separate Yosys checks and logs. `--explain` alone only
generates an egg trace; it does not turn that trace into an independent proof.
Explanation generation reruns the search, so a time-limited search can fail to
reproduce a target. This is recorded, and cannot grant verification status.

## Rewriting and extraction controls

```bash
# Compare the tree-cost greedy extractor with the global DAG ILP.
rover optimize examples/mcm.sv --extractor greedy --output-dir build/mcm-greedy

# Disable operator merging for an ablation.
rover optimize examples/mcm.sv --groups arithmetic,logic,exchange,constants --output-dir build/no-merge

# RTL roundtrip / no-rewrite baseline.
rover optimize examples/truncation.sv --groups '' --output-dir build/roundtrip
```

Available families: `arithmetic`, `logic`, `exchange`, `merge`, `constants`.
There are initially 40 registered directed rules, counting reverse directions.
Constant folding is an additional e-class analysis.
`--iterations`, `--node-limit`, `--seconds`, `--ilp-timeout`, and
`--verify-timeout` control resource budgets. The default ILP limit is 120 seconds,
matching the original paper's experimental extraction budget.

The objective is a reconstructed gate-count proxy. It includes width-sensitive
arithmetic, constant multiplication, constant versus variable shifts, and SUM/FMA
clustering. **A reduction in this objective is not a measured silicon area reduction.**

## Synthesis

```bash
rover synth examples/mcm.sv --output-dir build/synth-original
rover synth build/mcm-run/optimized.sv --output-dir build/synth-optimized

# Optional standard-cell mapping using a library you have access to.
rover synth build/mcm-run/optimized.sv --liberty /absolute/path/cells.lib --output-dir build/synth-mapped
```

Without Liberty, synthesis reports generic gate counts. With Liberty, the log
contains mapped cell area. This interface does not perform signoff timing analysis
or reproduce the paper's commercial datapath-clustering backend.

## Supported RTL contract

- One flat combinational module, continuous assignments and net initializers.
- Packed integral signals of 1–64 bits; parameters use their elaborated defaults.
- Arithmetic, bitwise operations and reductions, logical operations, comparisons,
  shifts, muxes, constant slices/bit selects, concatenation, replication, integer
  casts, `$signed`, and `$unsigned`.
- Exact two-state bitvector semantics, explicit extension/truncation boundaries,
  signed comparisons and arithmetic right shifts.
- Whole-signal assignment targets; ordinary Verilog identifiers. Selected vectors
  must use descending `[width-1:0]` indexing.

Procedural blocks, registers/latches, hierarchy, memories, multiple drivers,
combinational cycles, X/Z constants, variable selects, division/modulus/power,
timing controls, and arbitrary function calls are rejected. Four-state behavior
and reset/initial-state semantics are outside this baseline's contract. Widths
are preserved across source boundaries; rewrites never assume discarded carries
can be recovered.

`examples/factor.sv` is an intentionally harder 8-bit arithmetic equivalence
case. Z3 proved the first trial, but direct Yosys SAT exceeded 60 seconds; that
candidate was not published. `factor_small.sv` is the verified 4-bit demonstration.

## Development references

- [Paper-to-code mapping, ILP formulation, and extension procedure](docs/reproduction.md)
- [Required tool/library/benchmark access](docs/resources.md)
- [Measured implementation validation](docs/validation.md)

No constraint-aware ASSUME rewriting, delay-constrained extraction, power
optimization, or LLM rule generation is included in this first-stage baseline.
