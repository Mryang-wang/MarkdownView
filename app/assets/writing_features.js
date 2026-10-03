/* 按需出现的查找替换、图片导入与阅读位置记录。 */
window.installWritingFeatures = function (editor, getBridge, changed) {
  "use strict";
  var panel = document.getElementById("mdv-find-panel");
  var query = document.getElementById("mdv-find-input");
  var replacement = document.getElementById("mdv-replace-input");
  var replaceRow = document.getElementById("mdv-replace-row");
  var count = document.getElementById("mdv-find-count");
  var caseOption = document.getElementById("mdv-find-case");
  var wordOption = document.getElementById("mdv-find-word");
  var matches = [], active = 0, index = null, refreshTimer = null;

  function root() { return editor.vditor[editor.getCurrentMode()].element; }
  function scrollContainer() {
    var element = root();
    return element.scrollHeight > element.clientHeight ? element : element.parentElement;
  }

  function textIndex(element) {
    var walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    var segments = [], text = "", lastBlock = null;
    while (walker.nextNode()) {
      var node = walker.currentNode, parent = node.parentElement;
      if (!node.nodeValue || !node.nodeValue.replace(/\u200b/g, "")) { continue; }
      if (parent.closest('.vditor-ir__preview, .vditor-wysiwyg__preview, textarea, script, style')) { continue; }
      if (editor.getCurrentMode() === "ir" && parent.closest(
          '.vditor-ir__marker:not(pre), [data-type$="-marker"]')) { continue; }
      var block = parent.closest('p, h1, h2, h3, h4, h5, h6, td, th, li, [data-block]');
      if (lastBlock && block !== lastBlock) { text += "\n"; }
      segments.push({ node: node, start: text.length, end: text.length + node.nodeValue.length });
      text += node.nodeValue;
      lastBlock = block;
    }
    return { text: text, segments: segments };
  }

  function rangeFor(data, match) {
    var range = document.createRange(), start = null, end = null;
    data.segments.some(function (segment) {
      if (match.start >= segment.start && match.start < segment.end) { start = segment; return true; }
      return false;
    });
    data.segments.some(function (segment) {
      if (match.end > segment.start && match.end <= segment.end) { end = segment; return true; }
      return false;
    });
    if (!start || !end) { return null; }
    range.setStart(start.node, match.start - start.start);
    range.setEnd(end.node, match.end - end.start);
    return range;
  }

  function clearHighlights() {
    if (CSS.highlights) {
      CSS.highlights.delete("mdv-found"); CSS.highlights.delete("mdv-active");
    }
  }

  function paint(scroll) {
    clearHighlights();
    var hasMatches = matches.length > 0;
    ["mdv-find-prev", "mdv-find-next", "mdv-replace-one", "mdv-replace-all"].forEach(function (id) {
      document.getElementById(id).disabled = !hasMatches;
    });
    count.textContent = !query.value ? "" : hasMatches ? (active + 1) + " / " + matches.length : "无匹配";
    if (!hasMatches) { return; }
    var ranges = matches.map(function (match) { return rangeFor(index, match); }).filter(Boolean);
    var current = rangeFor(index, matches[active]);
    if (CSS.highlights) {
      CSS.highlights.set("mdv-found", new Highlight(...ranges));
      var selected = new Highlight(current); selected.priority = 1;
      CSS.highlights.set("mdv-active", selected);
    }
    if (scroll && current) {
      var element = current.startContainer.parentElement;
      var codeBlock = element.closest('[data-type="code-block"], [data-type="math-block"]');
      if (codeBlock) { codeBlock.classList.add("vditor-ir__node--expand"); }
      var container = scrollContainer(), rect = current.getBoundingClientRect();
      var viewport = container.getBoundingClientRect();
      var scale = viewport.height / container.offsetHeight || 1;
      container.scrollTop += (rect.top - viewport.top) / scale - container.clientHeight / 2;
    }
  }

  function search(scroll, retain) {
    index = textIndex(root());
    matches = [];
    var term = query.value;
    if (term) {
      var escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      var expression = new RegExp(escaped, caseOption.checked ? "gu" : "giu");
      var match;
      while ((match = expression.exec(index.text)) !== null) {
        var start = match.index, end = start + match[0].length;
        if (wordOption.checked && (/^[\p{L}\p{N}_]$/u.test(index.text[start - 1] || "") ||
            /^[\p{L}\p{N}_]$/u.test(index.text[end] || ""))) { continue; }
        matches.push({ start: start, end: end });
      }
    }
    active = retain ? Math.min(active, Math.max(0, matches.length - 1)) : 0;
    paint(scroll);
  }

  function toggleReplace(enabled) {
    replaceRow.hidden = !enabled;
    document.getElementById("mdv-find-toggle").textContent = enabled ? "隐藏替换" : "显示替换";
  }

  window.openFind = function (replace) {
    var selected = editor.getSelection();
    if (selected && selected.length < 200 && !selected.includes("\n")) { query.value = selected; }
    panel.hidden = false; toggleReplace(replace);
    search(false, false); query.focus(); query.select();
  };
  window.closeFind = function () {
    var selected = matches[active] && index ? rangeFor(index, matches[active]) : null;
    panel.hidden = true; clearHighlights(); editor.focus();
    if (selected && selected.startContainer.isConnected) {
      var selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(selected);
    }
  };
  window.findNext = function (direction) {
    if (panel.hidden) { window.openFind(false); return; }
    if (matches.length) { active = (active + direction + matches.length) % matches.length; paint(true); }
  };
  window.refreshFind = function () {
    if (panel.hidden) { return; }
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () { search(false, true); }, 80);
  };

  function replace(all) {
    search(false, true);
    if (!matches.length) { return; }
    var clone = root().cloneNode(true), clonedIndex = textIndex(clone);
    // 不把仅用于本地显示的绝对图片路径写入 Markdown。
    clone.querySelectorAll('img[data-osrc]').forEach(function (image) {
      image.setAttribute("src", image.getAttribute("data-osrc")); image.removeAttribute("data-osrc");
    });
    var selected = all ? matches.slice() : [matches[active]];
    selected.reverse().forEach(function (match) {
      var range = rangeFor(clonedIndex, match);
      range.deleteContents(); range.insertNode(document.createTextNode(replacement.value));
    });
    var mode = editor.getCurrentMode(), lute = editor.vditor.lute;
    var markdown = mode === "ir" ? lute.VditorIRDOM2Md(clone.innerHTML) :
      mode === "wysiwyg" ? lute.VditorDOM2Md(clone.innerHTML) :
      clone.textContent.replace(/\u00a0/g, " ").replace(/\n*$/, "\n");
    var position = window.getEditorPosition();
    // 替换是一次独立操作，立即记录前后状态，避免被输入防抖合并。
    editor.vditor.undo.addToUndoStack(editor.vditor);
    editor.setValue(markdown);
    editor.vditor.undo.addToUndoStack(editor.vditor);
    changed(); window.restorePosition(position);
    search(false, true);
    replacement.focus();
  }

  query.addEventListener("input", function () { search(true, false); });
  [caseOption, wordOption].forEach(function (option) {
    option.addEventListener("change", function () { search(true, false); });
  });
  document.getElementById("mdv-find-prev").onclick = function () { window.findNext(-1); };
  document.getElementById("mdv-find-next").onclick = function () { window.findNext(1); };
  document.getElementById("mdv-find-close").onclick = window.closeFind;
  document.getElementById("mdv-find-toggle").onclick = function () { toggleReplace(replaceRow.hidden); };
  document.getElementById("mdv-replace-one").onclick = function () { replace(false); };
  document.getElementById("mdv-replace-all").onclick = function () { replace(true); };
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); window.findNext(event.shiftKey ? -1 : 1); }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      event.preventDefault(); event.stopImmediatePropagation(); window.closeFind();
    } else if ((event.ctrlKey || event.metaKey) && /^(f|h)$/i.test(event.key)) {
      event.preventDefault(); event.stopImmediatePropagation(); window.openFind(event.key.toLowerCase() === "h");
    } else if (event.key === "F3") {
      event.preventDefault(); window.findNext(event.shiftKey ? -1 : 1);
    }
  }, true);

  function readImage(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader(); reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(new Error(window.uiText("无法读取图片"))); };
      reader.readAsDataURL(file);
    });
  }
  window.importDroppedImages = async function (files) {
    var bridge = getBridge();
    if (!bridge) { return window.uiText("编辑器尚未就绪，请稍后再试。"); }
    var selection = window.getSelection();
    var savedRange = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    try {
      for (var item of Array.from(files)) {
        var file = item.getAsFile ? item.getAsFile() : item;
        if (!file) { continue; }
        if (file.size > 50 * 1024 * 1024) { return window.uiText("单张图片不能超过 50 MB。"); }
        var data = await readImage(file);
        var response = await new Promise(function (resolve) { bridge.importImage(data, file.name || "截图.png", resolve); });
        var result = JSON.parse(response);
        if (result.error) { return result.error; }
        editor.focus();
        if (savedRange && savedRange.startContainer.isConnected && root().contains(savedRange.startContainer)) {
          selection.removeAllRanges(); selection.addRange(savedRange);
        }
        window.insertImageAtCursor(result.path, result.alt);
        savedRange = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
      }
      return null;
    } catch (error) { return window.uiText("插入图片失败：" + error.message); }
  };
  window.editorAcceptsImage = function () {
    return !document.activeElement.closest('input, textarea, #mdv-find-panel, #mdview-stats-backdrop');
  };

  var positionTimer = null;
  window.getEditorPosition = function () { return scrollContainer().scrollTop; };
  window.restorePosition = function (position) {
    requestAnimationFrame(function () { scrollContainer().scrollTop = Math.max(0, Number(position) || 0); });
  };
  document.getElementById("vditor").addEventListener("scroll", function () {
    clearTimeout(positionTimer);
    positionTimer = setTimeout(function () {
      var bridge = getBridge();
      if (bridge) { bridge.reportPosition(window.getEditorPosition()); }
    }, 200);
  }, true);
  document.querySelector('#vditor .vditor-toolbar').addEventListener("click", window.refreshFind);
};
