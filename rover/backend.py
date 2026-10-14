"""Generate one wire per selected DAG node; shared hardware is emitted once."""
from .ir import validate_identifier


def emit_verilog(design, outputs=None, module_name=None):
    outputs = outputs or design.outputs
    name = module_name or design.name
    validate_identifier(name)
    ports = list(design.inputs) + list(outputs)
    for p in ports: validate_identifier(p)
    prefix = "rover_n"
    while any(p.startswith(prefix) for p in ports): prefix += "_"
    lines = [f"module {name}({', '.join(ports)});"]
    lines += [f"  input wire [{w-1}:0] {p};" for p, w in design.inputs.items()]
    lines += [f"  output wire [{e.width-1}:0] {p};" for p, e in outputs.items()]
    memo = {}

    def emit(e):
        if e in memo: return memo[e]
        if e.op == "var":
            if design.inputs.get(e.name) != e.width: raise ValueError("Input type mismatch")
            memo[e] = e.name; return e.name
        if e.op == "const":
            r = f"{e.width}'h{e.value:x}"; memo[e] = r; return r
        a = [emit(child) for child in e.args]
        binary = {"add": "+", "sub": "-", "mul": "*", "and": "&", "or": "|", "xor": "^",
                  "shl": "<<", "lshr": ">>", "eq": "==", "ult": "<"}
        if e.op in binary: expr = f"({a[0]} {binary[e.op]} {a[1]})"
        elif e.op == "ashr": expr = f"($signed({a[0]}) >>> {a[1]})"
        elif e.op == "slt": expr = f"($signed({a[0]}) < $signed({a[1]}))"
        elif e.op in ("not", "neg"): expr = f"({'~' if e.op == 'not' else '-'}{a[0]})"
        elif e.op == "mux": expr = f"({a[0]} ? {a[1]} : {a[2]})"
        elif e.op == "sum": expr = f"({a[0]} + {a[1]} + {a[2]})"
        elif e.op == "fma": expr = f"({a[0]} * {a[1]} + {a[2]})"
        elif e.op == "slice":
            # Sized cast avoids part-selecting a literal or arbitrary expression.
            expr = f"{e.width}'({a[0]} >> {e.offset})"
        elif e.op == "zext": expr = f"{e.width}'($unsigned({a[0]}))"
        elif e.op == "sext": expr = f"{e.width}'($signed({a[0]}))"
        elif e.op == "concat": expr = "{" + ", ".join(a) + "}"
        else: raise ValueError(f"Unsupported output operator {e.op}")
        wire = f"{prefix}{len(memo)}"
        lines.append(f"  wire [{e.width-1}:0] {wire};")
        lines.append(f"  assign {wire} = {expr};")
        memo[e] = wire; return wire

    for port, expr in outputs.items(): lines.append(f"  assign {port} = {emit(expr)};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"
