"""Explicit, two-state bitvector IR. Every arithmetic node is modulo 2**width."""
from dataclasses import dataclass
from functools import lru_cache
import re


@dataclass(frozen=True)
class Expr:
    op: str
    width: int
    args: tuple["Expr", ...] = ()
    value: int | None = None
    name: str | None = None
    offset: int = 0

    def __post_init__(self):
        if not 1 <= self.width <= 64:
            raise ValueError(f"Only widths 1..64 are supported, got {self.width}")

    def sexpr(self):
        if self.op == "const":
            return f"(bv {self.width} {self.value})"
        if self.op == "var":
            return f"(var {self.width} {self.name})"
        tail = " ".join(a.sexpr() for a in self.args)
        if self.op == "slice":
            tail += f" {self.offset}"
        return f"({self.op} {self.width} {tail})"

    def to_dict(self):
        d = {"op": self.op, "width": self.width, "args": [a.to_dict() for a in self.args]}
        if self.value is not None: d["value"] = self.value
        if self.name is not None: d["name"] = self.name
        if self.op == "slice": d["offset"] = self.offset
        return d


def const(width, value):
    return Expr("const", width, value=value & ((1 << width) - 1))


def resize(a, width, signed=False):
    if a.width == width: return a
    if a.width > width: return Expr("slice", width, (a,))
    return Expr("sext" if signed else "zext", width, (a,))


def truth(a):
    if a.width == 1: return a
    return Expr("not", 1, (Expr("eq", 1, (a, const(a.width, 0))),))


def validate_identifier(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", name):
        raise ValueError(f"Unsupported identifier {name!r}; use ordinary Verilog identifiers")


@dataclass
class Design:
    name: str
    inputs: dict[str, int]
    outputs: dict[str, Expr]

    def to_dict(self):
        return {"name": self.name, "inputs": self.inputs,
                "outputs": {k: e.to_dict() for k, e in self.outputs.items()}}


def expressions_from_selection(graph, selected):
    @lru_cache(None)
    def build(cid):
        n = selected[cid]
        return Expr(n["op"], n["width"], tuple(build(c) for c in n["args"]),
                    n.get("value"), n.get("name"), n.get("offset", 0))
    return {name: build(cid) for name, cid in graph["roots"].items()}
