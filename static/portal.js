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
