# Slitherlink SMT Solver

## Overview
This project is an SMT-based Slitherlink puzzle solver implemented using Python and `pySMT`. 

The project compares two different approaches for enforcing the **single-loop constraint** of Slitherlink puzzles:
* **Iterative Solver (`solver_iterative.py`)**: Uses an iterative sub-loop elimination method. It detects disconnected loops and dynamically adds new constraints until only one continuous loop remains.
* **Flow Solver (`solver_flow.py`)**: Uses a one-shot SMT encoding with flow-based variables. It enforces the single-loop property directly inside the SMT formula without iterative blocking.

The main purpose of this project is to evaluate and compare these two approaches in terms of **correctness** and **performance**.

---

## Project Structure

### `common.py`
Contains the shared constraints and utility functions used by both solver versions.
* Puzzle file parser
* SMT edge variable definition
* Basic Slitherlink constraints (e.g., cell number constraints, degree constraints)
* Shared helper functions and standard result objects

### `solver_iterative.py`
An SMT solver that implements the iterative sub-loop elimination algorithm:
1. Build the basic Slitherlink constraints.
2. Solve the SMT formula.
3. Analyze the solution graph to check for multiple disconnected loops.
4. If sub-loops exist, add a blocking constraint to eliminate them and go back to Step 2.
5. Repeat until a single valid loop is found or the puzzle is determined to be `UNSAT`.

### `solver_flow.py`
An SMT solver that implements a flow-based (or timestamp/order-based) encoding. 
* Introduces additional SMT variables to represent the sequence/order of the loop.
* Enforces the single-loop property directly within a single SMT formula.
* Unlike the iterative version, it solves the formula in **one shot** without repeated solving or blocking.

### `run_benchmark.py`
A benchmark script for performance evaluation using satisfiable (`SAT`) puzzles.
* **Puzzle Sizes**: 7x7, 10x10, 15x15, 20x20
* **Difficulties**: Normal, Hard
* **Dataset Size**: 30 puzzles for each size and difficulty (Total: 240 puzzles)
* **Input Path**: `data/sat/`
* **Output Path**: `results/`
* *Note: This script can optionally save visualization images for the solved puzzles.*

### `run_edges.py`
A correctness test script designed for edge cases. 
* Verifies whether both solver versions can correctly distinguish between `SAT` and `UNSAT` instances.
* **Input Path**: `data/unsat/`
* **Output Path**: `results/`

### `visualize.py`
A visualization utility for solved puzzles.
* Draws the final Slitherlink loop based on the SMT model output and saves it as an image.
* Useful for checking correctness, debugging constraints, and generating figures for reports.

---

## Requirements

### Installation

Install all the required Python packages at once using `pip`:

<pre><code>pip install -r requirements.txt</code></pre>

---

## How to Run

### 1. Run Benchmark Tests
To evaluate performance on standard puzzles (7x7 to 20x20):
<pre><code>python run_benchmark.py</code></pre>

### 2. Run Edge-Case Tests
To test correctness on `SAT`/`UNSAT` edge cases:
<pre><code>python run_edges.py</code></pre>

---

## Output
All benchmark and test results are saved in the `results/` directory. The output includes:
* **SAT / UNSAT** status of each puzzle
* **Execution time** (running time)
* **Number of iterations** (for the iterative solver)
* **Encoding size** and complexity metrics
* **Benchmark CSV files** for data analysis
* Optional **visualization images** (.png) of the solved loops

---

## Project Purpose
This project was developed as a course project to study **SAT/SMT encodings for NP-hard problems**. The primary objective is to analyze the trade-offs between a dynamic, iterative encoding approach and a static, flow-based one-shot encoding approach when handling global connectivity constraints like the single-loop property in Slitherlink.
