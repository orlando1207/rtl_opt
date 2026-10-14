"""Global DAG extraction following ROVER (20)-(23), with explicit activity."""
import math
import shutil
import time
from pathlib import Path
import pulp
from .cost import area


def index_graph(graph):
    classes = {c["id"]: c for c in graph["classes"]}
    for c in classes.values():
        for n in c["nodes"]:
            if any(k not in classes for k in n["args"]): raise ValueError("Dangling e-class")
            if n["width"] != c["width"]: raise ValueError("E-class width mismatch")
    if any(c not in classes for c in graph["roots"].values()): raise ValueError("Missing root")
    return classes


def reachable_selection(graph, selected):
    live, visiting = {}, set()
    def visit(cid):
        if cid in visiting: raise ValueError("Cyclic extracted implementation")
        if cid in live: return
        if cid not in selected: raise ValueError("Missing selected dependency")
        visiting.add(cid)
        for child in selected[cid]["args"]: visit(child)
        visiting.remove(cid); live[cid] = selected[cid]
    for root in graph["roots"].values(): visit(root)
    return live


def extract(graph, method="ilp", timeout=120, lp_path=None, cost_fn=area):
    classes = index_graph(graph)
    costs = {n["id"]: float(cost_fn(n, classes)) for c in classes.values() for n in c["nodes"]}
    if any(not math.isfinite(v) or v < 0 for v in costs.values()): raise ValueError("Costs must be finite and nonnegative")
    started = time.monotonic()
    if method == "greedy":
        best, selected = {}, {}
        # Height tie breaking makes even zero-cost wiring extraction acyclic.
        for _ in range(len(classes) + 1):
            changed = False
            for cid, c in classes.items():
                for n in c["nodes"]:
                    if any(k not in best for k in n["args"]): continue
                    score = (costs[n["id"]] + sum(best[k][0] for k in n["args"]),
                             1 + max((best[k][1] for k in n["args"]), default=0))
                    if score < best.get(cid, (math.inf, math.inf)):
                        best[cid], selected[cid], changed = score, n, True
            if not changed: break
        selected = reachable_selection(graph, selected)
        return selected, {"method": method, "status": "heuristic", "objective": sum(costs[n["id"]] for n in selected.values()),
                          "seconds": time.monotonic() - started, "tree_objective": sum(best[c][0] for c in graph["roots"].values())}
    if method != "ilp": raise ValueError(f"Unknown extractor {method}")
    if timeout <= 0: raise ValueError("ILP timeout must be positive")
    problem = pulp.LpProblem("rover_dag_extraction", pulp.LpMinimize)
    x = {nid: pulp.LpVariable(f"x_{nid}", cat="Binary") for nid in costs}
    y = {cid: pulp.LpVariable(f"active_{cid}", cat="Binary") for cid in classes}
    count = len(classes)
    rank = {cid: pulp.LpVariable(f"rank_{cid}", lowBound=0, upBound=count - 1, cat="Integer") for cid in classes}
    problem += pulp.lpSum(costs[nid] * v for nid, v in x.items())
    for cid, c in classes.items():
        problem += pulp.lpSum(x[n["id"]] for n in c["nodes"]) == y[cid], f"one_if_active_{cid}"
        for n in c["nodes"]:
            for i, child in enumerate(n["args"]):
                problem += x[n["id"]] <= y[child], f"dependency_{n['id']}_{i}"
                problem += rank[cid] >= rank[child] + 1 - count * (1 - x[n["id"]]), f"acyclic_{n['id']}_{i}"
    for i, cid in enumerate(sorted(set(graph["roots"].values()))): problem += y[cid] == 1, f"output_{i}"
    if lp_path: problem.writeLP(str(Path(lp_path)))
    cbc = shutil.which("cbc")
    if not cbc: raise RuntimeError("CBC not found; activate the rover Conda environment")
    solver = pulp.COIN_CMD(path=cbc, msg=False, timeLimit=timeout, threads=1, gapRel=0)
    problem.solve(solver)
    feasible = problem.sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
    if not feasible: raise RuntimeError(f"No feasible ILP solution: {pulp.LpStatus[problem.status]}")
    selected = {}
    for cid, c in classes.items():
        chosen = [n for n in c["nodes"] if x[n["id"]].value() is not None and x[n["id"]].value() > .5]
        if len(chosen) > 1: raise RuntimeError("Solver returned multiple nodes per class")
        if chosen: selected[cid] = chosen[0]
    selected = reachable_selection(graph, selected)
    optimal = problem.sol_status == pulp.LpSolutionOptimal and problem.status == pulp.LpStatusOptimal
    return selected, {"method": method, "status": "optimal" if optimal else "feasible_not_proven_optimal",
                      "objective": sum(costs[n["id"]] for n in selected.values()), "seconds": time.monotonic() - started,
                      "solver_objective": pulp.value(problem.objective), "optimality_gap": 0 if optimal else None,
                      "selected_nodes": len(selected), "variables": len(problem.variables()), "constraints": len(problem.constraints)}
