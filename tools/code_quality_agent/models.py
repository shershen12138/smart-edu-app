"""评测智能体的数据契约：题目规格、缺陷、单题结果、学生报告、评分维度。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 五个内置评分维度。量表文件可以为每个维度改名或调权重。
KNOWLEDGE = "knowledge"
SYNTAX = "syntax"
BOUNDARY = "boundary"
LOGIC = "logic"
STYLE = "style"
STRUCTURE = "structure"
READABILITY = "readability"

DIMENSION_LABELS = {
    KNOWLEDGE: "知识点覆盖",
    SYNTAX: "语法与静态缺陷",
    BOUNDARY: "边界与健壮性",
    LOGIC: "题意一致性",
    STYLE: "代码规范",
    STRUCTURE: "代码结构",
    READABILITY: "可读性",
}


@dataclass(frozen=True)
class Issue:
    """一条可定位到行号的缺陷。"""

    task_id: str
    line: int
    message: str
    dimension: str
    severity: str = "warning"  # fatal / error / warning / convention
    source: str = "ast"  # ast / rule / pylint / syntax
    advice: str = ""

    def as_cell_text(self) -> str:
        return f"第 {self.line} 行：{self.message}"


@dataclass(frozen=True)
class TaskSpec:
    """一道题（一个必做函数）的规格。"""

    task_id: str
    title: str
    points: tuple[str, ...]  # 知识点标签
    rules: tuple[str, ...] = ()  # 语义规则名（rules.RULES 的键）


@dataclass
class TaskResult:
    """单个函数的分析结果。"""

    spec: TaskSpec
    parsed: bool
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def defects(self) -> list[Issue]:
        return [i for i in self.issues if i.dimension != STYLE]

    @property
    def has_error(self) -> bool:
        return any(i.severity in {"fatal", "error"} for i in self.issues)


@dataclass
class Dimension:
    key: str
    label: str
    weight: float


@dataclass
class StudentReport:
    name: str
    path: str
    results: list[TaskResult]
    scores: dict[str, float]
    total: float
    style_notes: list[str] = field(default_factory=list)

    def score_of(self, dimension_key: str) -> float:
        return round(self.scores.get(dimension_key, 0.0), 1)

    @property
    def grade(self) -> str:
        total = self.total
        if total >= 90:
            return "A"
        if total >= 80:
            return "B"
        if total >= 70:
            return "C"
        if total >= 60:
            return "D"
        return "E"
