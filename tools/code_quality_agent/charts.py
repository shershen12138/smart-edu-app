"""雷达图：每个学生一张，维度取评分量表的每一项。"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
from matplotlib import pyplot as plt

from . import models

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def student_slug(name: str, index: int) -> str:
    digits = re.sub(r"\D", "", name)
    return f"student{digits}" if digits else f"student{index:02d}"


def render(
    student,
    dimensions: list[models.Dimension],
    output: Path,
) -> Path:
    labels = [dim.label for dim in dimensions]
    values = [student.scores.get(dim.key, 0.0) for dim in dimensions]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    closed_values = values + [values[0]]
    closed_angles = angles + [angles[0]]

    figure = plt.figure(figsize=(5.6, 5.2), dpi=150)
    axes = figure.add_subplot(111, polar=True)
    axes.set_theta_offset(np.pi / 2)
    axes.set_theta_direction(-1)
    axes.set_ylim(0, 100)
    axes.set_xticks(angles)
    axes.set_xticklabels(labels, fontsize=9)
    axes.set_yticks([20, 40, 60, 80, 100])
    axes.set_yticklabels([])
    axes.grid(color="#d6dae1", linewidth=0.8)
    axes.spines["polar"].set_color("#c9ced6")

    axes.plot(closed_angles, closed_values, color="#2f6feb", linewidth=2, zorder=3)
    axes.fill(closed_angles, closed_values, color="#2f6feb", alpha=0.22, zorder=2)
    for angle, value in zip(angles, values):
        axes.text(
            angle,
            max(value * 0.62, 9),
            f"{value:.0f}",
            ha="center",
            va="center",
            fontsize=8.5,
            color="#1f3f8f",
            zorder=4,
        )

    axes.set_title(
        f"{student.name} 代码完成度（总分 {student.total:.1f} / 100）",
        fontsize=11,
        pad=18,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return output
