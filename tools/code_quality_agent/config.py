"""路径与课程配置。

约定：数据放在仓库 `data/<课程>/`，题目材料放在
`exercise requirements/<课程>/<课程>/`（含 func_info_list.txt、docx、gold.py、data/）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
EXERCISE_DIR = ROOT / "exercise requirements"
REPORT_DIR = ROOT / "reports"

# 课程键 -> 数据目录名 / 工作量表文件名
COURSES: dict[str, dict[str, str]] = {
    "03-列表": {"data": "03-列表", "rubric": "03评分量表.md"},
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class CourseContext:
    course: str
    student_dir: Path
    exercise_dir: Path
    rubric_file: Path
    report_dir: Path


def _locate_exercise_dir(course: str) -> Path:
    """题目包目录允许有一层同名嵌套，也存在历史手工解压的变体。"""
    base = EXERCISE_DIR / course
    if (base / "func_info_list.txt").is_file():
        return base
    candidates = sorted(base.glob("*/func_info_list.txt")) if base.is_dir() else []
    if candidates:
        return candidates[0].parent
    raise ConfigError(
        f"未找到 {course} 的题目包（需要 func_info_list.txt）：{base}"
    )


def build_context(course: str, rubric_override: Path | None = None) -> CourseContext:
    if course not in COURSES:
        raise ConfigError(f"未配置的课程：{course}，可选：{', '.join(COURSES)}")
    meta = COURSES[course]
    student_dir = DATA_DIR / meta["data"]
    if not student_dir.is_dir():
        raise ConfigError(f"未找到学生代码目录：{student_dir}")
    rubric_file = rubric_override or (DATA_DIR / meta["rubric"])
    return CourseContext(
        course=course,
        student_dir=student_dir,
        exercise_dir=_locate_exercise_dir(course),
        rubric_file=rubric_file,
        report_dir=REPORT_DIR / course,
    )
