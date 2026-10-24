"""LangGraph 编排的评测 Agent。

把静态评测拆成带状态图的多步流程，而不是一条顺序函数调用：

```text
START → prepare ─┬─(整文件可解析)→ lint ─┐
                 └─(不可解析)───────────┴→ tasks → notes → score → END
```

- 节点由 `stages` 提供，每个节点只读自己需要的状态字段；
- `lint` 是条件分支：整份文件无法解析时跳过 pylint，因为此时行号不可信；
- 图本身无状态，编译一次后跨请求复用。

这样拆分后，单步可以单独测试，也可以在任意节点后插入 LLM 节点（例如生成
学习建议）而不改动评分逻辑。
"""

from __future__ import annotations

# 导入 langgraph 时会链式加载 checkpoint 序列化器，向 stderr 打印一条
# LangChainPendingDeprecationWarning（与 allowed_objects 的默认值有关）。
# 该提示不受 warnings 过滤器与 -W ignore 控制，属第三方一次性输出，
# 只在进程首次导入时出现，不影响评测结果。
from langgraph.graph import END, START, StateGraph

from . import stages
from .stages import ReviewState

LINT = "lint"
SKIP_LINT = "tasks"
NODE_NAMES = ("prepare", LINT, "tasks", "notes", "score")


def _route_after_prepare(state: ReviewState) -> str:
    """整份文件解析失败时跳过 pylint：无法给出可信行号。"""
    return LINT if state.get("module_ast") is not None else SKIP_LINT


def build_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("prepare", stages.prepare)
    graph.add_node(LINT, stages.run_lint)
    graph.add_node("tasks", stages.build_tasks)
    graph.add_node("notes", stages.collect_notes)
    graph.add_node("score", stages.score)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare", _route_after_prepare, {LINT: LINT, SKIP_LINT: SKIP_LINT}
    )
    graph.add_edge(LINT, "tasks")
    graph.add_edge("tasks", "notes")
    graph.add_edge("notes", "score")
    graph.add_edge("score", END)
    return graph.compile()


_COMPILED = None


def compiled_graph():
    """编译一次后复用；图无状态，可以跨线程共享。"""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    return _COMPILED


def invoke(state: ReviewState) -> ReviewState:
    """执行评测图，返回填满各阶段结果的最终状态。"""
    return compiled_graph().invoke(state)


def node_names() -> tuple[str, ...]:
    """图的节点顺序，供自检与文档使用。"""
    return NODE_NAMES
