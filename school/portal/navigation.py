"""统一的“返回上一层”目标计算。

页面上的“返回”按钮不应该写死跳到某个固定页面——同一个页面从不同入口进来时，
上一级是不一样的（例如“学生结果”既可能来自统计报表，也可能来自班级名单）。
这里用会话保存一条最近访问的页面路径链，由 ``common_views.page`` 在每次渲染页面时维护：

- 正常点击链接进入新页面：把当前页压到链尾，返回目标就是它的前一项；
- 点击页面上的“返回”按钮时链接带 ``_nav=back``：到达目标页后把刚离开的那页从链尾裁掉，
  避免 A→B→返回→A→返回→B 来回跳；
- 会话里没有历史（直接打开链接、浏览器前进后退、跨标签页）时，退回该页面固定的上一级。

这样“返回”永远回到点进来之前的那一页，而不是另一个模块的首页。
"""

from __future__ import annotations

NAV_KEY = 'portal_nav_chain'
BACK_PARAM = '_nav'
MAX_DEPTH = 20


def _chain(request) -> list[str]:
    session = getattr(request, 'session', None)
    if session is None:
        return []
    value = session.get(NAV_KEY)
    return list(value) if isinstance(value, list) else []


def _current_key(request) -> str:
    """当前页面的标识：完整路径（含查询串），但不含返回标记本身。"""
    params = request.GET.copy()
    params.pop(BACK_PARAM, None)
    query = params.urlencode()
    return f'{request.path}?{query}' if query else request.path


def _is_back(request) -> bool:
    return BACK_PARAM in request.GET


def _with_marker(url: str) -> str:
    separator = '&' if '?' in url else '?'
    return f'{url}{separator}{BACK_PARAM}=back'


def back_target(request, default: str) -> str:
    """返回按钮的目标地址：优先取访问链里的上一页，没有历史时用 default。"""
    chain = _chain(request)
    current = _current_key(request)
    target = ''
    if _is_back(request) and len(chain) >= 2 and chain[-2] == current:
        # 正在往回走：再往前退一层，跳过刚离开的那页
        target = chain[-3] if len(chain) >= 3 else ''
    elif chain and chain[-1] != current:
        target = chain[-1]
    elif len(chain) >= 2:
        target = chain[-2]
    return _with_marker(target or default)


def track(request) -> None:
    """在渲染页面前记录访问链；重复渲染同一页不会重复入栈。"""
    session = getattr(request, 'session', None)
    if session is None:
        return
    current = _current_key(request)
    chain = _chain(request)
    if _is_back(request) and len(chain) >= 2 and chain[-2] == current:
        chain.pop()
    elif chain and chain[-1] == current:
        return
    elif current in chain:
        chain = chain[: chain.index(current) + 1]
    else:
        chain.append(current)
    session[NAV_KEY] = chain[-MAX_DEPTH:]
