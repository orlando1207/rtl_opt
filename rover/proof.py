"""Turn egg flat explanations into a replayable RTL equivalence chain."""
import json
from pathlib import Path
import re
from .ir import Expr, Design, const, validate_identifier
from .backend import emit_verilog
from .verify import verify_ir, verify_rtl


def parse_flat_term(text):
    tokens = re.findall(r"\(|\)|[^\s()]+", text)
    index = 0
    def parse():
        nonlocal index
        if index >= len(tokens): raise ValueError("Truncated explanation")
        token = tokens[index]; index += 1
        if token != "(": return token
        result = []
        while index < len(tokens) and tokens[index] != ")": result.append(parse())
        if index == len(tokens): raise ValueError("Unclosed explanation term")
        index += 1
        return result
    tree = parse()
    if index != len(tokens): raise ValueError("Trailing explanation tokens")
    def strip(t):
        if not isinstance(t, list): return t
        if t[0] in ("Rewrite=>", "Rewrite<="):
            if len(t) != 3: raise ValueError("Invalid rewrite annotation")
            return strip(t[2])
        return [strip(child) for child in t]
    def convert(t):
        if not isinstance(t, list) or len(t) < 3: raise ValueError("Invalid bitvector term")
        op, width = t[0], int(t[1])
        if op == "bv": return const(width, int(t[2]))
        if op == "var": return Expr("var", width, name=t[2])
        if op == "slice": return Expr(op, width, (convert(t[2]),), offset=int(t[3]))
        return Expr(op, width, tuple(convert(child) for child in t[2:]))
    return convert(strip(tree))


def replay_chain(manifest_path, timeout=60):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    validate_identifier(manifest["module"])
    edges = manifest["edges"]
    if (not edges or edges[0]["from"] != "original.sv" or edges[-1]["to"] != "candidate.sv"
            or any(a["to"] != b["from"] for a,b in zip(edges,edges[1:]))):
        raise ValueError("Proof manifest must connect original.sv to candidate.sv without gaps")
    for edge in edges:
        for field in ("from","to"):
            if Path(edge[field]).name != edge[field]: raise ValueError("Proof files must be local filenames")
    records = []
    for edge in edges:
        result = verify_rtl(manifest_path.parent / edge["from"], manifest_path.parent / edge["to"], manifest["module"], timeout)
        records.append({"from": edge["from"], "to": edge["to"], **result})
    status = "proved" if all(r["status"] == "proved" for r in records) else "failed" if any(r["status"] == "failed" for r in records) else "inconclusive"
    return {"status": status,
            "engine": "yosys-sat-chain", "edges": records}


def generate_chain(design, original, candidate, outputs, explanations, directory, timeout=60, limit=200):
    directory = Path(directory); directory.mkdir()
    (directory / "original.sv").write_text(Path(original).read_text())
    (directory / "candidate.sv").write_text(Path(candidate).read_text())
    current = dict(design.outputs)
    files = ["original.sv", "step0000.sv"]
    (directory / files[-1]).write_text(emit_verilog(design,current))
    ir_checks, number = [], 0
    for name in sorted(design.outputs):
        explanation = explanations[name]
        steps = [parse_flat_term(line) for line in explanation["egg_proof"].splitlines() if line.strip()]
        if not steps or steps[0] != current[name] or steps[-1] != outputs[name]:
            raise ValueError("Explanation endpoints do not match extracted design")
        for step in steps[1:]:
            if step == current[name]: continue
            number += 1
            if number > limit: raise ValueError(f"Proof chain exceeds {limit} intermediate steps")
            following = {**current, name:step}
            check = verify_ir(Design(design.name,design.inputs,current),following,timeout*1000)
            ir_checks.append({"step":number,"output":name,**check})
            current = following
            filename = f"step{number:04d}.sv"
            (directory / filename).write_text(emit_verilog(design,current)); files.append(filename)
    if current != outputs: raise ValueError("Incomplete proof chain")
    files.append("candidate.sv")
    manifest = {"module":design.name, "edges":[{"from":a,"to":b} for a,b in zip(files,files[1:])],
                "ir_checks":ir_checks, "ir_status":"proved" if all(c["status"] == "proved" for c in ir_checks) else "inconclusive"}
    path = directory / "manifest.json"; path.write_text(json.dumps(manifest,indent=2)+"\n")
    result = replay_chain(path,timeout)
    for i, check in enumerate(result["edges"]):
        log = check.pop("log", "")
        (directory / f"check{i:04d}.log").write_text(log)
    result["ir_status"] = manifest["ir_status"]
    (directory / "results.json").write_text(json.dumps(result,indent=2)+"\n")
    return result
