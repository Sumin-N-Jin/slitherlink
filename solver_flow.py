"""
solver_flow.py

Version B:
One-shot single-loop encoding using directed arc variables and timestamp
(order) variables.

Purpose:
- This is a comparison version for the professor's requested "inside SMT"
  single-loop handling.
- It avoids NetworkX-based iterative blocking.
- It adds extra SMT variables and constraints so that all active nodes are
  arranged as one directed cycle.

Main idea:
The local Slitherlink constraints can still allow multiple disconnected loops.
To prevent this inside SMT, this solver adds:
- directed arc variables for each selected edge
- one symbolic start node
- integer timestamp variables for grid nodes

The timestamp constraints force the selected loop to behave like one ordered
cycle. A disconnected cycle would require timestamps to keep increasing around
a closed loop, which is impossible unless it returns to the selected start node.

This is not a min-cost flow formulation. It is a timestamp/order-based
connectivity encoding.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pysmt.shortcuts import (
    And,
    Equals,
    GE,
    Iff,
    Implies,
    Int,
    LE,
    Not,
    Or,
    Plus,
    Solver,
    Symbol,
)
from pysmt.typing import BOOL, INT

from common import (
    EdgeKey,
    EdgeVars,
    Grid,
    Node,
    SolveResult,
    bool_sum,
    build_base_constraints,
    create_edge_variables,
    incident_edges,
    load_puzzle,
)


# A directed arc is represented by two nodes: (from_node, to_node).
ArcKey = Tuple[Node, Node]


def edge_key_to_nodes(key: EdgeKey) -> Tuple[Node, Node]:
    """Map an edge key to the two endpoint nodes of that edge.

    Horizontal edge:
        ("h", i, j) connects node (i,j) to node (i,j+1)

    Vertical edge:
        ("v", i, j) connects node (i,j) to node (i+1,j)
    """
    kind, i, j = key

    if kind == "h":
        return (i, j), (i, j + 1)

    if kind == "v":
        return (i, j), (i + 1, j)

    raise ValueError(f"Unknown edge kind: {kind}")


def make_arc_name(u: Node, v: Node) -> str:
    """Create a readable SMT variable name for a directed arc."""
    return f"a_{u[0]}_{u[1]}__{v[0]}_{v[1]}"


def create_directed_arc_variables(edge_vars: EdgeVars) -> Dict[ArcKey, Any]:
    """Create two directed arc variables for every undirected edge.

    Example:
    If an undirected edge connects u and v, we create:
    - arc u -> v
    - arc v -> u

    Later constraints ensure that at most one direction is selected.
    """
    arcs: Dict[ArcKey, Any] = {}

    for key in edge_vars.edge_by_key:
        u, v = edge_key_to_nodes(key)
        arcs[(u, v)] = Symbol(make_arc_name(u, v), BOOL)
        arcs[(v, u)] = Symbol(make_arc_name(v, u), BOOL)

    return arcs


def build_arc_edge_link_constraints(
    edge_vars: EdgeVars,
    arcs: Dict[ArcKey, Any],
) -> List[Any]:
    """Connect each undirected edge variable with its two directed arcs.

    If the undirected edge is active, exactly one of the two directions
    must be active.

    If the undirected edge is inactive, neither direction can be active.
    """
    constraints: List[Any] = []

    for key, edge in edge_vars.edge_by_key.items():
        u, v = edge_key_to_nodes(key)
        uv = arcs[(u, v)]
        vu = arcs[(v, u)]

        # edge <-> (uv or vu)
        constraints.append(Iff(edge, Or(uv, vu)))

        # Do not allow both directions at the same time.
        constraints.append(Not(And(uv, vu)))

    return constraints


def node_arc_sets(
    n: int,
    m: int,
    arcs: Dict[ArcKey, Any],
) -> Tuple[Dict[Node, List[Any]], Dict[Node, List[Any]]]:
    """Collect incoming and outgoing arc variables for each node."""
    incoming: Dict[Node, List[Any]] = {}
    outgoing: Dict[Node, List[Any]] = {}

    for i in range(n + 1):
        for j in range(m + 1):
            node = (i, j)
            incoming[node] = []
            outgoing[node] = []

    for (u, v), arc in arcs.items():
        outgoing[u].append(arc)
        incoming[v].append(arc)

    return incoming, outgoing


def build_directed_cycle_constraints(
    n: int,
    m: int,
    edge_vars: EdgeVars,
    arcs: Dict[ArcKey, Any],
) -> List[Any]:
    """Force each active node to have one incoming and one outgoing arc.

    In the undirected Slitherlink model, an active node has degree 2.
    In the directed version, this becomes:
    - exactly one incoming arc
    - exactly one outgoing arc

    Inactive nodes must have no incoming or outgoing arcs.
    """
    constraints: List[Any] = []
    incoming, outgoing = node_arc_sets(n, m, arcs)

    for i in range(n + 1):
        for j in range(m + 1):
            node = (i, j)

            incident = incident_edges(i, j, n, m, edge_vars)
            active_degree = bool_sum(incident)
            node_active = Equals(active_degree, Int(2))

            constraints.append(
                Implies(
                    node_active,
                    And(
                        Equals(bool_sum(incoming[node]), Int(1)),
                        Equals(bool_sum(outgoing[node]), Int(1)),
                    ),
                )
            )

            constraints.append(
                Implies(
                    Not(node_active),
                    And(
                        Equals(bool_sum(incoming[node]), Int(0)),
                        Equals(bool_sum(outgoing[node]), Int(0)),
                    ),
                )
            )

    return constraints


def build_timestamp_constraints(
    n: int,
    m: int,
    edge_vars: EdgeVars,
    arcs: Dict[ArcKey, Any],
) -> Tuple[List[Any], Dict[Node, Any], Dict[Node, Any]]:
    """Eliminate disconnected cycles using symbolic start node and timestamps.

    Exactly one active node is selected as the start node.

    For every active arc u -> v:
    - if v is the selected start node, this arc is the wrap-around edge
    - otherwise, timestamp[v] = timestamp[u] + 1

    This prevents disconnected cycles because a separate cycle would need
    timestamps to strictly increase forever around a closed loop.
    """
    constraints: List[Any] = []
    timestamps: Dict[Node, Any] = {}
    start_vars: Dict[Node, Any] = {}

    max_t = (n + 1) * (m + 1)

    for i in range(n + 1):
        for j in range(m + 1):
            node = (i, j)

            t = Symbol(f"t_{i}_{j}", INT)
            s = Symbol(f"start_{i}_{j}", BOOL)

            timestamps[node] = t
            start_vars[node] = s

            # Keep timestamps in a simple finite range.
            constraints.append(GE(t, Int(0)))
            constraints.append(LE(t, Int(max_t)))

            # A start node must be an active node.
            incident = incident_edges(i, j, n, m, edge_vars)
            active_degree = bool_sum(incident)
            node_active = Equals(active_degree, Int(2))

            constraints.append(Implies(s, node_active))
            constraints.append(Implies(s, Equals(t, Int(0))))

    # Select exactly one start node.
    constraints.append(Equals(bool_sum(list(start_vars.values())), Int(1)))

    for (u, v), arc in arcs.items():
        # If arc u -> v is active, then either:
        # 1. v is the selected start node, so this arc closes the cycle, or
        # 2. v must come immediately after u in timestamp order.
        constraints.append(
            Implies(
                arc,
                Or(
                    start_vars[v],
                    Equals(timestamps[v], Plus(timestamps[u], Int(1))),
                ),
            )
        )

    return constraints, timestamps, start_vars


def solve_grid_flow(
    grid: Grid,
    file_label: str = "",
    use_anti_2x2: bool = True,
    solver_name: str = "z3",
) -> SolveResult:
    """Solve a Slitherlink grid using one-shot timestamp connectivity encoding."""
    n, m = len(grid), len(grid[0])
    edge_vars = create_edge_variables(n, m)

    start_time = time.perf_counter()

    # Base constraints are the same local rules used by the iterative solver.
    base_constraints = build_base_constraints(
        grid,
        edge_vars,
        use_anti_2x2=use_anti_2x2,
    )

    # Extra variables and constraints for one-shot single-loop enforcement.
    arcs = create_directed_arc_variables(edge_vars)
    arc_constraints = build_arc_edge_link_constraints(edge_vars, arcs)
    directed_cycle_constraints = build_directed_cycle_constraints(n, m, edge_vars, arcs)
    timestamp_constraints, timestamps, start_vars = build_timestamp_constraints(
        n,
        m,
        edge_vars,
        arcs,
    )

    all_constraints = (
        base_constraints
        + arc_constraints
        + directed_cycle_constraints
        + timestamp_constraints
    )

    num_variables = (
        edge_vars.num_variables
        + len(arcs)
        + len(timestamps)
        + len(start_vars)
    )

    with Solver(name=solver_name) as solver:
        solver.add_assertion(And(all_constraints))

        if solver.solve():
            model = solver.get_model()
            status = "SAT"
        else:
            model = None
            status = "UNSAT"

    return SolveResult(
        solver_name="flow_timestamp",
        file=file_label,
        size=f"{n}x{m}",
        status=status,
        model=model,
        h=edge_vars.h,
        v=edge_vars.v,
        time_sec=time.perf_counter() - start_time,
        iterations=0,
        solver_calls=1,
        num_variables=num_variables,
        num_constraints=len(all_constraints),
        num_blocking_clauses=0,
        notes="symbolic_start",
    )


def solve_puzzle_file_flow(path: str | Path, **kwargs: Any) -> SolveResult:
    """Load a puzzle file and solve it with the flow/timestamp solver."""
    path = Path(path)
    grid = load_puzzle(path)
    return solve_grid_flow(grid, file_label=str(path), **kwargs)