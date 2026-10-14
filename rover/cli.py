"""Artifact-producing optimization flow; unverified candidates are never published."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import importlib.metadata
import hashlib
from .backend import emit_verilog
from .engine import saturate, DEFAULT_GROUPS
from .extract import extract
from .frontend import read_verilog
from .ir import expressions_from_selection, validate_identifier
from .verify import verify_ir, verify_rtl, quote_yosys
from .proof import generate_chain, replay_chain


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def optimize(args):
    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()): raise ValueError("Output directory must be empty to preserve prior experiments")
    design = read_verilog(args.input, args.top)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.input,out / "original.sv")
    groups = args.groups.split(",") if args.groups else []
    dump(out / "input.ir.json", design.to_dict())
    graph = saturate(design, groups, args.iterations, args.node_limit, args.seconds)
    dump(out / "egraph.json", graph)
    selected, extraction = extract(graph, args.extractor, args.ilp_timeout, out / "extraction.lp" if args.extractor == "ilp" else None)
    outputs = expressions_from_selection(graph, selected)
    candidate = out / "candidate.sv"
    candidate.write_text(emit_verilog(design, outputs))
    ir_proof = verify_ir(design, outputs, args.verify_timeout * 1000)
    rtl_proof = verify_rtl(args.input, candidate, design.name, args.verify_timeout)
    rtl_log = rtl_proof.pop("log", "")
    (out / "equivalence.log").write_text(rtl_log)
    verified = ir_proof["status"] == "proved" and rtl_proof["status"] == "proved"
    dump(out / "selected.json", {str(c): n for c, n in selected.items()})
    base_graph = saturate(design, [], 0, args.node_limit, args.seconds)
    _, baseline = extract(base_graph, "ilp", args.ilp_timeout)
    report = {"input": str(Path(args.input).resolve()), "module": design.name,
              "configuration": {k: v for k, v in vars(args).items() if k != "func"},
              "saturation": graph["stats"], "rule_names": graph["rule_names"], "extraction": extraction,
              "baseline_proxy_area": baseline["objective"], "optimized_proxy_area": extraction["objective"],
              "verification": {"ir": ir_proof, "rtl": rtl_proof}, "verified": verified,
              "cost_model": "reconstructed_gate_proxy_v1; not mapped cell area"}
    report["versions"] = {name: importlib.metadata.version(name) for name in ["rover-rtl", "pyslang", "pulp", "z3-solver"]}
    report["python"] = sys.version
    report["input_sha256"] = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
    if args.explain or getattr(args, "proof_chain", False):
        # Rerun deterministically with time budget large enough to reach the same iteration stop.
        try:
            explanations = saturate(design, groups, args.iterations, args.node_limit, args.seconds, outputs)["explanations"]
            dump(out / "explanations.json", explanations)
            report["explanation_status"] = "generated_egg_trace_not_independent_certificate"
            if getattr(args, "proof_chain", False):
                chain = generate_chain(design,args.input,candidate,outputs,explanations,out / "proof-chain",args.verify_timeout)
                report["verification"]["chain"] = chain
                verified = ((ir_proof["status"] == "proved" or chain["ir_status"] == "proved")
                            and (rtl_proof["status"] == "proved" or chain["status"] == "proved")
                            and ir_proof["status"] != "failed" and rtl_proof["status"] != "failed")
                report["verified"] = verified
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            report["explanation_status"] = f"unavailable: {e}"
    if verified:
        shutil.copyfile(candidate, out / "optimized.sv")
    dump(out / "report.json", report)
    print(json.dumps({"verified": verified, "baseline_proxy_area": baseline["objective"],
                      "optimized_proxy_area": extraction["objective"], "ilp_status": extraction["status"],
                      "artifacts": str(out)}, indent=2))
    return 0 if verified else 2


def synthesize(args):
    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()): raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    top = args.top or read_verilog(args.input).name
    validate_identifier(top)
    commands = [f"read_verilog -sv {quote_yosys(args.input)}", f"synth -top {top}"]
    if args.liberty:
        commands += [f"dfflibmap -liberty {quote_yosys(args.liberty)}", f"abc -liberty {quote_yosys(args.liberty)}"]
    commands += [f"write_verilog {quote_yosys(out / 'netlist.v')}",
                 "stat" + (f" -liberty {quote_yosys(args.liberty)}" if args.liberty else "")]
    result = subprocess.run(["yosys", "-Q", "-T", "-p", "; ".join(commands)], capture_output=True, text=True, timeout=args.timeout)
    (out / "synthesis.log").write_text(result.stdout + result.stderr)
    if result.returncode: raise RuntimeError("Synthesis failed; see synthesis.log")
    print(f"Synthesis artifacts: {out}; " + ("library-mapped area in synthesis.log" if args.liberty else "generic gate counts only; no physical area/delay claim"))
    return 0


def doctor(args):
    print(json.dumps({"python": sys.executable,
                      "tools": {t: shutil.which(t) for t in ["cargo", "rustc", "cbc", "yosys", "iverilog"]}}, indent=2))
    return 0


def check_chain(args):
    result = replay_chain(args.manifest,args.timeout)
    print(json.dumps({"status":result["status"], "checks":len(result["edges"])},indent=2))
    return 0 if result["status"] == "proved" else 2


def main():
    parser = argparse.ArgumentParser(description="Original ROVER reconstruction: verified combinational RTL rewriting + DAG ILP")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("optimize")
    p.add_argument("input"); p.add_argument("--top"); p.add_argument("--output-dir", required=True)
    p.add_argument("--groups", default=",".join(DEFAULT_GROUPS), help="Comma separated rule families; empty disables rewrites")
    p.add_argument("--extractor", choices=["ilp", "greedy"], default="ilp")
    p.add_argument("--iterations", type=int, default=8); p.add_argument("--node-limit", type=int, default=20000)
    p.add_argument("--seconds", type=int, default=10); p.add_argument("--ilp-timeout", type=int, default=120)
    p.add_argument("--verify-timeout", type=int, default=60); p.add_argument("--explain", action="store_true")
    p.add_argument("--proof-chain", action="store_true", help="Generate and independently check intermediate RTL equivalences")
    p.set_defaults(func=optimize)
    p = sub.add_parser("synth")
    p.add_argument("input"); p.add_argument("--top"); p.add_argument("--liberty"); p.add_argument("--output-dir", required=True)
    p.add_argument("--timeout", type=int, default=120); p.set_defaults(func=synthesize)
    p = sub.add_parser("doctor"); p.set_defaults(func=doctor)
    p = sub.add_parser("verify-chain")
    p.add_argument("manifest"); p.add_argument("--timeout",type=int,default=60); p.set_defaults(func=check_chain)
    args = parser.parse_args()
    try: return args.func(args)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print(f"rover: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
