'use strict';
document.querySelector('[data-select-all]')?.addEventListener('change', (event) => {
  document.querySelectorAll('input[name="selected"]').forEach((box) => { box.checked = event.target.checked; });
});
const refresh = document.querySelector('[data-refresh]');
if (refresh) window.setTimeout(() => window.location.reload(), Number(refresh.dataset.refresh));
document.querySelectorAll('.sidebar nav a').forEach((link) => {
  if (link.pathname === location.pathname) link.setAttribute('aria-current', 'page');
});
document.querySelector('form[action="/students/batch/"]')?.addEventListener('submit', (event) => {
  if (event.target.elements.action.value === 'delete' && !window.confirm('永久删除所选学生账号，以及他们的提交、成绩和相关文件？此操作无法恢复。')) event.preventDefault();
});

const gradingModes = document.querySelectorAll('input[name="grading_mode"]');
if (gradingModes.length) {
  const packageInput = document.getElementById('id_package_file');
  const packageRow = packageInput?.closest('p');
  const packageLabel = packageRow?.querySelector('label');
  const packageHelp = packageRow?.querySelector('.helptext');
  const updateUploadFields = () => {
    const mode = document.querySelector('input[name="grading_mode"]:checked')?.value;
    const manual = mode === 'manual';
    if (packageLabel) packageLabel.textContent = manual ? '非机器批阅包：' : '机器批阅包：';
    if (packageHelp) {
      packageHelp.textContent = manual
        ? '上传包含一份题目DOCX和学生所需数据文件的ZIP，不超过 10 MB。'
        : '上传题目DOCX、sample*.py、gold.py、func_info_list.txt和data目录组成的ZIP，不超过 10 MB。';
    }
  };
  gradingModes.forEach((field) => field.addEventListener('change', updateUploadFields));
  updateUploadFields();
}

// 加载遮罩：链接跳转与表单提交时显示，避免长请求期间页面毫无反馈。
// 延迟 120ms 再出现，本地快速跳转不会闪一下；30s 兜底隐藏，防止下载类操作卡住。
const loadingOverlay = document.querySelector('[data-loading]');
const loadingLabel = loadingOverlay?.querySelector('.loading-label');
let loadingShowTimer = 0;
let loadingHideTimer = 0;

const showLoading = (label) => {
  if (!loadingOverlay) return;
  window.clearTimeout(loadingShowTimer);
  window.clearTimeout(loadingHideTimer);
  loadingShowTimer = window.setTimeout(() => {
    if (loadingLabel) loadingLabel.textContent = label || '正在加载…';
    loadingOverlay.hidden = false;
  }, 120);
  loadingHideTimer = window.setTimeout(() => { loadingOverlay.hidden = true; }, 30000);
};

const hideLoading = () => {
  window.clearTimeout(loadingShowTimer);
  window.clearTimeout(loadingHideTimer);
  if (loadingOverlay) loadingOverlay.hidden = true;
};

const skipLoading = (element) => element.closest('[data-no-loading]') !== null;

document.addEventListener('submit', (event) => {
  if (event.defaultPrevented || skipLoading(event.target)) return;
  showLoading(event.target.dataset.loading || '正在提交…');
});

document.addEventListener('click', (event) => {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]');
  if (!link || skipLoading(link)) return;
  if (link.target && link.target !== '_self') return;
  if (link.hasAttribute('download')) return;
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) return;
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  if (url.pathname === window.location.pathname && url.search === window.location.search) return;
  showLoading(link.dataset.loading || '正在加载…');
});

window.addEventListener('pageshow', (event) => {
  if (event.persisted) hideLoading();
});

// 首屏加载：脚本以 defer 执行时页面通常还在下载资源，期间同样给出加载反馈。
// 复用 120ms 延迟与 pageshow 兜底：页面快速就绪时 hideLoading 会清掉未触发的显示定时器，不会闪烁。
if (document.readyState !== 'complete') {
  showLoading('正在加载…');
  window.addEventListener('load', hideLoading, { once: true });
}

// 雷达图：悬停或键盘聚焦某个维度时，在数据点上方显示名称与得分
const initRadar = () => {
  document.querySelectorAll('[data-radar]').forEach((wrap) => {
    const tip = wrap.querySelector('.radar-tooltip');
    if (!tip) return;
    const place = (axis) => {
      const point = axis.querySelector('.radar-point');
      if (!point) return;
      const wrapRect = wrap.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const x = pointRect.left + pointRect.width / 2 - wrapRect.left;
      tip.style.left = `${Math.min(Math.max(x, 70), wrapRect.width - 70)}px`;
      tip.style.top = `${pointRect.top - wrapRect.top - 10}px`;
      tip.textContent = '';
      const name = document.createElement('strong');
      name.textContent = axis.dataset.label || '';
      const level = axis.dataset.level ? `（${axis.dataset.level} 级）` : '';
      tip.append(
        name,
        ` ${axis.dataset.score || '0'} 分${level} · 权重 ${axis.dataset.weight || '0'}%`,
      );
      tip.hidden = false;
    };
    wrap.querySelectorAll('.radar-axis').forEach((axis) => {
      axis.addEventListener('mouseenter', () => place(axis));
      axis.addEventListener('mousemove', () => place(axis));
      axis.addEventListener('focus', () => place(axis));
      axis.addEventListener('mouseleave', () => {
        tip.hidden = true;
      });
      axis.addEventListener('blur', () => {
        tip.hidden = true;
      });
    });
  });
};

initRadar();

// 知识图谱：ECharts 力导向/放射双布局，支持拖拽缩放、搜索筛选、悬停簇高亮与详情面板
const initKnowledgeGraph = () => {
  const wrap = document.querySelector('[data-kg]');
  const dataNode = document.getElementById('kg-data');
  if (!wrap || !dataNode || typeof echarts === 'undefined') return;

  const graph = JSON.parse(dataNode.textContent);
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const chartDom = wrap.querySelector('[data-kg-chart]');
  const searchInput = wrap.querySelector('[data-kg-search]');
  const levelsBox = wrap.querySelector('[data-kg-levels]');
  const catsBox = wrap.querySelector('[data-kg-cats]');
  const layoutGroup = wrap.querySelector('[data-kg-layout-group]');
  const edgeLabelToggle = wrap.querySelector('[data-kg-edge-labels]');
  const edgeArrowToggle = wrap.querySelector('[data-kg-edge-arrows]');
  const resetButton = wrap.querySelector('[data-kg-reset]');
  const statsEl = wrap.querySelector('[data-kg-stats]');
  const legendEl = wrap.querySelector('[data-kg-legend]');
  const emptyEl = wrap.querySelector('[data-kg-empty]');
  const emptyText = wrap.querySelector('[data-kg-empty-text]');
  const clearButton = wrap.querySelector('[data-kg-clear]');
  const panel = wrap.querySelector('[data-kg-panel]');
  const panelBody = wrap.querySelector('[data-kg-panel-body]');
  const panelClose = wrap.querySelector('[data-kg-panel-close]');

  const LS_KEYS = { layout: 'kg-layout', labels: 'kg-edge-labels', arrows: 'kg-edge-arrows' };
  const store = {
    get(key) { try { return window.localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch { /* 隐私模式下忽略 */ } },
  };

  // 取自用户色卡的五色：浅蓝 / 珊瑚粉 / 黄 / 浅紫粉 / 玫红
  // 根节点用首色的浅版，保持只有这五个色相
  const CAT_COLORS = {
    root: '#c5d8ea',
    基础语法与数据类型: '#90b4d7',
    流程控制与函数: '#edb2a3',
    面向对象: '#ead564',
    异常处理与文件操作: '#da9ebb',
    常用标准库与模块化: '#cf7a98',
  };

  const state = {
    levels: new Set(['1', '2', '3', '4']),
    cats: new Set(),
    query: '',
    layout: store.get(LS_KEYS.layout) === 'force' ? 'force' : 'radial',
    edgeLabels: store.get(LS_KEYS.labels) === '1',
    edgeArrows: store.get(LS_KEYS.arrows) === '1',
    focusCat: null,
    zoom: 1,
  };

  // 与白色按比例混合，返回十六进制色（可嵌套调用）
  const mixWhite = (hex, ratio) => {
    const value = parseInt(hex.slice(1), 16);
    const channel = (shift) => Math.round(((value >> shift) & 255) + (255 - ((value >> shift) & 255)) * ratio);
    return `#${[16, 8, 0].map((shift) => channel(shift).toString(16).padStart(2, '0')).join('')}`;
  };

  const baseColorOf = (node) => {
    const base = CAT_COLORS[node.category] || CAT_COLORS.root;
    if (node.level <= 2) return base;
    return mixWhite(base, node.level === 3 ? 0.24 : 0.44);
  };

  // 每个节点用径向渐变：中心更亮、边缘略深，全部无描边
  const nodeFill = (node) => {
    const base = baseColorOf(node);
    return new echarts.graphic.RadialGradient(0.35, 0.3, 0.88, [
      { offset: 0, color: mixWhite(base, node.level >= 3 ? 0.55 : 0.38) },
      { offset: 1, color: mixWhite(base, 0.04) },
    ]);
  };

  const baseSize = (node) => {
    if (node.level === 1) return 64;
    if (node.level === 2) return Math.round((10 + node.importance * 4) * 1.4);
    return 10 + node.importance * 4;
  };

  const searchHit = (node) => {
    if (!state.query) return false;
    return `${node.name}${node.summary}`.toLowerCase().includes(state.query);
  };

  const visibleNode = (node) => state.levels.has(String(node.level))
    && state.cats.has(node.category)
    && (!state.query || searchHit(node));

  // contains 边构成的父子表，用于模块簇高亮与详情面板
  const childrenMap = new Map(graph.nodes.map((node) => [node.id, []]));
  graph.edges.forEach((edge) => {
    if (edge.type === 'contains') childrenMap.get(edge.source)?.push(edge.target);
  });
  const neighborMap = new Map(graph.nodes.map((node) => [node.id, new Set([node.id])]));
  graph.edges.forEach((edge) => {
    neighborMap.get(edge.source)?.add(edge.target);
    neighborMap.get(edge.target)?.add(edge.source);
  });
  const descendantsOf = (id) => {
    const result = new Set([id]);
    const queue = [id];
    while (queue.length) {
      childrenMap.get(queue.pop())?.forEach((child) => {
        if (!result.has(child)) {
          result.add(child);
          queue.push(child);
        }
      });
    }
    return result;
  };

  const chart = echarts.init(chartDom);

  // 图例聚焦：把模块名换成模块 id 后取整簇子孙
  const focusKeepIds = () => {
    if (!state.focusCat) return null;
    const module = graph.modules.find((item) => item.name === state.focusCat);
    return module ? descendantsOf(module.id) : null;
  };

  const buildNodeItem = (node, visibleIds, keepIds) => {
    const visible = visibleIds.has(node.id);
    const hit = searchHit(node);
    const dimmed = keepIds !== null && visible && !keepIds.has(node.id);
    const showLabel = visible && (node.level <= 2 || state.zoom >= 0.8);
    return {
      id: node.id,
      name: node.name,
      x: node.x,
      y: node.y,
      symbolSize: baseSize(node) * (hit ? 1.3 : 1),
      itemStyle: {
        color: nodeFill(node),
        borderWidth: 0,
        borderColor: 'transparent',
        opacity: visible ? (dimmed ? 0.15 : 1) : 0,
        shadowBlur: hit ? 16 : 0,
        shadowColor: hit ? 'rgba(80, 95, 115, .5)' : 'transparent',
      },
      label: {
        show: showLabel,
        fontSize: node.level === 1 ? 16 : node.level === 2 ? 14 : 11,
        fontWeight: node.level <= 2 ? 700 : 400,
        color: node.level <= 2 ? '#3d4a57' : '#5a6673',
      },
      cursor: visible ? 'pointer' : 'default',
    };
  };

  const buildEdgeItem = (edge, visibleIds, keepIds) => {
    const visible = visibleIds.has(edge.source) && visibleIds.has(edge.target);
    const kept = keepIds === null || (visibleIds.has(edge.source) && keepIds.has(edge.source) && keepIds.has(edge.target));
    const arrow = state.edgeArrows && edge.type === 'prerequisite';
    return {
      source: edge.source,
      target: edge.target,
      type: edge.type,
      reason: edge.reason || '',
      lineStyle: {
        color: edge.type === 'contains' ? '#dfe3e7' : '#b8c0c9',
        width: edge.type === 'contains' ? 1 : edge.type === 'contrast' ? 1.5 : 1.8,
        type: edge.type === 'contrast' ? 'dashed' : 'solid',
        opacity: visible ? (kept ? 0.85 : 0.06) : 0,
      },
      symbol: arrow ? ['none', 'arrow'] : ['none', 'none'],
      symbolSize: arrow ? 7 : 0,
      label: {
        show: visible && kept && state.edgeLabels && state.zoom >= 1.2 && edge.type !== 'contains',
        formatter: graph.relationShort[edge.type] || edge.type,
        fontSize: 10,
        color: '#6b7280',
        backgroundColor: 'rgba(250, 250, 250, .85)',
        padding: [1, 4],
        borderRadius: 3,
      },
    };
  };

  const buildSeriesPatch = (keepIds) => {
    const visibleIds = new Set(graph.nodes.filter(visibleNode).map((node) => node.id));
    return {
      layout: state.layout === 'force' ? 'force' : 'none',
      force: { repulsion: 260, edgeLength: [70, 130], gravity: 0.08, friction: 0.25 },
      data: graph.nodes.map((node) => buildNodeItem(node, visibleIds, keepIds)),
      edges: graph.edges.map((edge) => buildEdgeItem(edge, visibleIds, keepIds)),
    };
  };

  const updateStats = (visibleIds) => {
    const visibleEdges = graph.edges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
    ).length;
    if (statsEl) {
      statsEl.textContent = `节点 ${visibleIds.size} / ${graph.nodes.length} · 关系 ${visibleEdges} / ${graph.edges.length}`;
    }
  };

  const render = (keepIds = null) => {
    const visibleIds = new Set(graph.nodes.filter(visibleNode).map((node) => node.id));
    // data / edges / layout 都是 series 级配置，必须包在 series 数组里，
    // 否则 setOption 会把它当成顶层 option 忽略掉，筛选后画布不会重画。
    chart.setOption({ series: [buildSeriesPatch(keepIds)] });
    updateStats(visibleIds);

    const noFilterHit = visibleIds.size === 0;
    const noSearchHit = state.query !== '' && !graph.nodes.some(searchHit);
    if (emptyEl && emptyText) {
      emptyEl.hidden = !(noFilterHit || noSearchHit);
      emptyText.textContent = noSearchHit ? '未找到相关知识点' : '没有符合条件的知识点，试试清空筛选';
    }
  };

  // 缩放联动：知识点标签在 zoom≥0.8 时显示，关系标签在 zoom≥1.2 且开关打开时显示
  chart.on('graphRoam', (event) => {
    if (event.zoom) {
      state.zoom = Math.min(3, Math.max(0.3, state.zoom * event.zoom));
      render(focusKeepIds());
    }
  });

  const centerOn = (node) => {
    if (state.layout !== 'radial') return;
    const xs = graph.nodes.map((item) => item.x);
    const ys = graph.nodes.map((item) => item.y);
    const minX = Math.min(...xs);
    const width = Math.max(Math.max(...xs) - minX, 1);
    const minY = Math.min(...ys);
    const height = Math.max(Math.max(...ys) - minY, 1);
    const px = ((node.x - minX) / width) * 100;
    const py = ((node.y - minY) / height) * 100;
    chart.setOption({ series: [{ center: [`${px}%`, `${py}%`], zoom: 1.4 }] });
    state.zoom = 1.4;
  };

  const resetView = () => {
    state.zoom = 1;
    state.focusCat = null;
    chart.setOption({ series: [{ center: ['50%', '50%'], zoom: 1 }] });
    render();
  };

  resetButton?.addEventListener('click', resetView);

  // 悬停高亮：普通节点高亮直接邻居；大知识点悬停高亮整簇（含全部子孙）
  chart.on('mouseover', (params) => {
    if (params.dataType !== 'node') return;
    const node = nodesById.get(params.data.id);
    if (!node || !visibleNode(node)) return;
    const keep = node.level === 2 ? descendantsOf(node.id) : neighborMap.get(node.id);
    render(keep);
  });
  chart.on('mouseout', (params) => {
    if (params.dataType !== 'node') return;
    render(focusKeepIds());
  });

  // 详情面板：前置 / 后续 / 包含的子知识点
  const relationsOf = (id) => {
    const prereq = [];
    const next = [];
    const children = [];
    graph.edges.forEach((edge) => {
      if (edge.type === 'prerequisite' && edge.target === id) prereq.push(nodesById.get(edge.source));
      if (edge.type === 'prerequisite' && edge.source === id) next.push(nodesById.get(edge.target));
      if (edge.type === 'contains' && edge.source === id) children.push(nodesById.get(edge.target));
    });
    return { prereq: prereq.filter(Boolean), next: next.filter(Boolean), children: children.filter(Boolean) };
  };

  const showPanel = (node) => {
    if (!panel || !panelBody) return;
    const { prereq, next, children } = relationsOf(node.id);
    const list = (items, empty) => (items.length
      ? `<ul class="kg-panel-list">${items.map((item) => `<li><button type="button" data-kg-jump="${item.id}">${item.name}</button></li>`).join('')}</ul>`
      : `<p class="kg-panel-empty">${empty}</p>`);
    const moduleLine = node.level === 1 ? '根节点' : `所属模块：${node.category}`;
    panelBody.innerHTML = `
      <h3 class="kg-panel-title">${node.name}</h3>
      <p class="kg-panel-meta">${moduleLine} · 重要度 ${'★'.repeat(node.importance)}${'☆'.repeat(5 - node.importance)}</p>
      <p>${node.summary}</p>
      <h4>前置知识点</h4>${list(prereq, '没有前置要求')}
      <h4>后续知识点</h4>${list(next, '暂无直接后续')}
      <h4>包含的知识点</h4>${list(children, node.level === 4 ? '已是叶子节点' : '暂无')}
    `;
    panel.hidden = false;
    panelBody.querySelectorAll('[data-kg-jump]').forEach((button) => {
      button.addEventListener('click', () => focusNode(button.dataset.kgJump));
    });
  };

  const focusNode = (id) => {
    const node = nodesById.get(id);
    if (!node) return;
    state.cats.add(node.category);
    state.levels.add(String(node.level));
    state.query = '';
    if (searchInput) searchInput.value = '';
    catsBox?.querySelectorAll('input').forEach((box) => {
      if (box.dataset.cat === node.category) box.checked = true;
    });
    levelsBox?.querySelectorAll('input').forEach((box) => {
      if (box.value === String(node.level)) box.checked = true;
    });
    render();
    centerOn(node);
    showPanel(node);
  };

  chart.on('click', (params) => {
    if (params.dataType === 'node') showPanel(nodesById.get(params.data.id));
  });

  panelClose?.addEventListener('click', () => { panel.hidden = true; });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && panel) panel.hidden = true;
  });

  // 搜索：回车定位第一个结果
  searchInput?.addEventListener('input', () => {
    state.query = searchInput.value.trim().toLowerCase();
    render();
  });
  searchInput?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || !state.query) return;
    const first = graph.nodes.find((node) => visibleNode(node) && searchHit(node));
    if (first) centerOn(first);
  });

  levelsBox?.querySelectorAll('input').forEach((box) => {
    box.addEventListener('change', () => {
      if (box.checked) state.levels.add(box.value); else state.levels.delete(box.value);
      render();
    });
  });

  // 模块筛选与图例共用同一份分类数据
  const moduleCats = graph.modules.map((module) => module.name);
  const buildToggles = () => {
    if (catsBox) {
      catsBox.innerHTML = '';
      state.cats.add('root');
      moduleCats.forEach((name) => {
        state.cats.add(name);
        const label = document.createElement('label');
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = true;
        box.dataset.cat = name;
        box.addEventListener('change', () => {
          if (box.checked) state.cats.add(name); else state.cats.delete(name);
          render();
        });
        const dot = document.createElement('span');
        dot.className = 'kg-dot';
        dot.style.background = CAT_COLORS[name];
        label.append(box, dot, document.createTextNode(name));
        catsBox.append(label);
      });
    }
    if (legendEl) {
      legendEl.innerHTML = '';
      moduleCats.forEach((name) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'kg-legend-item';
        const dot = document.createElement('span');
        dot.className = 'kg-dot';
        dot.style.background = CAT_COLORS[name];
        item.append(dot, document.createTextNode(name));
        item.addEventListener('click', () => {
          state.focusCat = state.focusCat === name ? null : name;
          legendEl.querySelectorAll('.kg-legend-item').forEach((el) => el.classList.remove('kg-legend-active'));
          if (state.focusCat) item.classList.add('kg-legend-active');
          render(focusKeepIds());
        });
        legendEl.append(item);
      });
    }
  };

  const syncLayoutButtons = () => {
    layoutGroup?.querySelectorAll('[data-kg-layout]').forEach((button) => {
      button.classList.toggle('kg-seg-active', button.dataset.kgLayout === state.layout);
    });
  };

  layoutGroup?.querySelectorAll('[data-kg-layout]').forEach((button) => {
    button.addEventListener('click', () => {
      state.layout = button.dataset.kgLayout;
      state.zoom = 1;
      store.set(LS_KEYS.layout, state.layout);
      syncLayoutButtons();
      resetView();
    });
  });

  edgeLabelToggle?.addEventListener('change', () => {
    state.edgeLabels = edgeLabelToggle.checked;
    store.set(LS_KEYS.labels, state.edgeLabels ? '1' : '0');
    render();
  });
  edgeArrowToggle?.addEventListener('change', () => {
    state.edgeArrows = edgeArrowToggle.checked;
    store.set(LS_KEYS.arrows, state.edgeArrows ? '1' : '0');
    render();
  });

  clearButton?.addEventListener('click', () => {
    state.query = '';
    if (searchInput) searchInput.value = '';
    state.levels = new Set(['1', '2', '3', '4']);
    state.cats = new Set(['root', ...moduleCats]);
    levelsBox?.querySelectorAll('input').forEach((box) => { box.checked = true; });
    catsBox?.querySelectorAll('input').forEach((box) => { box.checked = true; });
    render();
  });

  // 索引卡片定位：聚焦该模块并打开详情面板
  wrap.closest('.content')?.querySelectorAll('[data-kg-focus]').forEach((button) => {
    button.addEventListener('click', () => focusNode(button.dataset.kgFocus));
  });

  // 组件清理：离开页面时释放实例与监听，避免内存泄漏
  const resizeObserver = new ResizeObserver(() => chart.resize());
  resizeObserver.observe(chartDom);
  window.addEventListener('pagehide', () => {
    resizeObserver.disconnect();
    chart.dispose();
  }, { once: true });

  if (edgeLabelToggle) edgeLabelToggle.checked = state.edgeLabels;
  if (edgeArrowToggle) edgeArrowToggle.checked = state.edgeArrows;
  syncLayoutButtons();
  buildToggles();
  chart.setOption({
    color: Object.values(CAT_COLORS),
    tooltip: {
      confine: true,
      textStyle: { fontSize: 12 },
      formatter: (params) => {
        if (params.dataType === 'edge') {
          const label = graph.relationLabels[params.data.type] || params.data.type;
          return `${label}${params.data.reason ? `：${params.data.reason}` : ''}`;
        }
        return `<strong>${params.data.name}</strong><br>${nodesById.get(params.data.id)?.summary || ''}`;
      },
    },
    series: [{
      type: 'graph',
      layout: state.layout === 'force' ? 'force' : 'none',
      roam: true,
      draggable: true,
      force: { repulsion: 260, edgeLength: [70, 130], gravity: 0.08, friction: 0.25 },
      scaleLimit: { min: 0.3, max: 3 },
      ...buildSeriesPatch(null),
    }],
  });
  render(null);
};

initKnowledgeGraph();
