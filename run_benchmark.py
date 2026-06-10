"""
run_benchmark.py

Benchmark driver for comparing multiple Slitherlink SMT encodings.

This script:
1. Finds puzzle files under a given puzzle directory.
2. Runs one or more solver versions on each puzzle.
3. Records runtime, SAT/UNSAT status, iteration count, and encoding size.
4. Saves a raw benchmark CSV file.
5. Saves a side-by-side comparison CSV file.
6. Optionally saves solution figures for SAT instances.

Solver versions:
- iterative: NetworkX-based iterative sub-loop elimination
- flow: one-shot timestamp/direction encoding

Expected puzzle layout:
    data/puzzles/sat/
        puzzle_5x5_easy_01.txt
        puzzle_10x10_normal_12.txt
        puzzle_15x15_hard_25.txt

Difficulty subfolders are optional because this script recursively collects
all .txt files under --puzzle-dir.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common import load_puzzle, result_to_row
from solver_iterative import solve_puzzle_file_iterative
from solver_flow import solve_puzzle_file_flow

# Visualization is optional.
# The benchmark should still run even if visualize.py is missing
# or matplotlib is not available.
try:
    from visualize import visualize_solution
except Exception:
    visualize_solution = None


# Pattern used to find puzzle size from filenames such as:
# puzzle_10x10_normal_12.txt
SIZE_RE = re.compile(r"(?P<rows>\d+)x(?P<cols>\d+)", re.IGNORECASE)


def find_puzzle_files(root: Path) -> List[Path]:
    """Find all .txt puzzle files under the given directory.

    The search is recursive, so this works both with and without
    difficulty subfolders.
    """
    return sorted(root.rglob("*.txt"))


def extract_metadata_from_filename(path: Path) -> Dict[str, str]:
    """Extract size, difficulty, and puzzle id from a filename.

    Example:
        puzzle_15x15_normal_25.txt

    Extracted metadata:
        size_from_name = 15x15
        difficulty = normal
        puzzle_id = 25

    The function is intentionally permissive. If a filename does not follow
    this exact format, the missing fields are left blank.
    """
    stem = path.stem
    parts = stem.split("_")

    size_from_name = ""
    difficulty = ""
    puzzle_id = ""

    size_match = SIZE_RE.search(stem)
    if size_match:
        size_from_name = f"{size_match.group('rows')}x{size_match.group('cols')}"

    # Look for common difficulty labels in the filename.
    difficulty_labels = {
        "easy",
        "medium",
        "normal",
        "hard",
        "expert",
        "difficult",
        "tricky",
    }

    for part in parts:
        if part.lower() in difficulty_labels:
            difficulty = part.lower()
            break

    # Use the last numeric token as the puzzle id.
    for part in reversed(parts):
        if part.isdigit():
            puzzle_id = part
            break

    return {
        "size_from_name": size_from_name,
        "difficulty": difficulty,
        "puzzle_id": puzzle_id,
    }


def run_one_solver(
    solver: str,
    path: Path,
    relative_path: str,
    use_anti_2x2: bool,
) -> Tuple[Dict[str, Any], Any]:
    """Run one solver on one puzzle and return a CSV row.

    Both solver implementations return the same SolveResult structure.
    This makes it possible to benchmark different encodings with the same
    code path.
    """
    if solver == "iterative":
        result = solve_puzzle_file_iterative(
            path,
            use_anti_2x2=use_anti_2x2,
        )
    elif solver == "flow":
        result = solve_puzzle_file_flow(
            path,
            use_anti_2x2=use_anti_2x2,
        )
    else:
        raise ValueError(f"Unknown solver: {solver}")

    row = result_to_row(result)
    row["relative_path"] = relative_path

    # Add filename metadata such as size, difficulty, and puzzle id.
    meta = extract_metadata_from_filename(path)
    row.update(meta)

    return row, result


def build_comparison_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build side-by-side comparison rows.

    Raw benchmark output has one row per (solver, puzzle).

    This function converts it into one row per puzzle, with iterative and flow
    results placed side by side. This is easier to use for tables and plots.
    """
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for row in rows:
        rel = row["relative_path"]
        solver = row["solver"]
        grouped.setdefault(rel, {})[solver] = row

    comparison_rows: List[Dict[str, Any]] = []

    for rel, by_solver in sorted(grouped.items()):
        iterative = by_solver.get("iterative")
        flow = by_solver.get("flow_timestamp")

        # If one solver was not run, skip side-by-side comparison.
        if iterative is None or flow is None:
            continue

        try:
            iterative_time = float(iterative["time_sec"])
        except Exception:
            iterative_time = None

        try:
            flow_time = float(flow["time_sec"])
        except Exception:
            flow_time = None

        # Speed ratio:
        #   flow_time / iterative_time
        #
        # > 1 means flow is slower.
        # < 1 means flow is faster.
        if iterative_time is not None and flow_time is not None and iterative_time > 0:
            flow_over_iterative = flow_time / iterative_time
        else:
            flow_over_iterative = ""

        comparison_rows.append(
            {
                "relative_path": rel,
                "size": iterative.get("size", ""),
                "size_from_name": iterative.get("size_from_name", ""),
                "difficulty": iterative.get("difficulty", ""),
                "puzzle_id": iterative.get("puzzle_id", ""),
                "iterative_status": iterative.get("status", ""),
                "flow_status": flow.get("status", ""),
                "iterative_time_sec": iterative.get("time_sec", ""),
                "flow_time_sec": flow.get("time_sec", ""),
                "flow_over_iterative_time": (
                    f"{flow_over_iterative:.6f}"
                    if isinstance(flow_over_iterative, float)
                    else ""
                ),
                "iterative_iterations": iterative.get("iterations", ""),
                "iterative_solver_calls": iterative.get("solver_calls", ""),
                "flow_solver_calls": flow.get("solver_calls", ""),
                "iterative_num_variables": iterative.get("num_variables", ""),
                "flow_num_variables": flow.get("num_variables", ""),
                "iterative_num_constraints": iterative.get("num_constraints", ""),
                "flow_num_constraints": flow.get("num_constraints", ""),
                "iterative_blocking_clauses": iterative.get("num_blocking_clauses", ""),
                "flow_notes": flow.get("notes", ""),
            }
        )

    return comparison_rows


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    """Save rows to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def maybe_save_figure(
    result: Any,
    puzzle_path: Path,
    puzzle_root: Path,
    figure_dir: Path,
    solver: str,
) -> None:
    """Save a solution figure if visualization is available.

    Figures are not required for benchmarking itself.
    They are mainly useful for debugging and for report examples.
    """
    if visualize_solution is None:
        return

    if result.status != "SAT":
        return

    grid = load_puzzle(puzzle_path)

    safe_name = str(puzzle_path.relative_to(puzzle_root))
    safe_name = safe_name.replace("/", "_").replace("\\", "_")

    save_path = figure_dir / solver / f"{safe_name}.png"

    visualize_solution(
        grid,
        result.model,
        result.h,
        result.v,
        title=f"{solver}: {safe_name} ({result.size}) — {result.time_sec:.4f}s",
        save_path=save_path,
        show=False,
    )


def main() -> None:
    """Run the benchmark from command-line arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--puzzle-dir",
        default="data/puzzles/sat",
        help="Root directory containing .txt puzzle files",
    )
    parser.add_argument(
        "--output",
        default="results/benchmark_results.csv",
        help="CSV output path for raw long-form benchmark results",
    )
    parser.add_argument(
        "--comparison-output",
        default="results/benchmark_comparison.csv",
        help="CSV output path for side-by-side solver comparison",
    )
    parser.add_argument(
        "--solver",
        choices=["iterative", "flow", "both"],
        default="both",
        help="Which solver version to run",
    )
    parser.add_argument(
        "--save-figures",
        action="store_true",
        help="Save figures for SAT solutions",
    )
    parser.add_argument(
        "--figure-dir",
        default="results/figures",
        help="Directory for saved figures",
    )
    parser.add_argument(
        "--no-anti-2x2",
        action="store_true",
        help="Disable anti-2x2 / anti-1x1-loop constraints",
    )

    args = parser.parse_args()

    puzzle_root = Path(args.puzzle_dir)
    puzzle_files = find_puzzle_files(puzzle_root)

    if not puzzle_files:
        print(f"No .txt puzzle files found under {puzzle_root}")
        return

    # Run both solver versions by default.
    if args.solver == "both":
        solvers = ["iterative", "flow"]
    else:
        solvers = [args.solver]

    use_anti_2x2 = not args.no_anti_2x2
    rows: List[Dict[str, Any]] = []
    figure_dir = Path(args.figure_dir)

    print(f"Found {len(puzzle_files)} puzzle files.")
    print(f"Solvers: {', '.join(solvers)}")
    print(
        f"{'Solver':<14} {'File':<42} {'Size':<8} "
        f"{'Status':<16} {'Iters':<7} {'Calls':<7} {'Time(s)':<10}"
    )

    for path in puzzle_files:
        relative_path = str(path.relative_to(puzzle_root))

        for solver in solvers:
            try:
                row, result = run_one_solver(
                    solver=solver,
                    path=path,
                    relative_path=relative_path,
                    use_anti_2x2=use_anti_2x2,
                )
            except Exception as exc:
                # Do not stop the whole benchmark because of one failed run.
                # Record the error in the CSV and continue with the next run.
                meta = extract_metadata_from_filename(path)

                row = {
                    "solver": solver,
                    "relative_path": relative_path,
                    "file": str(path),
                    "size": meta.get("size_from_name", ""),
                    "status": "ERROR",
                    "iterations": "",
                    "solver_calls": "",
                    "time_sec": "",
                    "num_variables": "",
                    "num_constraints": "",
                    "num_blocking_clauses": "",
                    "notes": repr(exc),
                    **meta,
                }
                result = None

            rows.append(row)

            print(
                f"{row['solver']:<14} {row['relative_path']:<42} "
                f"{row['size']:<8} {row['status']:<16} "
                f"{str(row['iterations']):<7} {str(row['solver_calls']):<7} "
                f"{str(row['time_sec']):<10}"
            )

            if args.save_figures and result is not None:
                maybe_save_figure(
                    result=result,
                    puzzle_path=path,
                    puzzle_root=puzzle_root,
                    figure_dir=figure_dir,
                    solver=row["solver"],
                )

    # Raw output:
    # one row per (solver, puzzle)
    raw_fieldnames = [
        "solver",
        "relative_path",
        "file",
        "size",
        "size_from_name",
        "difficulty",
        "puzzle_id",
        "status",
        "iterations",
        "solver_calls",
        "time_sec",
        "num_variables",
        "num_constraints",
        "num_blocking_clauses",
        "notes",
    ]

    output_path = Path(args.output)
    save_csv(output_path, rows, raw_fieldnames)

    # Comparison output:
    # one row per puzzle with both solver results side by side
    comparison_rows = build_comparison_rows(rows)
    comparison_output_path = Path(args.comparison_output)

    comparison_fieldnames = [
        "relative_path",
        "size",
        "size_from_name",
        "difficulty",
        "puzzle_id",
        "iterative_status",
        "flow_status",
        "iterative_time_sec",
        "flow_time_sec",
        "flow_over_iterative_time",
        "iterative_iterations",
        "iterative_solver_calls",
        "flow_solver_calls",
        "iterative_num_variables",
        "flow_num_variables",
        "iterative_num_constraints",
        "flow_num_constraints",
        "iterative_blocking_clauses",
        "flow_notes",
    ]

    save_csv(comparison_output_path, comparison_rows, comparison_fieldnames)

    sat_count = sum(1 for r in rows if r["status"] == "SAT")
    unsat_count = sum(1 for r in rows if r["status"] == "UNSAT")
    error_count = sum(1 for r in rows if r["status"] == "ERROR")

    print(f"\nWrote raw results to {output_path}")
    print(f"Wrote comparison results to {comparison_output_path}")
    print(
        f"Total runs: {len(rows)} | "
        f"SAT: {sat_count} | "
        f"UNSAT: {unsat_count} | "
        f"ERROR: {error_count}"
    )


if __name__ == "__main__":
    main()