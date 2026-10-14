from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUPS = ["arithmetic", "logic", "exchange", "merge", "constants"]


def saturate(design, groups=None, iterations=8, node_limit=20000, seconds=10, explain=None):
    binary = Path(os.environ.get("ROVER_EGRAPH_BIN", ROOT / "target/release/rover-egraph"))
    if not binary.is_file():
        raise RuntimeError("Build the engine first: conda run -n rover cargo build --release --locked")
    if iterations < 0 or node_limit <= 0 or seconds <= 0: raise ValueError("Invalid saturation limits")
    request = {"outputs": {n: e.sexpr() for n, e in design.outputs.items()},
               "groups": DEFAULT_GROUPS if groups is None else groups,
               "iterations": iterations, "node_limit": node_limit, "seconds": seconds}
    if explain is not None: request["explain"] = {n: e.sexpr() for n, e in explain.items()}
    result = subprocess.run([str(binary)], input=json.dumps(request), capture_output=True, text=True, timeout=seconds + 30)
    if result.returncode: raise RuntimeError("e-graph engine failed: " + result.stderr)
    return json.loads(result.stdout)
