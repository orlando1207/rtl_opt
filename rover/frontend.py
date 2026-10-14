"""Slang elaboration frontend for continuous-assignment combinational modules."""
from pathlib import Path
import pyslang as s
from .ir import Design, Expr, const, resize, truth, validate_identifier


def read_verilog(path, top=None):
    compilation = s.Compilation()
    compilation.addSyntaxTree(s.SyntaxTree.fromFile(str(Path(path).resolve())))
    root = compilation.getRoot()
    errors = [d for d in compilation.getAllDiagnostics() if d.isError()]
    if errors:
        raise ValueError("Slang elaboration errors: " + "; ".join(f"{d.code}: {list(d.args)}" for d in errors))
    tops = [t for t in root.topInstances if top is None or t.name == top]
    if len(tops) != 1:
        raise ValueError("Select exactly one root module using --top")
    body = tops[0].body
    validate_identifier(tops[0].name)
    inputs, outputs, assignments = {}, {}, {}
    for port in body.portList:
        validate_identifier(port.name)
        if not port.type.isSimpleBitVector:
            raise ValueError(f"Only scalar / packed bitvector ports supported: {port.name}")
        if port.direction == s.ArgumentDirection.In:
            inputs[port.name] = port.type.bitWidth
        elif port.direction == s.ArgumentDirection.Out:
            outputs[port.name] = port.type.bitWidth
        else:
            raise ValueError("Inout/ref ports are unsupported")
    for symbol in body:
        if symbol.kind == s.SymbolKind.ContinuousAssign:
            a = symbol.assignment
            if symbol.delay is not None or a.timingControl is not None:
                raise ValueError("Delayed assignments are unsupported")
            if a.left.kind != s.ExpressionKind.NamedValue:
                raise ValueError("Assignment targets must be whole signals")
            name = a.left.symbol.name
            if name in assignments or name in inputs:
                raise ValueError(f"Multiple drivers / input assignment: {name}")
            assignments[name] = a.right
        elif symbol.kind in (s.SymbolKind.ProceduralBlock, s.SymbolKind.Instance, s.SymbolKind.PrimitiveInstance):
            raise ValueError(f"Unsupported {symbol.kind}; use a flat combinational module with continuous assignments")
        elif symbol.kind == s.SymbolKind.Variable and symbol.initializer is not None:
            raise ValueError("Variable initialization is sequential state; use wire/assign")
        elif symbol.kind == s.SymbolKind.Net and symbol.initializer is not None:
            if symbol.name in assignments or symbol.name in inputs:
                raise ValueError(f"Multiple drivers / input assignment: {symbol.name}")
            assignments[symbol.name] = symbol.initializer
    memo, active = {}, set()

    def signal(name):
        if name in memo: return memo[name]
        if name in inputs:
            memo[name] = Expr("var", inputs[name], name=name)
        else:
            if name in active: raise ValueError(f"Combinational cycle at {name}")
            if name not in assignments: raise ValueError(f"Undriven signal {name}")
            active.add(name)
            memo[name] = convert(assignments[name])
            active.remove(name)
        return memo[name]

    def integer(e):
        a = convert(e)
        if a.op == "const": v = a.value
        else:
            from .verify import symbolic
            import z3
            try: value = z3.simplify(symbolic({"value": a}, {})["value"])
            except KeyError: raise ValueError("Select bounds must be compile-time constants") from None
            if not z3.is_bv_value(value): raise ValueError("Select bounds must be compile-time constants")
            v = value.as_long()
        if e.type.isSigned and v & (1 << (a.width - 1)): v -= 1 << a.width
        return v

    def convert(e):
        w, kind = e.type.bitWidth, e.kind
        if kind in (s.ExpressionKind.IntegerLiteral, s.ExpressionKind.UnbasedUnsizedIntegerLiteral):
            if e.value.hasUnknown: raise ValueError("X/Z constants are outside the two-state contract")
            return const(w, int(e.value))
        if kind == s.ExpressionKind.NamedValue:
            if e.symbol.kind == s.SymbolKind.Parameter:
                v = e.symbol.value
                if v.hasUnknown(): raise ValueError("Unknown parameter")
                return const(w, int(v.value))
            return signal(e.symbol.name)
        if kind == s.ExpressionKind.Conversion:
            return resize(convert(e.operand), w, e.operand.type.isSigned)
        if kind == s.ExpressionKind.Call:
            if e.isSystemCall and e.subroutineName in ("$signed", "$unsigned") and len(e.arguments) == 1:
                return resize(convert(e.arguments[0]), w, e.arguments[0].type.isSigned)
            raise ValueError(f"Unsupported function call {e.subroutineName}")
        if kind == s.ExpressionKind.UnaryOp:
            a, op = convert(e.operand), e.op
            if op == s.UnaryOperator.Plus: return resize(a, w, e.operand.type.isSigned)
            if op == s.UnaryOperator.LogicalNot: return Expr("not", 1, (truth(a),))
            if op in (s.UnaryOperator.Minus, s.UnaryOperator.BitwiseNot):
                return Expr("neg" if op == s.UnaryOperator.Minus else "not", w, (resize(a, w, e.operand.type.isSigned),))
            if op in (s.UnaryOperator.BitwiseOr, s.UnaryOperator.BitwiseNor):
                b = truth(a)
                return b if op == s.UnaryOperator.BitwiseOr else Expr("not", 1, (b,))
            if op in (s.UnaryOperator.BitwiseAnd, s.UnaryOperator.BitwiseNand):
                b = Expr("eq", 1, (a, const(a.width, (1 << a.width) - 1)))
                return b if op == s.UnaryOperator.BitwiseAnd else Expr("not", 1, (b,))
            if op in (s.UnaryOperator.BitwiseXor, s.UnaryOperator.BitwiseXnor):
                bits = [Expr("slice", 1, (a,), offset=i) for i in range(a.width)]
                b = bits[0]
                for bit in bits[1:]: b = Expr("xor", 1, (b, bit))
                return b if op == s.UnaryOperator.BitwiseXor else Expr("not", 1, (b,))
            raise ValueError(f"Unsupported unary operator {op}")
        if kind == s.ExpressionKind.BinaryOp:
            a, b, op = convert(e.left), convert(e.right), e.op
            arithmetic = {s.BinaryOperator.Add: "add", s.BinaryOperator.Subtract: "sub", s.BinaryOperator.Multiply: "mul",
                          s.BinaryOperator.BinaryAnd: "and", s.BinaryOperator.BinaryOr: "or", s.BinaryOperator.BinaryXor: "xor"}
            if op in arithmetic:
                return Expr(arithmetic[op], w, (resize(a, w, e.left.type.isSigned), resize(b, w, e.right.type.isSigned)))
            if op == s.BinaryOperator.BinaryXnor:
                return Expr("not", w, (Expr("xor", w, (resize(a,w,e.left.type.isSigned), resize(b,w,e.right.type.isSigned))),))
            shifts = {s.BinaryOperator.LogicalShiftLeft: "shl", s.BinaryOperator.ArithmeticShiftLeft: "shl",
                      s.BinaryOperator.LogicalShiftRight: "lshr", s.BinaryOperator.ArithmeticShiftRight: "ashr" if e.left.type.isSigned else "lshr"}
            if op in shifts:
                return Expr(shifts[op], w, (resize(a, w, e.left.type.isSigned), b))
            if op in (s.BinaryOperator.LogicalAnd, s.BinaryOperator.LogicalOr):
                return Expr("and" if op == s.BinaryOperator.LogicalAnd else "or", 1, (truth(a), truth(b)))
            comparisons = (s.BinaryOperator.Equality, s.BinaryOperator.Inequality, s.BinaryOperator.LessThan,
                           s.BinaryOperator.GreaterThan, s.BinaryOperator.LessThanEqual, s.BinaryOperator.GreaterThanEqual)
            if op in comparisons:
                signed = e.left.type.isSigned and e.right.type.isSigned
                cw = max(a.width, b.width); a, b = resize(a, cw, signed), resize(b, cw, signed)
                if op in (s.BinaryOperator.Equality, s.BinaryOperator.Inequality):
                    r = Expr("eq", 1, (a, b))
                    return Expr("not", 1, (r,)) if op == s.BinaryOperator.Inequality else r
                if op in (s.BinaryOperator.GreaterThan, s.BinaryOperator.LessThanEqual): a, b = b, a
                r = Expr("slt" if signed else "ult", 1, (a, b))
                return Expr("not", 1, (r,)) if op in (s.BinaryOperator.LessThanEqual, s.BinaryOperator.GreaterThanEqual) else r
            raise ValueError(f"Unsupported binary operator {op}")
        if kind == s.ExpressionKind.ConditionalOp:
            if len(e.conditions) != 1 or e.conditions[0].pattern is not None:
                raise ValueError("Pattern conditionals unsupported")
            return Expr("mux", w, (truth(convert(e.conditions[0].expr)),
                                   resize(convert(e.left), w, e.left.type.isSigned), resize(convert(e.right), w, e.right.type.isSigned)))
        if kind in (s.ExpressionKind.RangeSelect, s.ExpressionKind.ElementSelect):
            a = convert(e.value)
            r = e.value.type.getBitVectorRange()
            if r.right != 0 or r.left != a.width - 1:
                raise ValueError("Selected packed vectors must have descending [width-1:0] indices")
            if kind == s.ExpressionKind.ElementSelect: low = integer(e.selector)
            else:
                if e.selectionKind != s.RangeSelectionKind.Simple: raise ValueError("Indexed part-select unsupported")
                high, low = integer(e.left), integer(e.right)
                if high < low: raise ValueError("Ascending selects unsupported")
            if low < 0 or low + w > a.width: raise ValueError("Out-of-range select")
            return Expr("slice", w, (a,), offset=low)
        if kind == s.ExpressionKind.Concatenation:
            items = [convert(a) for a in e.operands]
            r = items[0]
            for a in items[1:]: r = Expr("concat", r.width + a.width, (r, a))
            return r
        if kind == s.ExpressionKind.Replication:
            count, a = integer(e.count), convert(e.concat)
            if count <= 0: raise ValueError("Zero-width replication unsupported")
            r = a
            for _ in range(count - 1): r = Expr("concat", r.width + a.width, (r, a))
            return r
        raise ValueError(f"Unsupported expression {kind}; source: {e.syntax}")

    result = {name: resize(signal(name), width) for name, width in outputs.items()}
    if not result: raise ValueError("No outputs")
    return Design(tops[0].name, inputs, result)
