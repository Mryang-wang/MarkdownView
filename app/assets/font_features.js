/* Persist font choices as HTML spans; transient editor wrappers are ignored by Lute. */
window.installFontFeatures = function (editor, selectionTools, getBridge, changed) {
  "use strict";
  var panel = document.getElementById("mdv-font-panel"), search = document.getElementById("mdv-font-search");
  var options = document.getElementById("mdv-font-options"), notice = document.getElementById("mdv-font-notice");
  var button = document.querySelector('#vditor [data-type="mdv-font"]');
  var families = null, savedRange = null, savedMode = null, hasSelection = false, composing = false;
  var aliases = {SimSun: "宋体", NSimSun: "新宋体", SimHei: "黑体", KaiTi: "楷体", FangSong: "仿宋",
    "Microsoft YaHei": "微软雅黑", "Microsoft JhengHei": "微软正黑体"};
  var preferred = ["宋体", "SimSun", "微软雅黑", "Microsoft YaHei", "黑体", "SimHei", "楷体", "KaiTi", "仿宋", "FangSong",
    "Arial", "Times New Roman", "Calibri", "Consolas", "Courier New", "Segoe UI"];
  var excluded = '[data-type="html-inline"],.vditor-ir__marker,.vditor-ir__preview,.vditor-wysiwyg__preview,[data-type$="-marker"],code,script,style';
  function root() { return editor.vditor[editor.getCurrentMode()].element; }
  function editable() { return !window.mdvReadOnly && !window.mdvTranslationReading && root().isContentEditable; }
  function cssFont(family) { return JSON.stringify(family); }
  function styleTag(styles) {
    // Separate CSS and HTML quote characters: Lute decodes HTML entities on mode switches.
    var declarations = [];
    if (styles.fontFamily) {
      var escaped = styles.fontFamily.replace(/[\\'"&<>\x00-\x1f]/g, function (value) { return "\\" + value.charCodeAt(0).toString(16) + " "; });
      declarations.push("font-family: '" + escaped + "'");
    }
    if (styles.fontSize) { declarations.push("font-size: " + styles.fontSize); }
    if (styles.color) { declarations.push("color: " + styles.color); }
    return '<span' + (styles.color ? ' data-mdv-text-color="true"' : '') + ' style="' + declarations.join("; ") + '">';
  }
  function marker(tag, mode) {
    mode = mode || editor.getCurrentMode();
    var node = document.createElement(mode === "ir" ? "span" : "code");
    node.dataset.type = "html-inline";
    if (mode === "ir") {
      node.className = "vditor-ir__node";
      var code = document.createElement("code"); code.className = "vditor-ir__marker"; code.textContent = tag; node.appendChild(code);
    } else { node.textContent = "\u200b" + tag; }
    return node;
  }
  function formatSource(markdown, styles) {
    if (!markdown.trim()) { return markdown; }
    var leading = markdown.match(/^\s*/)[0], trailing = markdown.match(/\s*$/)[0];
    var fragment = document.createElement("div"), lute = editor.vditor.lute;
    fragment.innerHTML = lute.Md2VditorIRDOM(window.markdownMath.toEditor(markdown.slice(leading.length, markdown.length - trailing.length)));
    var walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT), nodes = [];
    while (walker.nextNode()) {
      if (!walker.currentNode.parentElement.closest(excluded)) { nodes.push(walker.currentNode); }
    }
    nodes.forEach(function (text) { text.before(marker(styleTag(styles), "ir")); text.after(marker("</span>", "ir")); });
    return leading + window.markdownMath.fromEditor(lute.VditorIRDOM2Md(fragment.innerHTML)).replace(/\n+$/, "") + trailing;
  }
  function close(restore) {
    panel.hidden = true; button.setAttribute("aria-expanded", "false");
    if (restore && savedMode === editor.getCurrentMode()) { selectionTools.restoreRange(savedRange); }
    savedRange = null;
  }
  function choose(family) {
    if (family && applyStyles({fontFamily: family}, savedRange, savedMode)) { close(false); }
  }
  function applyStyles(styles, originalRange, mode) {
    if (!editable() || !originalRange || mode !== editor.getCurrentMode()) { return false; }
    var range = selectionTools.restoreRange(originalRange);
    if (!range || range.collapsed) { return false; }
    if (editor.getCurrentMode() === "sv") {
      selectionTools.applyFormat("", "", range, function (markdown) { return formatSource(markdown, styles); }); return true;
    }
    // The undo snapshot inserts a caret marker and may split text nodes.
    editor.vditor.undo.addToUndoStack(editor.vditor);
    range = selectionTools.restoreRange(originalRange);
    if (!range) { return false; }
    var pieces = selectionTools.textNodes(root()).filter(function (node) {
      return range.intersectsNode(node) && !node.parentElement.closest(excluded);
    }).map(function (node) {
      return {node: node, start: node === range.startContainer ? range.startOffset : 0,
        end: node === range.endContainer ? range.endOffset : node.length};
    }).filter(function (piece) { return piece.end > piece.start; });
    if (!pieces.length) { return false; }
    pieces.forEach(function (piece) {
      var text = piece.node;
      if (piece.end < text.length) { text.splitText(piece.end); }
      if (piece.start) { text = text.splitText(piece.start); }
      text.before(marker(styleTag(styles))); text.after(marker("</span>")); piece.node = text;
    });
    range = document.createRange(); range.setStart(pieces[0].node, 0);
    range.setEnd(pieces[pieces.length - 1].node, pieces[pieces.length - 1].node.length);
    getSelection().removeAllRanges(); getSelection().addRange(range);
    var bookmark = selectionTools.currentRange();
    range.collapse(false); // The refresh API must not replace the selected text.
    getSelection().removeAllRanges(); getSelection().addRange(range);
    editor.insertMD(""); window.refreshFontFormats(); selectionTools.restoreRange(bookmark);
    editor.vditor.undo.addToUndoStack(editor.vditor); changed(); return true;
  }
  function renderOptions() {
    var query = search.value.trim().toLocaleLowerCase(), fragment = document.createDocumentFragment();
    (families || []).filter(function (family) { return (family + " " + (aliases[family] || "")).toLocaleLowerCase().includes(query); }).forEach(function (family) {
      var option = document.createElement("button"); option.type = "button";
      option.textContent = aliases[family] ? aliases[family] + " · " + family : family;
      option.dataset.font = family; option.style.fontFamily = cssFont(family);
      option.disabled = !hasSelection;
      option.onclick = function () { choose(family); }; fragment.appendChild(option);
    });
    options.replaceChildren(fragment);
    notice.hidden = hasSelection && options.children.length > 0;
    notice.textContent = window.uiText(hasSelection ? "没有匹配的字体。" : "请先选中需要更换字体的文字。");
    document.getElementById("mdv-font-reset").disabled = !hasSelection;
    selectionTools.positionPanel(panel, button);
  }
  button.setAttribute("aria-haspopup", "dialog"); button.setAttribute("aria-expanded", "false"); button.setAttribute("aria-controls", panel.id);
  window.openFontPicker = function () {
    if (!panel.hidden) { close(true); return; }
    if (!editable()) { return; }
    savedRange = selectionTools.currentRange(); savedMode = editor.getCurrentMode();
    hasSelection = !!savedRange && !savedRange.collapsed;
    panel.hidden = false; button.setAttribute("aria-expanded", "true"); search.value = "";
    renderOptions(); search.focus();
    if (!families && getBridge()) {
      getBridge().fontFamilies(function (names) {
        var duplicateAliases = Object.keys(aliases).filter(function (name) { return names.includes(name); }).map(function (name) { return aliases[name]; });
        names = names.filter(function (name) { return !duplicateAliases.includes(name); });
        families = preferred.filter(function (name) { return names.includes(name); }).concat(names.filter(function (name) { return !preferred.includes(name); }));
        if (!panel.hidden) { renderOptions(); }
      });
    }
  };
  search.oninput = renderOptions;
  document.getElementById("mdv-font-cancel").onclick = function () { close(true); };
  document.getElementById("mdv-font-reset").onclick = function () {
    var font = getComputedStyle(document.documentElement).getPropertyValue("--reading-font").trim() || '"Segoe UI"';
    try { font = JSON.parse(font); } catch (_) { font = font.replace(/^["']|["']$/g, ""); }
    choose(font);
  };
  panel.addEventListener("keydown", function (event) {
    if (event.isComposing || composing) { return; }
    var buttons = Array.from(options.querySelectorAll("button:not(:disabled)"));
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && buttons.length) {
      event.preventDefault(); var index = buttons.indexOf(document.activeElement);
      buttons[(index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length].focus();
    } else if (event.key === "Enter" && event.target === search && buttons.length) { event.preventDefault(); buttons[0].click(); }
    else if (event.key === "Tab") {
      var controls = Array.from(panel.querySelectorAll("input,button:not(:disabled)"));
      var next = (controls.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
      event.preventDefault(); controls[next].focus();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.isComposing || composing) { return; }
    if (event.key === "Escape" && !panel.hidden) { event.preventDefault(); event.stopImmediatePropagation(); close(true); }
  }, true);
  document.addEventListener("pointerdown", function (event) {
    if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) { close(false); }
  }, true);
  window.addEventListener("resize", function () { if (!panel.hidden) { selectionTools.positionPanel(panel, button); } });
  document.addEventListener("compositionstart", function () { composing = true; });
  document.addEventListener("compositionend", function () { composing = false; setTimeout(window.refreshInlineFormats, 0); });
  window.installTextStyleControls(editor, selectionTools, applyStyles);

  window.refreshFontFormats = function () {
    if (composing || editor.getCurrentMode() === "sv") { return; }
    var element = root(), stack = [], desired = new Map();
    if (!element.querySelector('[data-type="html-inline"],[data-mdv-font-run]')) { return; }
    var walker = document.createTreeWalker(element, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node.nodeType === Node.ELEMENT_NODE && node.matches('[data-type="html-inline"]') && !node.closest('.vditor-ir__preview,.vditor-wysiwyg__preview')) {
        node.removeAttribute("data-mdv-font-marker");
        var tag = node.textContent.replace(/\u200b/g, "").trim();
        if (/^<span(?:\s[^>]*)?>$/i.test(tag)) {
          var template = document.createElement("template"); template.innerHTML = tag;
          var inline = template.content.firstElementChild.style;
          var own = {}, active = Object.assign({}, stack.length ? stack[stack.length - 1].styles : {});
          ["fontFamily", "fontSize", "color"].forEach(function (name) { if (inline[name]) { own[name] = inline[name]; } });
          stack.push({styles: Object.assign(active, own), marker: node, own: Object.keys(own).length > 0});
        } else if (/^<\/span\s*>$/i.test(tag) && stack.length) {
          var opening = stack.pop();
          if (opening.own) { opening.marker.dataset.mdvFontMarker = "true"; node.dataset.mdvFontMarker = "true"; }
        }
      } else if (node.nodeType === Node.TEXT_NODE && node.nodeValue && !node.parentElement.closest(excluded)) {
        var styles = stack.length ? stack[stack.length - 1].styles : null;
        desired.set(node, styles && Object.keys(styles).length ? styles : null);
      }
    }
    var remove = Array.from(element.querySelectorAll("[data-mdv-font-run]")).filter(function (span) {
      return span.childNodes.length !== 1 || !desired.get(span.firstChild);
    });
    var needsWrap = Array.from(desired).some(function (entry) { return entry[1] && !entry[0].parentElement.hasAttribute("data-mdv-font-run"); });
    var bookmark = (remove.length || needsWrap) ? selectionTools.currentRange() : null;
    remove.forEach(function (span) { span.replaceWith(...span.childNodes); });
    desired.forEach(function (styles, text) {
      if (!styles) { return; }
      var span = text.parentElement;
      if (!span.hasAttribute("data-mdv-font-run")) {
        span = document.createElement("span"); span.dataset.mdvFontRun = "true";
        text.replaceWith(span); span.appendChild(text);
      }
      ["fontFamily", "fontSize", "color"].forEach(function (name) {
        if (span.style[name] !== (styles[name] || "")) { span.style[name] = styles[name] || ""; }
      });
      // Highlight foregrounds respect an explicit text color without losing the background.
      if (styles.color) { span.style.setProperty("--mdv-inline-color", styles.color); }
      else { span.style.removeProperty("--mdv-inline-color"); }
    });
    if (bookmark) { selectionTools.restoreRange(bookmark); }
  };
};
