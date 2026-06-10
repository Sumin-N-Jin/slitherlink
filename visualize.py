"""
visualize.py

Visualization utilities for Slitherlink solutions.

This module converts a solved SMT model into a picture of the Slitherlink grid.

It is useful for:
- checking whether the solver output looks correct
- debugging suspicious solutions
- generating figures for the final report

The selected edges are drawn as a thick blue loop on top of the puzzle grid.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt


def visualize_solution(
    grid,
    model,
    h_vars,
    v_vars,
    title="Slitherlink Solution",
    save_path=None,
    show=True,
):
    """Draw a Slitherlink puzzle and its solved loop.

    Parameters:
    - grid: puzzle clue grid. Clues are 0, 1, 2, 3. Empty cells are None.
    - model: SMT model returned by the solver.
    - h_vars: horizontal edge variables.
    - v_vars: vertical edge variables.
    - title: title shown above the plot.
    - save_path: optional path for saving the figure.
    - show: if True, display the figure. If False, close it after saving.

    Returns:
    - fig, ax: matplotlib figure and axes objects.
    """

    # Puzzle size.
    #
    # Example:
    #   A 10x10 puzzle has:
    #       rows = 10
    #       cols = 10
    rows = len(grid)
    cols = len(grid[0]) if rows else 0

    # Create a matplotlib figure.
    #
    # fig = the whole image
    # ax  = the drawing area inside the image
    #
    # The figure size is scaled with the puzzle size,
    # but it never becomes too small for tiny puzzles.
    fig, ax = plt.subplots(figsize=(max(cols, 4) + 1, max(rows, 4) + 1))

    # Configure the drawing area.
    #
    # Matplotlib's origin is at the bottom-left,
    # but puzzle rows are indexed from the top.
    # Later we use (rows - i) to flip the y-coordinate.
    #
    # A small margin is added so nodes and edges near the border
    # are not clipped.
    ax.set_xlim(-0.3, cols + 0.3)
    ax.set_ylim(-0.3, rows + 0.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=13, pad=12)

    # Draw horizontal background grid lines.
    #
    # These are light gray guide lines only.
    # They show cell boundaries but are not the solution loop.
    for i in range(rows + 1):
        y = rows - i
        ax.plot(
            [0, cols],
            [y, y],
            color="#dddddd",
            linewidth=0.8,
            zorder=1,
        )

    # Draw vertical background grid lines.
    #
    # These lines complete the light gray puzzle grid.
    for j in range(cols + 1):
        ax.plot(
            [j, j],
            [0, rows],
            color="#dddddd",
            linewidth=0.8,
            zorder=1,
        )

    # Draw puzzle nodes.
    #
    # Nodes are the intersection points of the grid.
    # In the SMT encoding, horizontal and vertical edge variables
    # connect these nodes.
    #
    # Example:
    #   node ---- node
    #     |        |
    #   node ---- node
    for i in range(rows + 1):
        for j in range(cols + 1):
            ax.plot(
                j,
                rows - i,
                "ko",
                markersize=4,
                zorder=3,
            )

    # Draw clue numbers inside cells.
    #
    # Each cell may contain:
    #   0, 1, 2, 3  -> clue
    #   None        -> empty cell
    #
    # Only real clues are displayed.
    for i in range(rows):
        for j in range(cols):
            clue = grid[i][j]

            if clue is not None:
                ax.text(
                    j + 0.5,
                    rows - i - 0.5,
                    str(clue),
                    ha="center",
                    va="center",
                    fontsize=14,
                    fontweight="bold",
                    color="#222222",
                )

    if model is None:
        # No model usually means:
        #   - UNSAT puzzle
        #   - solver failure
        #
        # Instead of drawing a loop, show a message in the center.
        ax.text(
            cols / 2,
            rows / 2,
            "No Solution",
            ha="center",
            va="center",
            fontsize=16,
            color="red",
            fontweight="bold",
            bbox=dict(
                boxstyle="round",
                facecolor="lightyellow",
                alpha=0.8,
            ),
        )
    else:
        # Draw selected horizontal edges from the SMT model.
        #
        # h_vars[i][j] represents this kind of edge:
        #
        #   node ---- node
        #
        # If the model assigns h_vars[i][j] = True,
        # that horizontal edge is part of the final loop.
        for i in range(rows + 1):
            for j in range(cols):
                if model.get_value(h_vars[i][j]).is_true():
                    y = rows - i
                    ax.plot(
                        [j, j + 1],
                        [y, y],
                        color="royalblue",
                        linewidth=3,
                        solid_capstyle="round",
                        zorder=2,
                    )

        # Draw selected vertical edges from the SMT model.
        #
        # v_vars[i][j] represents this kind of edge:
        #
        #   node
        #     |
        #   node
        #
        # If the model assigns v_vars[i][j] = True,
        # that vertical edge is part of the final loop.
        for i in range(rows):
            for j in range(cols + 1):
                if model.get_value(v_vars[i][j]).is_true():
                    ax.plot(
                        [j, j],
                        [rows - i, rows - i - 1],
                        color="royalblue",
                        linewidth=3,
                        solid_capstyle="round",
                        zorder=2,
                    )

    # Adjust spacing around the figure.
    plt.tight_layout()

    # Save figure to disk if a path is provided.
    #
    # Example:
    #   results/figures/puzzle_10x10_1.png
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=200, bbox_inches="tight")

    # show=True:
    #   display the figure interactively
    #
    # show=False:
    #   close the figure after saving
    #
    # Benchmark scripts usually use show=False.
    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax