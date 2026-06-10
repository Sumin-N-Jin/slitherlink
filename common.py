"""
common.py

Shared utilities for Slitherlink SMT encodings.

This file contains code that is shared by both solver versions:
- puzzle parsing
- edge-variable creation
- local Slitherlink constraints
- result container
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from pysmt.shortcuts import And, Equals, Int, Ite, Not, Or, Plus, Symbol
from pysmt.typing import BOOL


# Internal grid format:
# - 0, 1, 2, 3 mean clue cells.
# - None means an empty cell with no clue.
Grid = List[List[Optional[int]]]

# A node is a grid point, not a cell.
# For an N x M puzzle, nodes range from (0,0) to (N,M).
Node = Tuple[int, int]

# EdgeKey identifies one grid edge.
# ("h", i, j) means a horizontal edge.
# ("v", i, j) means a vertical edge.
EdgeKey = Tuple[str, int, int]


@dataclass
class EdgeVars:
    """Container for all edge variables.

    h[i][j] is True if the horizontal edge is selected.
    v[i][j] is True if the vertical edge is selected.

    edge_by_key maps an edge location to its SMT variable.
    key_by_edge maps an SMT variable back to its edge location.
    """

    h: List[List[Any]]
    v: List[List[Any]]
    edge_by_key: Dict[EdgeKey, Any]
    key_by_edge: Dict[Any, EdgeKey]
    num_variables: int


@dataclass
class SolveResult:
    """Standard result object returned by both solver versions."""

    solver_name: str
    file: str
    size: str
    status: str
    model: Any | None
    h: List[List[Any]] | None
    v: List[List[Any]] | None
    time_sec: float
    iterations: int = 0
    solver_calls: int = 0
    num_variables: int = 0
    num_constraints: int = 0
    num_blocking_clauses: int = 0
    notes: str = ""


def load_puzzle(path: str | Path) -> Grid:
    """Load a Slitherlink puzzle from a text file.

    Supported format:
    - The first line may be a dimension line, e.g. "7 7" or "10 10".
    - Each following line is one puzzle row.
    - Digits 0, 1, 2, 3 are clues.
    - Space, '.', '-', '_' mean no clue.

    Important:
    Some puzzle files use spaces as actual empty cells.
    Therefore, this parser reads puzzle rows character by character.
    It does not use split() for puzzle rows.
    """
    path = Path(path)
    raw_lines = path.read_text().splitlines()

    lines = []
    for line in raw_lines:
        line = line.rstrip("\n\r")

        # Skip comment lines anywhere in the file.
        if line.lstrip().startswith("#"):
            continue

        # Skip truly empty lines.
        # Whitespace-only lines are kept because they may represent empty puzzle rows.
        if line == "":
            continue

        lines.append(line)

    if not lines:
        raise ValueError(f"Puzzle file is empty: {path}")

    expected_n = None
    expected_m = None

    # Optional first line: dimensions, e.g. "7 7" or "10 10".
    first_tokens = lines[0].split()
    if len(first_tokens) == 2 and all(tok.isdigit() for tok in first_tokens):
        expected_n = int(first_tokens[0])
        expected_m = int(first_tokens[1])
        lines = lines[1:]

    rows: Grid = []

    for line in lines:
        # If the width is given, preserve spaces and pad missing trailing spaces.
        if expected_m is not None:
            if len(line) > expected_m:
                raise ValueError(
                    f"Expected row width {expected_m}, got {len(line)} in {path}: {line!r}"
                )
            line = line.ljust(expected_m)

        row: List[Optional[int]] = []

        for ch in line:
            if ch in {" ", ".", "-", "_"}:
                row.append(None)
            elif ch in {"0", "1", "2", "3"}:
                row.append(int(ch))
            elif ch == "\t":
                row.append(None)
            else:
                raise ValueError(f"Invalid character {ch!r} in {path}: line={line!r}")

        rows.append(row)

    if expected_n is not None and len(rows) != expected_n:
        raise ValueError(
            f"Expected {expected_n} rows from dimension line, got {len(rows)} in {path}"
        )

    if not rows:
        raise ValueError(f"Puzzle file has no grid rows: {path}")

    width = expected_m if expected_m is not None else len(rows[0])

    padded_rows: Grid = []
    for row in rows:
        if len(row) > width:
            raise ValueError(f"Expected row width {width}, got {len(row)} in {path}")
        padded_rows.append(row + [None] * (width - len(row)))

    rows = padded_rows

    if any(len(row) != width for row in rows):
        raise ValueError(f"Puzzle rows have inconsistent widths: {path}")

    return rows


def create_edge_variables(n: int, m: int) -> EdgeVars:
    """Create Boolean SMT variables for all possible grid edges.

    For an N x M cell grid:
    - horizontal edges: (N+1) * M
    - vertical edges: N * (M+1)
    """
    h = [[Symbol(f"h_{i}_{j}", BOOL) for j in range(m)] for i in range(n + 1)]
    v = [[Symbol(f"v_{i}_{j}", BOOL) for j in range(m + 1)] for i in range(n)]

    edge_by_key: Dict[EdgeKey, Any] = {}
    key_by_edge: Dict[Any, EdgeKey] = {}

    for i in range(n + 1):
        for j in range(m):
            key = ("h", i, j)
            edge_by_key[key] = h[i][j]
            key_by_edge[h[i][j]] = key

    for i in range(n):
        for j in range(m + 1):
            key = ("v", i, j)
            edge_by_key[key] = v[i][j]
            key_by_edge[v[i][j]] = key

    return EdgeVars(
        h=h,
        v=v,
        edge_by_key=edge_by_key,
        key_by_edge=key_by_edge,
        num_variables=(n + 1) * m + n * (m + 1),
    )


def bool_sum(edges: List[Any]) -> Any:
    """Return an integer expression counting how many Boolean edges are true."""
    if not edges:
        return Int(0)
    return Plus([Ite(edge, Int(1), Int(0)) for edge in edges])


def incident_edges(i: int, j: int, n: int, m: int, edge_vars: EdgeVars) -> List[Any]:
    """Return all h/v edge variables touching node (i,j).

    A node can touch up to four edges:
    - left horizontal edge
    - right horizontal edge
    - upper vertical edge
    - lower vertical edge

    Boundary nodes have fewer incident edges.
    """
    h, v = edge_vars.h, edge_vars.v
    edges: List[Any] = []

    # Horizontal edge to the left: h[i][j-1]
    if j > 0:
        edges.append(h[i][j - 1])

    # Horizontal edge to the right: h[i][j]
    if j < m:
        edges.append(h[i][j])

    # Vertical edge above: v[i-1][j]
    if i > 0:
        edges.append(v[i - 1][j])

    # Vertical edge below: v[i][j]
    if i < n:
        edges.append(v[i][j])

    return edges


def build_node_degree_constraints(n: int, m: int, edge_vars: EdgeVars) -> List[Any]:
    """Build node-degree constraints.

    In a valid Slitherlink loop, every node must have degree 0 or 2:
    - degree 0: the loop does not pass through this node
    - degree 2: the loop passes through this node

    This prevents dead ends and branching points.
    """
    constraints: List[Any] = []

    for i in range(n + 1):
        for j in range(m + 1):
            edges = incident_edges(i, j, n, m, edge_vars)
            degree = bool_sum(edges)
            constraints.append(Or(Equals(degree, Int(0)), Equals(degree, Int(2))))

    return constraints


def build_clue_constraints(grid: Grid, edge_vars: EdgeVars) -> List[Any]:
    """Build clue constraints.

    For each numbered cell, the number of selected surrounding edges
    must be equal to the clue value.
    """
    n, m = len(grid), len(grid[0])
    h, v = edge_vars.h, edge_vars.v
    constraints: List[Any] = []

    for i in range(n):
        for j in range(m):
            clue = grid[i][j]
            if clue is None:
                continue

            surrounding = [
                h[i][j],       # top
                h[i + 1][j],   # bottom
                v[i][j],       # left
                v[i][j + 1],   # right
            ]
            constraints.append(Equals(bool_sum(surrounding), Int(clue)))

    return constraints


def build_anti_2x2_constraints(n: int, m: int, edge_vars: EdgeVars) -> List[Any]:
    """Forbid a single cell from being fully enclosed.

    This removes the smallest possible isolated loop: a 1x1 loop.
    It does not guarantee the global single-loop property by itself.
    """
    h, v = edge_vars.h, edge_vars.v
    constraints: List[Any] = []

    for i in range(n):
        for j in range(m):
            constraints.append(Not(And(h[i][j], h[i + 1][j], v[i][j], v[i][j + 1])))

    return constraints


def build_base_constraints(
    grid: Grid,
    edge_vars: EdgeVars,
    use_anti_2x2: bool = True,
) -> List[Any]:
    """Build the common local constraints.

    These constraints are shared by both solver versions.

    The global single-loop condition is handled separately:
    - iterative solver: NetworkX + blocking clauses
    - flow solver: timestamp/direction constraints
    """
    n, m = len(grid), len(grid[0])

    constraints: List[Any] = []
    constraints += build_node_degree_constraints(n, m, edge_vars)
    constraints += build_clue_constraints(grid, edge_vars)

    if use_anti_2x2:
        constraints += build_anti_2x2_constraints(n, m, edge_vars)

    return constraints


def result_to_row(result: SolveResult) -> Dict[str, Any]:
    """Convert solver output into a CSV row.

    This is used by benchmark scripts to save experimental results.
    """
    return {
        "solver": result.solver_name,
        "file": result.file,
        "size": result.size,
        "status": result.status,
        "iterations": result.iterations,
        "solver_calls": result.solver_calls,
        "time_sec": f"{result.time_sec:.6f}",
        "num_variables": result.num_variables,
        "num_constraints": result.num_constraints,
        "num_blocking_clauses": result.num_blocking_clauses,
        "notes": result.notes,
    }