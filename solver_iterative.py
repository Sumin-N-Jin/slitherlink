"""
solver_iterative.py

Version A:
NetworkX-based iterative sub-loop elimination.

This solver uses a lazy constraint strategy.

Step 1:
Build the basic SMT formula:
- node-degree constraints
- clue constraints
- optional anti-2x2 constraints

Step 2:
Ask Z3 for a satisfying assignment.

Step 3:
Convert the active edges in the model into a NetworkX graph.

Step 4:
If the graph has exactly one connected component, we accept the solution.

Step 5:
If the graph has multiple connected components, then the solver found
several disconnected loops. We block one of those loops and solve again.

This repeats until:
- a single loop is found,
- the formula becomes UNSAT,
- or the maximum iteration limit is reached.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import networkx as nx
from pysmt.shortcuts import And, Not, Solver

from common import (
    EdgeKey,
    EdgeVars,
    Grid,
    Node,
    SolveResult,
    build_base_constraints,
    create_edge_variables,
    load_puzzle,
)


def _edge_is_true(model: Any, edge: Any) -> bool:
    """Check whether one edge variable is True in the SMT model."""
    value = model.get_value(edge)
    return bool(value.is_true())


def active_edges_from_model(model: Any, edge_vars: EdgeVars) -> Dict[EdgeKey, Any]:
    """Return all active edge variables from the model.

    The result maps:
        EdgeKey -> SMT variable

    Example:
        ("h", 2, 3) -> h_2_3

    Only edges assigned True are included.
    """
    active: Dict[EdgeKey, Any] = {}

    for key, edge in edge_vars.edge_by_key.items():
        if _edge_is_true(model, edge):
            active[key] = edge

    return active


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


def build_loop_graph(active_edges: Dict[EdgeKey, Any]) -> nx.Graph:
    """Build a graph from the active Slitherlink edges.

    Nodes in this graph are grid points.
    Edges in this graph are selected Slitherlink line segments.

    This graph is used only for checking connectivity.
    """
    graph = nx.Graph()

    for key in active_edges:
        u, v = edge_key_to_nodes(key)
        graph.add_edge(u, v, edge_key=key)

    return graph


def component_edge_vars(
    component_nodes: Set[Node],
    active_edges: Dict[EdgeKey, Any],
) -> List[Any]:
    """Return active edge variables inside one connected component.

    This is used to build a blocking clause.

    Important:
    We only use currently active edges. We do not include inactive edges that
    happen to be inside the same component area.
    """
    subloop_vars: List[Any] = []

    for key, edge_var in active_edges.items():
        u, v = edge_key_to_nodes(key)
        if u in component_nodes and v in component_nodes:
            subloop_vars.append(edge_var)

    return subloop_vars


def solve_grid_iterative(
    grid: Grid,
    file_label: str = "",
    use_anti_2x2: bool = True,
    max_iterations: int = 100,
    solver_name: str = "z3",
) -> SolveResult:
    """Solve a Slitherlink grid using iterative sub-loop elimination.

    This solver does not encode the full single-loop constraint upfront.
    Instead, it finds disconnected loops after each SMT solve and blocks them.
    """
    n, m = len(grid), len(grid[0])
    edge_vars = create_edge_variables(n, m)

    # Build local Slitherlink constraints.
    # These constraints alone may still allow multiple disconnected loops.
    constraints = build_base_constraints(grid, edge_vars, use_anti_2x2=use_anti_2x2)

    # Each blocking clause prevents one previously discovered sub-loop
    # from appearing again.
    blocking_clauses: List[Any] = []

    start = time.perf_counter()
    solver_calls = 0

    with Solver(name=solver_name) as solver:
        # Add the base SMT formula once.
        solver.add_assertion(And(constraints))

        for iteration in range(1, max_iterations + 1):
            solver_calls += 1

            # Ask Z3 to solve the current formula.
            if not solver.solve():
                return SolveResult(
                    solver_name="iterative",
                    file=file_label,
                    size=f"{n}x{m}",
                    status="UNSAT",
                    model=None,
                    h=edge_vars.h,
                    v=edge_vars.v,
                    time_sec=time.perf_counter() - start,
                    iterations=iteration,
                    solver_calls=solver_calls,
                    num_variables=edge_vars.num_variables,
                    num_constraints=len(constraints) + len(blocking_clauses),
                    num_blocking_clauses=len(blocking_clauses),
                )

            model = solver.get_model()

            # Extract all edges selected by the model.
            active_edges = active_edges_from_model(model, edge_vars)

            # Build a graph from the selected edges.
            graph = build_loop_graph(active_edges)

            if graph.number_of_edges() == 0:
                # Local constraints may allow a model with no selected edges,
                # especially for edge cases or highly corrupted puzzles.
                # This is not a valid Slitherlink loop.
                return SolveResult(
                    solver_name="iterative",
                    file=file_label,
                    size=f"{n}x{m}",
                    status="UNSAT",
                    model=None,
                    h=edge_vars.h,
                    v=edge_vars.v,
                    time_sec=time.perf_counter() - start,
                    iterations=iteration,
                    solver_calls=solver_calls,
                    num_variables=edge_vars.num_variables,
                    num_constraints=len(constraints) + len(blocking_clauses),
                    num_blocking_clauses=len(blocking_clauses),
                    notes="SAT assignment contained no active edges",
                )

            # Each connected component represents one separate loop-like piece.
            components = list(nx.connected_components(graph))

            if len(components) == 1:
                # All active edges are connected, so we have one loop.
                return SolveResult(
                    solver_name="iterative",
                    file=file_label,
                    size=f"{n}x{m}",
                    status="SAT",
                    model=model,
                    h=edge_vars.h,
                    v=edge_vars.v,
                    time_sec=time.perf_counter() - start,
                    iterations=iteration,
                    solver_calls=solver_calls,
                    num_variables=edge_vars.num_variables,
                    num_constraints=len(constraints) + len(blocking_clauses),
                    num_blocking_clauses=len(blocking_clauses),
                )

            # If there are multiple components, block one discovered sub-loop.
            # We choose the smallest component because it is usually a small
            # unwanted loop and cheap to block.
            smallest_component = min(components, key=len)
            subloop_vars = component_edge_vars(smallest_component, active_edges)

            if not subloop_vars:
                return SolveResult(
                    solver_name="iterative",
                    file=file_label,
                    size=f"{n}x{m}",
                    status="ERROR",
                    model=model,
                    h=edge_vars.h,
                    v=edge_vars.v,
                    time_sec=time.perf_counter() - start,
                    iterations=iteration,
                    solver_calls=solver_calls,
                    num_variables=edge_vars.num_variables,
                    num_constraints=len(constraints) + len(blocking_clauses),
                    num_blocking_clauses=len(blocking_clauses),
                    notes="Could not extract sub-loop variables",
                )

            # Blocking clause:
            # If all edges in this sub-loop are True again, the same sub-loop
            # would reappear. Not(And(...)) prevents that exact sub-loop.
            blocking_clause = Not(And(subloop_vars))
            blocking_clauses.append(blocking_clause)
            solver.add_assertion(blocking_clause)

    # If the loop finishes without returning, we reached the iteration limit.
    return SolveResult(
        solver_name="iterative",
        file=file_label,
        size=f"{n}x{m}",
        status="TIMEOUT_OR_MAX_ITER",
        model=None,
        h=edge_vars.h,
        v=edge_vars.v,
        time_sec=time.perf_counter() - start,
        iterations=max_iterations,
        solver_calls=solver_calls,
        num_variables=edge_vars.num_variables,
        num_constraints=len(constraints) + len(blocking_clauses),
        num_blocking_clauses=len(blocking_clauses),
    )


def solve_puzzle_file_iterative(path: str | Path, **kwargs: Any) -> SolveResult:
    """Load a puzzle file and solve it with the iterative solver."""
    path = Path(path)
    grid = load_puzzle(path)
    return solve_grid_iterative(grid, file_label=str(path), **kwargs)