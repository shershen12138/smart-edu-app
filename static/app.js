document.querySelectorAll('.sidebar nav>a').forEach(a => {
  if (a.pathname === location.pathname) a.classList.add('active')
});
const addCase = document.querySelector('#add-case');
if (addCase) addCase.addEventListener('click', () => {
  const count = document.querySelector('#id_cases-TOTAL_FORMS');
  const n = Number(count.value);
  if (n >= 50) return;
  document.querySelector('#case-list').insertAdjacentHTML('beforeend', document.querySelector('#empty-case').innerHTML.replaceAll('__prefix__', String(n)));
  count.value = n + 1
});
const submitForm = document.querySelector('#submission-form');
if (submitForm) {
  const editor = submitForm.querySelector('textarea[name=code]');
  const key = 'coursejudge:' + submitForm.dataset.draft;
  try {
    const saved = localStorage.getItem(key);
    if (saved && !editor.value.trim()) editor.value = saved
  } catch {};
  editor.addEventListener('input', () => {
    try {
      localStorage.setItem(key, editor.value);
      document.querySelector('#draft-status').textContent = '草稿已保存在当前浏览器'
    } catch {
      document.querySelector('#draft-status').textContent = '浏览器不允许保存草稿'
    }
  });
  editor.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = editor.selectionStart;
      editor.setRangeText('    ', start, editor.selectionEnd, 'end');
      editor.dispatchEvent(new Event('input'))
    }
  });
  submitForm.addEventListener('submit', () => {
    const button = submitForm.querySelector('button[type=submit],button:not([type])');
    if (button) {
      button.disabled = true;
      button.textContent = '正在提交…'
    }
  })
}
const polling = document.querySelector('[data-poll]');
if (polling) {
  let attempts = 0;
  const timer = setInterval(async () => {
    if (++attempts > 150) {
      clearInterval(timer);
      return
    }
    try {
      const r = await fetch(polling.dataset.poll, {
        headers: {
          Accept: 'application/json'
        }
      });
      if (!r.ok) {
        clearInterval(timer);
        return
      }
      const data = await r.json();
      if (['done', 'error', 'superseded'].includes(data.status)) location.reload()
    } catch {}
  }, 2500)
}
