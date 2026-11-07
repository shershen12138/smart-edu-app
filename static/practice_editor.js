/* 训练题代码编辑器：行号 + Python 语法高亮 + Tab/自动缩进。
   自包含实现（无外部 CDN 依赖），仅做展示层增强，提交的仍是原始文本。 */
(function () {
  'use strict';

  var KEYWORDS = new Set(
    ('False None True and as assert async await break class continue def del elif else ' +
     'except finally for from global if import in is lambda nonlocal not or pass ' +
     'raise return try while with yield').split(' ')
  );
  var BUILTINS = new Set(
    ('abs all any bin bool bytes chr dict divmod enumerate eval filter float format ' +
     'frozenset getattr hash hex input int isinstance issubclass iter len list map max ' +
     'min next oct open ord pow print range repr reversed round set setattr sorted str ' +
     'sum super tuple type zip').split(' ')
  );

  // 单趟扫描：1 注释 2 字符串 3 数字 4 标识符，避免对已生成的 HTML 二次替换。
  var TOKEN_RE = new RegExp(
    [
      '(#[^\\n]*)',
      '([rbfu]{0,2}"""[\\s\\S]*?"""|[rbfu]{0,2}\'\'\'[\\s\\S]*?\'\'\'|[rbfu]{0,2}"(?:\\\\.|[^"\\\\\\n])*"|[rbfu]{0,2}\'(?:\\\\.|[^\'\\\\\\n])*\')',
      '(\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)',
      '([A-Za-z_]\\w*)'
    ].join('|'),
    'g'
  );

  function escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function highlight(code) {
    var html = '';
    var last = 0;
    var match;
    TOKEN_RE.lastIndex = 0;
    while ((match = TOKEN_RE.exec(code)) !== null) {
      html += escapeHtml(code.slice(last, match.index));
      var token = match[0];
      if (match[1]) {
        html += '<span class="tok-com">' + escapeHtml(token) + '</span>';
      } else if (match[2]) {
        html += '<span class="tok-str">' + escapeHtml(token) + '</span>';
      } else if (match[3]) {
        html += '<span class="tok-num">' + escapeHtml(token) + '</span>';
      } else if (KEYWORDS.has(token)) {
        html += '<span class="tok-kw">' + escapeHtml(token) + '</span>';
      } else if (BUILTINS.has(token)) {
        html += '<span class="tok-bi">' + escapeHtml(token) + '</span>';
      } else {
        html += escapeHtml(token);
      }
      last = match.index + token.length;
      if (TOKEN_RE.lastIndex === match.index) {
        TOKEN_RE.lastIndex += 1; // 防御空匹配死循环
      }
    }
    html += escapeHtml(code.slice(last));
    // def/class 后跟的函数名单独着色（此时名称是纯文本，不会被误替换）
    html = html.replace(
      /(<span class="tok-kw">(?:def|class)<\/span>)\s+([A-Za-z_]\w*)/g,
      function (whole, keyword, name) {
        return keyword + ' <span class="tok-def">' + name + '</span>';
      }
    );
    return html;
  }

  function lineCount(code) {
    return code.split('\n').length;
  }

  function setupEditor(root) {
    var textarea = root.querySelector('textarea[data-code-input]');
    var gutter = root.querySelector('[data-gutter]');
    var highlighter = root.querySelector('[data-highlight] code') ||
      root.querySelector('[data-highlight]');
    if (!textarea || !gutter || !highlighter) return;

    function syncScroll() {
      highlighter.parentElement.scrollTop = textarea.scrollTop;
      highlighter.parentElement.scrollLeft = textarea.scrollLeft;
    }

    function render() {
      highlighter.innerHTML = highlight(textarea.value) + '\n';
      var lines = '';
      for (var i = 1; i <= lineCount(textarea.value); i += 1) {
        lines += i + '\n';
      }
      gutter.textContent = lines;
      syncScroll();
    }

    function insertAtCaret(element, text) {
      var start = element.selectionStart;
      var end = element.selectionEnd;
      element.value = element.value.slice(0, start) + text + element.value.slice(end);
      var caret = start + text.length;
      element.selectionStart = caret;
      element.selectionEnd = caret;
    }

    textarea.addEventListener('input', render);
    textarea.addEventListener('scroll', syncScroll);
    textarea.addEventListener('keydown', function (event) {
      if (event.key === 'Tab') {
        event.preventDefault();
        insertAtCaret(textarea, '    ');
        render();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        var before = textarea.value.slice(0, textarea.selectionStart);
        var lineStart = before.lastIndexOf('\n') + 1;
        var currentLine = before.slice(lineStart);
        var indent = (currentLine.match(/^[ \t]*/) || [''])[0];
        if (/:(\s*#.*)?$/.test(currentLine.trimEnd())) indent += '    ';
        insertAtCaret(textarea, '\n' + indent);
        render();
      }
    });

    render();
  }

  function init() {
    document.querySelectorAll('[data-editor]').forEach(setupEditor);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
