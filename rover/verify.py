"""Independent bitvector translation validation and RTL-level Yosys checking."""
from functools import lru_cache
from pathlib import Path
import subprocess
import z3


def symbolic(outputs, inputs):
    @lru_cache(None)
    def visit(e):
        if e.op == "var": return inputs[e.name]
        if e.op == "const": return z3.BitVecVal(e.value, e.width)
        a = [visit(c) for c in e.args]
        def bvbool(b): return z3.If(b, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))
        if e.op == "add": return a[0] + a[1]
        if e.op == "sub": return a[0] - a[1]
        if e.op == "mul": return a[0] * a[1]
        if e.op == "and": return a[0] & a[1]
        if e.op == "or": return a[0] | a[1]
        if e.op == "xor": return a[0] ^ a[1]
        if e.op == "not": return ~a[0]
        if e.op == "neg": return -a[0]
        if e.op in ("shl", "lshr", "ashr"):
            # Extend both operands so a wide shift amount cannot wrap on resize.
            sw = max(a[0].size(), a[1].size())
            amt = z3.ZeroExt(sw - a[1].size(), a[1])
            val = (z3.SignExt if e.op == "ashr" else z3.ZeroExt)(sw - a[0].size(), a[0])
            r = val << amt if e.op == "shl" else z3.LShR(val, amt) if e.op == "lshr" else val >> amt
            return z3.Extract(e.width-1, 0, r)
        if e.op == "eq": return bvbool(a[0] == a[1])
        if e.op == "ult": return bvbool(z3.ULT(a[0], a[1]))
        if e.op == "slt": return bvbool(a[0] < a[1])
        if e.op == "mux": return z3.If(a[0] != 0, a[1], a[2])
        if e.op == "sum": return a[0] + a[1] + a[2]
        if e.op == "fma": return a[0] * a[1] + a[2]
        if e.op == "zext": return z3.ZeroExt(e.width - a[0].size(), a[0])
        if e.op == "sext": return z3.SignExt(e.width - a[0].size(), a[0])
        if e.op == "slice": return z3.Extract(e.offset + e.width - 1, e.offset, a[0])
        if e.op == "concat": return z3.Concat(*a)
        raise ValueError(f"Unknown SMT operator {e.op}")
    return {name: visit(e) for name, e in outputs.items()}


def verify_ir(design, outputs, timeout_ms=30000):
    if set(outputs) != set(design.outputs): raise ValueError("Output interface mismatch")
    if any(outputs[n].width != design.outputs[n].width for n in outputs): raise ValueError("Output width mismatch")
    inputs = {name: z3.BitVec(name, w) for name, w in design.inputs.items()}
    lhs, rhs = symbolic(design.outputs, inputs), symbolic(outputs, inputs)
    solver = z3.Solver(); solver.set(timeout=timeout_ms)
    solver.add(z3.Or(*(lhs[n] != rhs[n] for n in lhs)))
    result = solver.check()
    if result == z3.unsat: return {"status": "proved", "engine": "z3-bitvectors"}
    if result == z3.unknown: return {"status": "inconclusive", "engine": "z3-bitvectors", "reason": solver.reason_unknown()}
    model = solver.model()
    return {"status": "failed", "engine": "z3-bitvectors",
            "counterexample": {n: model.eval(v, model_completion=True).as_long() for n, v in inputs.items()}}


def quote_yosys(path):
    text = str(Path(path).resolve())
    if '"' in text or "\n" in text: raise ValueError("Unsupported Yosys path")
    return '"' + text + '"'


def verify_rtl(original, optimized, top, timeout=60):
    # Stash isolated designs, then compare externally observable ports using SAT.
    commands = [f"read_verilog -sv {quote_yosys(original)}", f"prep -top {top}", f"rename {top} gold",
                "design -stash gold", "design -reset", f"read_verilog -sv {quote_yosys(optimized)}",
                f"prep -top {top}", f"rename {top} gate", "design -stash gate", "design -reset",
                "design -copy-from gold -as gold gold", "design -copy-from gate -as gate gate",
                "miter -equiv -flatten gold gate miter", "hierarchy -top miter", "proc", "opt",
                "sat -verify -prove trigger 0 -show-inputs -show-outputs miter"]
    try:
        result = subprocess.run(["yosys", "-Q", "-T", "-p", "; ".join(commands)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "inconclusive", "engine": "yosys-sat", "reason": "timeout"}
    except FileNotFoundError:
        return {"status": "inconclusive", "engine": "yosys-sat", "reason": "yosys unavailable"}
    if result.returncode == 0 and "SUCCESS" in result.stdout:
        return {"status": "proved", "engine": "yosys-sat", "log": result.stdout}
    status = "failed" if "proof did fail" in result.stderr else "inconclusive"
    return {"status": status, "engine": "yosys-sat", "log": result.stdout + result.stderr}
