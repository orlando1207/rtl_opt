"""Reconstructed gate-count proxy, not the original unpublished implementation."""
import math


def area(node, classes):
    op, w = node["op"], node["width"]
    constants = [classes[c].get("constant") for c in node["args"]]
    if op in ("var", "const", "slice", "concat", "zext", "sext"): return 0.0
    if op in ("shl", "lshr", "ashr"):
        if constants[1] is not None: return 0.0
        aw = classes[node["args"][1]]["width"]
        # Extra selector bits implement the out-of-range shift behavior.
        return float(3 * w * min(aw, math.ceil(math.log2(w)) + 1) + max(0, aw - math.ceil(math.log2(w)) - 1))
    if op in ("and", "or", "xor", "not"): return float(w * (2 if op == "xor" else 1))
    if op == "mux": return float(3 * w)
    if op in ("eq", "ult", "slt"):
        return float((3 if op == "eq" else 5) * classes[node["args"][0]]["width"])
    # Carry-propagate approximation plus partial-product/compressor estimate.
    adder = max(1, 8 * w - 3)
    if op in ("add", "sub", "neg"): return float(adder)
    if op == "sum": return float(adder + 5 * w)
    if op in ("mul", "fma"):
        rows = w
        for c in constants[:2]:
            if c is not None:
                if c == 0: return 0.0 if op == "mul" else float(adder)
                rows = min(rows, c.bit_count())
        # Constant power-of-two multiplication is wiring.
        if op == "mul" and rows == 1 and any(c is not None for c in constants): return 0.0
        return float(w * rows + 5 * w * max(0, rows - 2) + adder + (5 * w if op == "fma" else 0))
    raise ValueError(f"No cost model for {op}")
