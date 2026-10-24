/* 交互式原型共享脚本：示例数据 + 交互组件（无外部依赖，可离线打开） */
(function () {
  'use strict';

  /* ---------------- 示例数据（均为虚构，不代表任何真实班级与学生） ---------------- */
  const DATA = {
    classes: [
      { code: 'PY-2026-01', name: 'Python 教学班', course: 'Python 程序设计', term: '2026 秋季', count: 38, archived: false },
      { code: 'PY-2026-02', name: 'Python 提高班', course: 'Python 程序设计', term: '2026 秋季', count: 24, archived: false },
      { code: 'PY-2025-03', name: '2025 春学期班', course: 'Python 程序设计', term: '2025 春季', count: 41, archived: true },
    ],
    students: [
      { no: '20260101', name: '示例学生甲', cls: 'PY-2026-01', active: true },
      { no: '20260102', name: '示例学生乙', cls: 'PY-2026-01', active: true },
      { no: '20260103', name: '示例学生丙', cls: 'PY-2026-01', active: true },
      { no: '20260104', name: '示例学生丁', cls: 'PY-2026-01', active: false },
      { no: '20260105', name: '示例学生戊', cls: 'PY-2026-01', active: true },
      { no: '20260106', name: '示例学生己', cls: 'PY-2026-02', active: true },
      { no: '20260107', name: '示例学生庚', cls: 'PY-2026-02', active: true },
      { no: '20260108', name: '示例学生辛', cls: 'PY-2026-02', active: true },
      { no: '20260109', name: '示例学生壬', cls: 'PY-2026-02', active: true },
      { no: '20260110', name: '示例学生癸', cls: 'PY-2026-02', active: false },
      { no: '20260111', name: '示例学生子', cls: '未分班', active: true },
      { no: '20260112', name: '示例学生丑', cls: '未分班', active: true },
    ],
    dicts: [
      { key: 'grading_mode', name: '批阅方式', items: ['机器批阅', '非机器批阅'] },
      { key: 'role', name: '系统身份', items: ['管理员', '教师', '学生'] },
      { key: 'entry_status', name: '批阅状态', items: ['等待批阅', '批阅中', '已完成', '批阅异常'] },
    ],
    homeworks: [
      { id: 1, title: '03-列表习题说明', mode: 'automatic', deadline: '2026-11-02 23:59', submitted: 5, total: 38, status: '进行中' },
      { id: 2, title: '第 10 章综合练习', mode: 'manual', deadline: '2026-11-09 23:59', submitted: 2, total: 38, status: '进行中' },
    ],
    entries: [
      { id: 1, hw: 1, no: '20260101', name: '示例学生甲', attempt: 2, status: '已完成', cases: '15 / 15', score: 100 },
      { id: 2, hw: 1, no: '20260102', name: '示例学生乙', attempt: 1, status: '已完成', cases: '13 / 15', score: 86.7 },
      { id: 3, hw: 1, no: '20260103', name: '示例学生丙', attempt: 1, status: '已完成', cases: '11 / 15', score: 73.3 },
      { id: 4, hw: 1, no: '20260105', name: '示例学生戊', attempt: 3, status: '批阅异常', cases: '—', score: null },
      { id: 5, hw: 1, no: '20260106', name: '示例学生己', attempt: 1, status: '等待批阅', cases: '—', score: null },
    ],
    questions: [
      { fn: 'func301', title: '列表合并与截取', full: 6, cases: '3 / 3' },
      { fn: 'func302', title: '中位数计算', full: 8, cases: '2 / 3' },
      { fn: 'func303', title: '回文判断', full: 6, cases: '3 / 3' },
      { fn: 'func304', title: '去重保序', full: 6, cases: '2 / 3' },
      { fn: 'func305', title: '素数筛选', full: 8, cases: '3 / 3' },
    ],
    rubric: [
      { key: 'D1', label: '知识点覆盖与运用', weight: 25, value: 4.5, tips: '本题要求的语法点是否出现且用对' },
      { key: 'D2', label: '语法与静态正确性', weight: 15, value: 5, tips: '能否通过解析与 lint 检查' },
      { key: 'D3', label: '边界与健壮性', weight: 15, value: 3, tips: '极端输入是否崩溃或死循环' },
      { key: 'D4', label: '逻辑与算法正确性', weight: 20, value: 4, tips: '解题路径是否符合题意' },
      { key: 'D5', label: '题意一致性与输出契约', weight: 15, value: 3.5, tips: '返回值类型、结构、顺序是否对' },
      { key: 'D6', label: '代码规范与可读性', weight: 10, value: 4, tips: '命名、注释、拆分与可维护性' },
    ],
  };

  /* ---------------- 通用工具 ---------------- */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));

  function toast(text, ms) {
    let box = $('#toast');
    if (!box) {
      box = document.createElement('div');
      box.id = 'toast';
      document.body.appendChild(box);
    }
    const item = document.createElement('div');
    item.className = 'toast';
    item.textContent = text;
    box.appendChild(item);
    setTimeout(() => item.remove(), ms || 2200);
  }

  function modal(title, bodyHtml, onOk) {
    const mask = document.createElement('div');
    mask.className = 'mask on';
    mask.innerHTML =
      '<div class="modal"><h3>' + title + '</h3><div class="modal-body">' + bodyHtml + '</div>' +
      '<div class="row end" style="margin-top:16px"><button class="subtle" data-close>取消</button>' +
      '<button data-ok>确定</button></div></div>';
    document.body.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', (e) => {
      if (e.target === mask || e.target.hasAttribute('data-close')) close();
      if (e.target.hasAttribute('data-ok')) {
        if (!onOk || onOk(mask) !== false) close();
      }
    });
    return mask;
  }

  function tabs(container, onChange) {
    const buttons = $$('.tabs button', container);
    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        buttons.forEach((b) => b.classList.remove('on'));
        btn.classList.add('on');
        $$('.panel', container).forEach((p) => (p.hidden = p.dataset.panel !== btn.dataset.tab));
        if (onChange) onChange(btn.dataset.tab);
      });
    });
    if (buttons.length) buttons[0].click();
  }

  function paginate(rows, pageSize, mount, render) {
    let page = 1;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    function draw() {
      const slice = rows.slice((page - 1) * pageSize, page * pageSize);
      $('tbody', mount).innerHTML = slice.map(render).join('');
      let pager = $('.pager', mount);
      if (!pager) {
        pager = document.createElement('div');
        pager.className = 'pager';
        mount.appendChild(pager);
      }
      let html = '<span>共 ' + rows.length + ' 条</span>';
      for (let i = 1; i <= pages; i += 1) {
        html += '<button data-page="' + i + '" class="' + (i === page ? 'on' : '') + '">' + i + '</button>';
      }
      pager.innerHTML = html;
      $$('button', pager).forEach((b) =>
        b.addEventListener('click', () => {
          page = Number(b.dataset.page);
          draw();
        })
      );
    }
    draw();
  }

  /* 雷达图：六维 5 分制，canvas 手绘，无外部图表库 */
  function drawRadar(canvas, dims) {
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const size = 320;
    canvas.width = size * ratio;
    canvas.height = size * ratio;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, size, size);
    const cx = size / 2;
    const cy = size / 2 + 6;
    const r = size / 2 - 46;
    const n = dims.length;
    const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;

    for (let ring = 5; ring >= 1; ring -= 1) {
      ctx.beginPath();
      for (let i = 0; i < n; i += 1) {
        const a = angle(i);
        const rr = (r * ring) / 5;
        const x = cx + Math.cos(a) * rr;
        const y = cy + Math.sin(a) * rr;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = ring % 2 ? '#f4f8f5' : '#ffffff';
      ctx.fill();
      ctx.strokeStyle = '#e1e7e2';
      ctx.stroke();
    }
    ctx.strokeStyle = '#e1e7e2';
    for (let i = 0; i < n; i += 1) {
      const a = angle(i);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      ctx.stroke();
    }
    ctx.beginPath();
    dims.forEach((d, i) => {
      const a = angle(i);
      const rr = (r * Math.max(0, Math.min(5, d.value))) / 5;
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = 'rgba(8,123,102,.22)';
    ctx.fill();
    ctx.strokeStyle = '#087b66';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.font = '12px "Microsoft YaHei", system-ui, sans-serif';
    ctx.fillStyle = '#172e2b';
    dims.forEach((d, i) => {
      const a = angle(i);
      const x = cx + Math.cos(a) * (r + 26);
      const y = cy + Math.sin(a) * (r + 20);
      ctx.textAlign = Math.abs(Math.cos(a)) < 0.2 ? 'center' : Math.cos(a) > 0 ? 'left' : 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(d.label.replace(/与|和/g, '·'), x, y);
      ctx.fillStyle = '#74817e';
      ctx.fillText(d.value.toFixed(1), x, y + 15);
      ctx.fillStyle = '#172e2b';
    });
  }

  function grade(total) {
    if (total >= 90) return 'A';
    if (total >= 80) return 'B';
    if (total >= 70) return 'C';
    if (total >= 60) return 'D';
    return 'E';
  }

  /* ---------------- 页面：登录 ---------------- */
  function initLogin() {
    const form = $('#loginForm');
    const changeBox = $('#changeBox');
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const user = $('#username').value.trim();
      const pwd = $('#password').value;
      if (!user || !pwd) {
        toast('请输入账号与密码');
        return;
      }
      if ($('#firstLogin').checked) {
        changeBox.hidden = false;
        form.hidden = true;
        toast('首次登录：必须先修改初始密码');
        return;
      }
      toast('登录成功，正在进入工作空间…');
      setTimeout(() => {
        window.location.href = 'index.html';
      }, 600);
    });
    $('#changeForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const a = $('#newPwd').value;
      const b = $('#newPwd2').value;
      if (a.length < 10) {
        toast('新密码至少 10 位');
        return;
      }
      if (a !== b) {
        toast('两次输入的新密码不一致');
        return;
      }
      toast('密码已更新，请用新密码登录');
      changeBox.hidden = true;
      form.hidden = false;
      $('#firstLogin').checked = false;
    });
    $$('[data-fill]').forEach((btn) =>
      btn.addEventListener('click', () => {
        $('#username').value = btn.dataset.fill;
        $('#password').value = '123456';
        $('#firstLogin').checked = true;
        toast('已填入示例账号（初始密码仅演示）');
      })
    );
  }

  /* ---------------- 页面：管理员 ---------------- */
  function initAdmin() {
    tabs($('#adminTabs'));

    const table = $('#rosterTable');
    paginate(DATA.students, 5, table, (s) => {
      return (
        '<tr><td>' + s.no + '</td><td>' + s.name + '</td><td>' + s.cls + '</td>' +
        '<td>' + (s.active ? '<span class="tag">启用</span>' : '<span class="tag grey">停用</span>') + '</td>' +
        '<td class="row" style="gap:6px"><button class="subtle" data-toggle="' + s.no + '">' +
        (s.active ? '停用' : '启用') + '</button><button class="danger" data-del="' + s.no + '">删除</button></td></tr>'
      );
    });

    table.addEventListener('click', (e) => {
      const tog = e.target.dataset.toggle;
      const del = e.target.dataset.del;
      if (tog) {
        const s = DATA.students.find((x) => x.no === tog);
        s.active = !s.active;
        toast(s.name + ' 已' + (s.active ? '启用' : '停用'));
        table.querySelector('.pager button.on').click();
      }
      if (del) {
        const s = DATA.students.find((x) => x.no === del);
        modal('删除账号', '<p>将永久删除 <b>' + s.name + '（' + s.no + '）</b>及其提交记录，删除后不可恢复，确定继续？</p>', () => {
          DATA.students = DATA.students.filter((x) => x.no !== del);
          toast('已删除 ' + s.name);
          const pager = table.querySelector('.pager button.on');
          if (pager) pager.click();
        });
      }
    });

    $('#addStudent').addEventListener('click', () => {
      modal(
        '新建学生账号',
        '<div class="field"><label>姓名</label><input id="mName" placeholder="如：示例学生寅"></div>' +
          '<div class="field"><label>学号 / 工号</label><input id="mNo" placeholder="如：20260113"></div>' +
          '<div class="field"><label>教学班</label><select id="mCls"><option>PY-2026-01</option><option>PY-2026-02</option><option>未分班</option></select></div>' +
          '<div class="field"><label>临时密码（留空使用默认密码）</label><input id="mPwd" placeholder="留空为 123456"></div>' +
          '<p class="hint">新建账号默认要求首次登录修改密码。</p>',
        (mask) => {
          const name = $('#mName', mask).value.trim();
          const no = $('#mNo', mask).value.trim();
          if (!name || !no) {
            toast('姓名与学号不能为空');
            return false;
          }
          if (DATA.students.some((x) => x.no === no)) {
            toast('学号已存在：' + no);
            return false;
          }
          DATA.students.push({ no: no, name: name, cls: $('#mCls', mask).value, active: true });
          toast('已创建 ' + name);
          const last = table.querySelector('.pager button:last-child');
          if (last) last.click();
          return true;
        }
      );
    });

    const preview = [
      { no: '20260120', name: '示例学生卯', ok: true },
      { no: '20260121', name: '示例学生辰', ok: true },
      { no: '20260122', name: '示例学生巳', ok: false, err: '学号重复' },
      { no: '', name: '示例学生午', ok: false, err: '学号为空' },
      { no: '20260124', name: '示例学生未', ok: true },
    ];
    $('#pickFile').addEventListener('click', () => {
      $('#importPanel').hidden = false;
      $('#importBody').innerHTML = preview
        .map(
          (p) =>
            '<tr><td>' + (p.no || '（空）') + '</td><td>' + p.name + '</td><td>' +
            (p.ok ? '<span class="tag">成功</span>' : '<span class="tag red">失败</span> ' + p.err) + '</td></tr>'
        )
        .join('');
      toast('已解析 5 行：成功 3 行，失败 2 行');
    });
    $('#doImport').addEventListener('click', () => {
      const okRows = preview.filter((p) => p.ok);
      okRows.forEach((p) => DATA.students.push({ no: p.no, name: p.name, cls: 'PY-2026-01', active: true }));
      $('#importPanel').hidden = true;
      toast('导入完成：新增 ' + okRows.length + ' 个账号，跳过 2 行');
      table.querySelector('.pager button:last-child').click();
    });

    const dictBox = $('#dictBox');
    function renderDict() {
      dictBox.innerHTML = DATA.dicts
        .map(
          (d) =>
            '<div class="card" style="margin-bottom:12px"><div class="row between"><h3>' + d.name +
            ' <small class="muted mono">' + d.key + '</small></h3><button class="ghost" data-add="' + d.key + '">新增字典项</button></div>' +
            '<div class="row" style="gap:6px">' +
            d.items
              .map(
                (it, i) =>
                  '<span class="tag">' + it + ' <a href="#" data-rm="' + d.key + ':' + i + '" style="color:inherit">×</a></span>'
              )
              .join('') +
            '</div></div>'
        )
        .join('');
    }
    renderDict();
    dictBox.addEventListener('click', (e) => {
      const rm = e.target.dataset.rm;
      if (rm) {
        e.preventDefault();
        const [key, idx] = rm.split(':');
        const d = DATA.dicts.find((x) => x.key === key);
        const removed = d.items.splice(Number(idx), 1)[0];
        renderDict();
        toast('已删除字典项：' + removed);
        return;
      }
      if (e.target.dataset.add) {
        const key = e.target.dataset.add;
        modal('新增字典项', '<div class="field"><label>字典项名称</label><input id="mItem"></div>', (mask) => {
          const value = $('#mItem', mask).value.trim();
          if (!value) {
            toast('名称不能为空');
            return false;
          }
          DATA.dicts.find((x) => x.key === key).items.push(value);
          renderDict();
          toast('已新增：' + value);
          return true;
        });
      }
    });

    const archiveBox = $('#archiveBox');
    function renderArchive() {
      archiveBox.innerHTML = DATA.classes
        .map(
          (c) =>
            '<div class="row between" style="border-bottom:1px solid var(--line);padding:8px 0">' +
            '<div><b>' + c.name + '</b> <small class="muted">' + c.code + ' · ' + c.term + ' · ' + c.count + ' 人</small></div>' +
            '<label class="row" style="gap:6px;margin:0"><input type="checkbox" data-arch="' + c.code + '"' +
            (c.archived ? ' checked' : '') + '> 归档（日常页面隐藏）</label></div>'
        )
        .join('');
    }
    renderArchive();
    archiveBox.addEventListener('change', (e) => {
      if (!e.target.dataset.arch) return;
      const c = DATA.classes.find((x) => x.code === e.target.dataset.arch);
      c.archived = e.target.checked;
      toast(c.name + (c.archived ? ' 已归档，日常页面与旧链接不再显示' : ' 已取消归档，恢复显示'));
    });
  }

  /* ---------------- 页面：教师 ---------------- */
  function initTeacher() {
    tabs($('#teacherTabs'));

    $('#modeSwitch').addEventListener('change', (e) => {
      const auto = e.target.value === 'automatic';
      $('#autoHint').hidden = !auto;
      $('#manualHint').hidden = auto;
      $('#uploadLabel').textContent = auto
        ? '机器批阅包（章节完整 ZIP：含说明、参考答案、测试数据）'
        : '非机器批阅包（含 DOCX 说明与数据材料的 ZIP）';
    });
    $('#modeSwitch').dispatchEvent(new Event('change'));

    $('#saveHw').addEventListener('click', () => {
      const title = $('#hwTitle').value.trim();
      if (!title) {
        toast('请填写作业名称');
        return;
      }
      DATA.homeworks.push({
        id: DATA.homeworks.length + 1,
        title: title,
        mode: $('#modeSwitch').value,
        deadline: $('#hwDeadline').value || '未设置',
        submitted: 0,
        total: 38,
        status: '进行中',
      });
      toast('作业已创建：' + title);
      renderHwList();
    });
    function renderHwList() {
      $('#hwList').innerHTML = DATA.homeworks
        .map(
          (h) =>
            '<tr><td>' + h.title + '</td><td>' +
            (h.mode === 'automatic' ? '<span class="tag">机器批阅</span>' : '<span class="tag amber">非机器批阅</span>') +
            '</td><td>' + h.deadline + '</td><td>' + h.submitted + ' / ' + h.total + '</td><td>' + h.status +
            '</td><td><button class="subtle">修改</button></td></tr>'
        )
        .join('');
    }
    renderHwList();

    const entryBox = $('#entryBox');
    function renderEntries() {
      entryBox.innerHTML = DATA.entries
        .map(
          (e) =>
            '<div class="row between" data-entry="' + e.id + '" style="border-bottom:1px solid var(--line);padding:8px 0;cursor:pointer">' +
            '<div><b>' + e.name + '</b> <small class="muted">' + e.no + ' · 第 ' + e.attempt + ' 次提交</small></div>' +
            '<div class="row" style="gap:8px"><span class="tag ' +
            (e.status === '已完成' ? '' : e.status === '批阅异常' ? 'red' : 'grey') + '">' + e.status +
            '</span><small class="muted">' + (e.score === null ? '—' : e.score) + '</small></div></div>'
        )
        .join('');
    }
    renderEntries();

    function renderDetail(entry) {
      $('#detail').innerHTML =
        '<div class="row between"><h3>' + entry.name + ' 的提交</h3><small class="muted">状态：' + entry.status + '</small></div>' +
        '<div class="kv"><span>提交次数</span><span>第 ' + entry.attempt + ' 次</span>' +
        '<span>通过用例</span><span>' + entry.cases + '</span>' +
        '<span>机器得分</span><span>' + (entry.score === null ? '—（未批阅）' : entry.score) + '</span></div>' +
        '<h3 style="margin-top:16px">逐题人工评分（非机器批阅 / 复核使用）</h3>' +
        DATA.questions
          .map(
            (q, i) =>
              '<div class="field"><label>' + q.fn + ' · ' + q.title + '（满分 ' + q.full + ' 分，用例 ' + q.cases + '）</label>' +
              '<div class="row"><input type="range" min="0" max="' + q.full + '" step="0.5" value="' + (q.full * 0.8).toFixed(1) +
              '" data-q="' + i + '"><b data-out="' + i + '" style="width:52px">' + (q.full * 0.8).toFixed(1) + '</b>' +
              '<input placeholder="评语（可选）" style="flex:1"></div></div>'
          )
          .join('') +
        '<div class="row between" style="margin-top:10px"><div><b>本份合计：<span id="manualSum">0</span> / ' +
        DATA.questions.reduce((a, q) => a + q.full, 0) + '</b></div>' +
        '<div class="row" style="gap:8px"><button class="subtle" id="downloadZip">按班打包下载本班最后一次提交</button>' +
        '<button id="saveManual">保存评分</button></div></div>';

      const sliders = $$('input[type=range]', $('#detail'));
      function sum() {
        const total = sliders.reduce((a, s) => a + Number(s.value), 0);
        $('#manualSum').textContent = total.toFixed(1);
        return total;
      }
      sliders.forEach((s) => {
        s.addEventListener('input', () => {
          $('[data-out="' + s.dataset.q + '"]').textContent = Number(s.value).toFixed(1);
          sum();
        });
      });
      sum();
      $('#saveManual').addEventListener('click', () => toast('已保存人工评分：' + sum().toFixed(1) + ' 分'));
      $('#downloadZip').addEventListener('click', () => toast('已开始打包，完成后在浏览器下载（示例提示）'));
    }
    entryBox.addEventListener('click', (e) => {
      const row = e.target.closest('[data-entry]');
      if (!row) return;
      const entry = DATA.entries.find((x) => x.id === Number(row.dataset.entry));
      renderDetail(entry);
    });

    const dimBox = $('#dimBox');
    const canvas = $('#radar');
    function renderRubric() {
      dimBox.innerHTML = DATA.rubric
        .map(
          (d, i) =>
            '<div class="field"><label>' + d.key + ' · ' + d.label + '（权重 ' + d.weight + '%）<small class="muted"> ' + d.tips + '</small></label>' +
            '<div class="row"><input type="range" min="0" max="5" step="0.5" value="' + d.value + '" data-i="' + i + '">' +
            '<b data-v="' + i + '" style="width:36px">' + d.value.toFixed(1) + '</b></div></div>'
        )
        .join('');
      $$('input[type=range]', dimBox).forEach((s) =>
        s.addEventListener('input', () => {
          const i = Number(s.dataset.i);
          DATA.rubric[i].value = Number(s.value);
          $('[data-v="' + i + '"]').textContent = DATA.rubric[i].value.toFixed(1);
          updateScore();
        })
      );
      updateScore();
    }
    function updateScore() {
      const total5 = DATA.rubric.reduce((a, d) => a + (d.value * d.weight) / 100, 0);
      const hundred = total5 * 20;
      $('#score5').textContent = total5.toFixed(2);
      $('#score100').textContent = hundred.toFixed(1);
      $('#scoreGrade').textContent = grade(hundred);
      drawRadar(canvas, DATA.rubric);
    }
    renderRubric();
    $('#resetRubric').addEventListener('click', () => {
      DATA.rubric.forEach((d) => (d.value = 3));
      renderRubric();
      toast('已重置为 3 分基准');
    });
  }

  /* ---------------- 页面：学生 ---------------- */
  function initStudent() {
    tabs($('#studentTabs'));

    $('#fileInput').addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const ok = file.name.endsWith('.py');
      $('#fileInfo').innerHTML = ok
        ? '<span class="note">已选择：' + file.name + '（' + Math.max(1, Math.round(file.size / 1024)) + ' KB）</span>'
        : '<span class="hint">机器批阅作业只接受单个 UTF-8 编码的 .py 文件，当前选择：' + file.name + '</span>';
      $('#doSubmit').disabled = !ok;
    });

    $('#doSubmit').addEventListener('click', () => {
      $('#progress').hidden = false;
      $('#resultBox').hidden = true;
      let pct = 0;
      const bar = $('#bar');
      const timer = setInterval(() => {
        pct += 12;
        bar.style.width = Math.min(100, pct) + '%';
        $('#pctText').textContent = Math.min(100, pct) + '%';
        if (pct >= 100) {
          clearInterval(timer);
          $('#progressHint').textContent = '批阅完成（原型模拟，不代表真实批阅结果）';
          $('#resultBox').hidden = false;
          toast('提交成功，已开始批阅（原型模拟）');
        }
      }, 300);
    });

    $('#zipInput').addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      $('#zipInfo').innerHTML =
        '<span class="note">已选择：' + file.name + '</span><p class="hint" style="margin-top:8px">' +
        '非机器批阅作业要求包内包含 1001.py～1005.py 五个源码文件；提交后由教师逐题人工评分。</p>';
    });

    $('#showReport').addEventListener('click', () => {
      $('#reportBox').hidden = false;
      drawRadar($('#myRadar'), DATA.rubric);
      $('#reportBox').scrollIntoView({ behavior: 'smooth' });
      toast('已加载我的代码质量报告（示例数据）');
    });
  }

  /* ---------------- 首页 ---------------- */
  function initIndex() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('from') === 'login') toast('已登录（原型演示，未校验真实账号）');
  }

  const PAGES = {
    index: initIndex,
    login: initLogin,
    admin: initAdmin,
    teacher: initTeacher,
    student: initStudent,
  };

  document.addEventListener('DOMContentLoaded', () => {
    const page = document.body.dataset.page;
    if (PAGES[page]) {
      try {
        PAGES[page]();
      } catch (err) {
        toast('原型脚本异常：' + err.message);
        throw err;
      }
    }
  });

  window.Proto = { data: DATA, toast: toast, modal: modal, drawRadar: drawRadar, grade: grade };
})();
