# Resources and access to arrange

## Available now

The Conda environment `rover` includes Rust/Cargo, CBC, Yosys/ABC, Icarus Verilog,
Python/pytest, pyslang, PuLP, and Z3. These require no commercial registration.
Public upstreams:

- egg: https://github.com/egraphs-good/egg
- Slang: https://github.com/MikePopoloski/slang
- CBC: https://github.com/coin-or/Cbc
- Yosys: https://github.com/YosysHQ/yosys
- Z3: https://github.com/Z3Prover/z3
- extraction-gym, for later extractor comparisons: https://github.com/egraphs-good/extraction-gym

The implemented CLI handles generic synthesis and optional cell-library mapping.
It does not yet orchestrate a commercial synthesis server or static timing flow.

## User/group access needed for stronger reproduction

| Resource | What to arrange | Why |
| --- | --- | --- |
| Commercial logic synthesis | Confirm access to Synopsys Design Compiler or Cadence Genus through your lab/university, with relevant datapath optimization capability | Original ROVER models commercial arithmetic clustering |
| Commercial formal equivalence | Confirm access to an RTL equivalence tool, such as Formality or Conformal, and a server/license arrangement | Direct SAT can struggle with multiplier transformations |
| Standard-cell Liberty library | Obtain an authorized library, corners, and operating conditions; record provenance | Meaningful mapped area and timing comparisons |
| Static timing flow | Select a timing tool, constraints, loads, and input arrival assumptions | Current generic synthesis does not establish delay |
| Original ROVER artifact | Request source, full rewrite guards, area-cost functions, scripts, and tool versions from the authors if obtainable | Separates exact recovery from independent reconstruction |
| Original benchmarks | Request redistributable academic examples and identify which Intel examples are unavailable | Prevents calling reconstructed kernels the original benchmarks |

These examples of commercial products are implementation options, not a claim
that the paper discloses those specific vendors. No license server or proprietary
library has been configured in this checkout.

The paper's TSMC5 library is not bundled and cannot be substituted while claiming
the same numerical experiment. An open library can support a useful independent
evaluation, provided the library, backend, and constraints are identified.

The later constraint-aware paper references supplemental rewrites at
https://figshare.com/s/e3ab2850662d24991cbc. Availability and contents were not
verified because that URL was inaccessible through the browsing tool. It is not
a confirmed complete source release of original ROVER.

## Benchmarks to start with

Included examples are authored reconstruction kernels, not original artifact files:

- `factor_small.sv`: distributive factoring, 4-bit verified demonstration.
- `factor.sv`: 8-bit version exposing direct SAT scalability limitations.
- `mux_mul.sv`: sharing a multiplier across mutually exclusive branches.
- `mcm.sv`: jointly optimize 3x, 7x, 21x.
- `sum_fma.sv`: compressor/FMA costing and operator merging.
- `truncation.sv`: preserve discarded carry at an 8-bit intermediate.
- `signed.sv`: sign extension, arithmetic shift, and signed comparison.
- `fir3.sv`: a simple 3-tap constant-coefficient FIR; not the paper's variable-shift architecture sweep.

Next benchmark additions should include the other MCM sets from the original
paper, shifted FMA/multiplication, and a parameterized FIR architecture study.
Keep reconstructed examples separate from recovered author benchmarks and from
held-out examples for the eventual proposal.

For baseline comparisons, use identical frontend/backend versions, rewrite budgets,
ILP budgets, libraries, and constraints. Do not interpret independent minimum-area
and minimum-delay observations as one simultaneously achievable circuit point.
