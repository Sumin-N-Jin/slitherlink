"""
run_edges.py

Run quick correctness tests on UNSAT and edge-case Slitherlink puzzles.

This script is separate from run_benchmark.py.

Purpose:
- run_benchmark.py is for performance experiments on many SAT puzzles.
- run_edges.py is for quick correctness checks on special cases.

The test files are expected under:
    data/puzzles/unsat/

These files may include:
- intentionally UNSAT puzzles
- edge cases
- corrupted puzzles
- very small puzzles

The script runs both solver versions and prints their status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from solver_iterative import solve_puzzle_file_iterative
from solver_flow import solve_puzzle_file_flow
import csv


TEST_DIR = Path("data/puzzles/unsat")


def run_solver_safely(solver_name: str, path: Path) -> str:
    """Run one solver and return only its status.

    If the solver crashes on a malformed file, return ERROR instead of
    stopping the whole test script.
    """
    try:
        if solver_name == "iterative":
            result = solve_puzzle_file_iterative(path)
        elif solver_name == "flow":
            result = solve_puzzle_file_flow(path)
        else:
            raise ValueError(f"Unknown solver: {solver_name}")

        return result.status

    except Exception as exc:
        return f"ERROR: {repr(exc)}"


def main() -> None:
    """Run all edge-case and UNSAT tests."""
    files = sorted(TEST_DIR.rglob("*.txt"))

    if not files:
        print(f"No test files found under {TEST_DIR}")
        return
    rows = []

    print(f"Found {len(files)} test files.\n")
    print(f"{'File':<40} {'Iterative':<20} {'Flow':<20}")
    print("-" * 80)

    for path in files:
        iterative_status = run_solver_safely("iterative", path)
        flow_status = run_solver_safely("flow", path)

        rows.append({
            "file": path.name,
            "iterative": iterative_status,
            "flow": flow_status,
            "agreement": iterative_status == flow_status,
        })

        print(
            f"{path.name:<40} "
            f"{iterative_status:<20} "
            f"{flow_status:<20}"
        )

    with open(
        "results/edge_case_results.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
                f,
                fieldnames=["file", "iterative", "flow", "agreement"]
            )
        writer.writeheader()
        writer.writerows(rows)

print("\nSaved results/edge_case_results.csv")


if __name__ == "__main__":
    main()