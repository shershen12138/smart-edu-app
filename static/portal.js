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
