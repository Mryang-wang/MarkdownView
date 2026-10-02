/* 下划线与彩色高亮：保留 Markdown 中的 HTML 标记，绘制可编辑文本的格式。 */
window.installInlineFormats = function (editor, changed) {
  "use strict";
  var panel = document.getElementById("mdv-highlight-panel");
  var picker = document.getElementById("mdv-highlight-custom");
  var hexInput = document.getElementById("mdv-highlight-hex");
  var error = document.getElementById("mdv-highlight-error");
  var button = document.querySelector('#vditor button[data-type="u-mark"]');
  var savedRange = null, savedMode = null, color = "#ffe58f", refreshTimer = null;
  var underlinePanel = document.getElementById("mdv-underline-panel");
  var underlineButton = document.querySelector('#vditor button[data-type="u-underline-style"]');
  var underlineRange = null, underlineMode = null, underlineStyle = "solid";
  var underlineStyles = ["solid", "double", "wavy", "dashed", "dotted"];
  var highlightNames = [];
  var bookmarks = new WeakMap();
  var style = document.createElement("style");
  document.head.appendChild(style);
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", panel.id);
  underlineButton.setAttribute("aria-haspopup", "dialog");
  underlineButton.setAttribute("aria-expanded", "false");
  underlineButton.setAttribute("aria-controls", underlinePanel.id);

  function root() { return editor.vditor[editor.getCurrentMode()].element; }
  function textNodes(element) {
    var walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), nodes = [];
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (editor.getCurrentMode() !== "sv" && node.parentElement && node.parentElement.closest(
          '[data-type="html-inline"], .vditor-ir__marker, .vditor-ir__preview, .vditor-wysiwyg__preview, [data-type$="-marker"]')) { continue; }
      if (node.nodeValue.replace(/\u200b/g, "")) { nodes.push(node); }
    }
    return nodes;
  }
  function plainText(element) {
    return textNodes(element).map(function (node) { return node.nodeValue.replace(/\u200b/g, ""); }).join("");
  }
  function nodeOffset(node, position) {
    if (!position) { return 0; }
    var count = 0;
    for (var i = 0; i < node.nodeValue.length; i++) {
      if (node.nodeValue[i] !== "\u200b" && ++count === position) { return i + 1; }
    }
    return node.nodeValue.length;
  }
  function currentRange() {
    var selection = window.getSelection();
    if (!selection.rangeCount) { return null; }
    var range = selection.getRangeAt(0);
    if (!root().contains(range.commonAncestorContainer)) { return null; }
    range = range.cloneRange();
    var prefix = document.createRange(); prefix.selectNodeContents(root());
    prefix.setEnd(range.startContainer, range.startOffset);
    var start = plainText(prefix.cloneContents()).length;
    var selected = plainText(range.cloneContents());
    bookmarks.set(range, { mode: editor.getCurrentMode(), text: plainText(root()),
                          selected: selected, start: start, end: start + selected.length });
    return range;
  }
  function restoreRange(range) {
    editor.focus();
    if (!range) { return null; }
    var bookmark = bookmarks.get(range);
    if (!root().contains(range.startContainer) || !root().contains(range.endContainer) ||
        (bookmark && plainText(range.cloneContents()) !== bookmark.selected)) {
      // 延迟重绘会替换节点和零宽标记；正文未改变时按文字位置找回选区。
      if (!bookmark || bookmark.mode !== editor.getCurrentMode() || bookmark.text !== plainText(root())) { return null; }
      var nodes = textNodes(root()), offset = 0;
      var restored = document.createRange(), hasStart = false, hasEnd = false;
      for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i], end = offset + node.nodeValue.replace(/\u200b/g, "").length;
        if (!hasStart && bookmark.start <= end) { restored.setStart(node, nodeOffset(node, bookmark.start - offset)); hasStart = true; }
        if (hasStart && bookmark.end <= end) { restored.setEnd(node, nodeOffset(node, bookmark.end - offset)); hasEnd = true; break; }
        offset = end;
      }
      if (!hasStart || !hasEnd) { return null; }
      range = restored;
    }
    var selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    return range;
  }
  function normalizedColor(value) {
    var result = value.trim().toLowerCase();
    if (/^#[0-9a-f]{3}$/.test(result)) { result = "#" + result.slice(1).split("").map(function (c) { return c + c; }).join(""); }
    return /^#[0-9a-f]{6}$/.test(result) ? result : null;
  }
  function foreground(background) {
    var rgb = [1, 3, 5].map(function (start) { return parseInt(background.slice(start, start + 2), 16) / 255; });
    var luminance = rgb.map(function (v) { return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    var brightness = luminance[0] * .2126 + luminance[1] * .7152 + luminance[2] * .0722;
    return brightness > .26 ? "#272724" : brightness > .179 ? "#000000" : "#ffffff";
  }

  function completeIRFormats(element) {
    // 跨格式选区会截掉 IR 的开/闭标记，补全标记后再交给 Lute 序列化。
    var formats = { strong: ["strong", "**"], em: ["em", "*"], s: ["s", "~~"],
                    mark: ["mark", "=="], sup: ["sup", "^"], sub: ["sub", "~"], code: ["code", "`"] };
    Object.keys(formats).forEach(function (type) {
      element.querySelectorAll('[data-type="' + type + '"]').forEach(function (node) {
        var content = node.querySelector(":scope > " + formats[type][0]);
        if (!content) { return; }
        if (!content.textContent.replace(/\u200b/g, "") && !content.querySelector("img")) { node.remove(); return; }
        var markers = Array.from(node.children).filter(function (child) { return child.classList.contains("vditor-ir__marker"); });
        var token = markers.length ? markers[0].textContent : formats[type][1];
        function marker() { var span = document.createElement("span"); span.className = "vditor-ir__marker"; span.textContent = token; return span; }
        if (!node.firstElementChild.classList.contains("vditor-ir__marker")) { node.prepend(marker()); }
        if (!node.lastElementChild.classList.contains("vditor-ir__marker")) { node.appendChild(marker()); }
      });
    });
  }

  function applyFormat(prefix, suffix, range) {
    range = restoreRange(range);
    if (!range) { return; }
    var selection = "";
    if (!range.collapsed) {
      if (editor.getCurrentMode() === "sv") { selection = range.toString(); }
      else {
        var fragment = document.createElement("div");
        fragment.appendChild(range.cloneContents());
        if (editor.getCurrentMode() === "ir") { completeIRFormats(fragment); }
        fragment.querySelectorAll('img[data-osrc]').forEach(function (image) {
          image.setAttribute("src", image.getAttribute("data-osrc")); image.removeAttribute("data-osrc");
        });
        var lute = editor.vditor.lute;
        var html = fragment.innerHTML;
        if (!fragment.querySelector('[data-block]')) { html = '<p data-block="0">' + html + '</p>'; }
        selection = (editor.getCurrentMode() === "ir" ? lute.VditorIRDOM2Md(html) : lute.VditorDOM2Md(html)).replace(/\n+$/, "");
      }
    }
    // 工具栏操作需要独立的撤销记录，不能被编辑器的输入防抖合并。
    editor.vditor.undo.addToUndoStack(editor.vditor);
    if (!range.collapsed) {
      range.deleteContents();
      bookmarks.delete(range);
      if (editor.getCurrentMode() === "ir") { completeIRFormats(root()); }
      restoreRange(range);
    }
    editor.insertMD(prefix + (selection || window.uiText("文本")) + suffix);
    editor.vditor.undo.addToUndoStack(editor.vditor);
    changed(); refreshFormats();
  }

  function closePanel(restore) {
    panel.hidden = true; button.setAttribute("aria-expanded", "false");
    if (restore) { restoreRange(savedRange); }
    savedRange = null;
  }
  function closeUnderlinePanel(restore) {
    underlinePanel.hidden = true; underlineButton.setAttribute("aria-expanded", "false");
    if (restore) { restoreRange(underlineRange); }
    underlineRange = null;
  }
  function positionPanel(popup, anchorButton) {
    document.getElementById("mdv-toolbar-tooltip").style.display = "none";
    var anchor = anchorButton.getBoundingClientRect();
    var left = Math.max(8, Math.min(anchor.left, window.innerWidth - popup.offsetWidth - 8));
    var top = anchor.bottom + 8;
    if (top + popup.offsetHeight > window.innerHeight - 8) { top = Math.max(8, anchor.top - popup.offsetHeight - 8); }
    popup.style.left = left + "px"; popup.style.top = top + "px";
  }
  function applyUnderline(range) {
    var prefix = underlineStyle === "solid" ? "<u>" : '<u style="text-decoration-style: ' + underlineStyle + '">';
    applyFormat(prefix, "</u>", range);
  }
  function chooseColor(value) {
    var selected = normalizedColor(value);
    if (!selected) {
      hexInput.setAttribute("aria-invalid", "true"); error.hidden = false; hexInput.focus(); return;
    }
    color = selected;
    picker.value = color; hexInput.value = color.toUpperCase();
    hexInput.removeAttribute("aria-invalid"); error.hidden = true;
    button.querySelector("rect").setAttribute("fill", color);
    button.querySelector("text").setAttribute("fill", foreground(color));
    if (savedMode === editor.getCurrentMode() && savedRange) {
      applyFormat('<mark style="background-color: ' + color + '; color: ' + foreground(color) + '">', '</mark>', savedRange);
    }
    closePanel(false);
  }
  window.applyUnderline = function () {
    if (!underlinePanel.hidden) { closeUnderlinePanel(true); }
    if (!panel.hidden) { closePanel(true); }
    applyUnderline(currentRange());
  };
  window.openUnderlineStyles = function () {
    if (!underlinePanel.hidden) { closeUnderlinePanel(true); return; }
    if (!panel.hidden) { closePanel(true); }
    underlineRange = currentRange(); underlineMode = editor.getCurrentMode();
    underlinePanel.hidden = false; underlineButton.setAttribute("aria-expanded", "true");
    underlinePanel.querySelectorAll("[data-underline-style]").forEach(function (option) {
      var selected = option.dataset.underlineStyle === underlineStyle;
      option.setAttribute("aria-pressed", String(selected));
      option.querySelector(".underline-check").textContent = selected ? "✓" : "";
    });
    positionPanel(underlinePanel, underlineButton);
    underlinePanel.querySelector('[aria-pressed="true"]').focus({ preventScroll: true });
  };
  [["单横线", "solid"], ["双横线", "double"], ["波浪线", "wavy"],
   ["虚线", "dashed"], ["点线", "dotted"]].forEach(function (preset) {
    var option = document.createElement("button");
    option.type = "button"; option.dataset.underlineStyle = preset[1];
    option.setAttribute("aria-label", preset[0]);
    var preview = document.createElement("span"); preview.className = "underline-preview";
    preview.textContent = "Aa"; preview.style.textDecorationStyle = preset[1]; preview.setAttribute("aria-hidden", "true");
    var label = document.createElement("span"); label.textContent = preset[0];
    var check = document.createElement("span"); check.className = "underline-check"; check.setAttribute("aria-hidden", "true");
    option.append(preview, label, check);
    option.addEventListener("click", function () {
      underlineStyle = preset[1];
      if (underlineMode === editor.getCurrentMode() && underlineRange) { applyUnderline(underlineRange); }
      closeUnderlinePanel(false);
    });
    document.getElementById("mdv-underline-options").appendChild(option);
  });
  underlinePanel.addEventListener("keydown", function (event) {
    var options = Array.from(underlinePanel.querySelectorAll("button"));
    var index = options.indexOf(document.activeElement), next;
    if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Tab") {
      var previous = event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey);
      next = (index + (previous ? -1 : 1) + options.length) % options.length;
    } else if (event.key === "Home") { next = 0; }
    else if (event.key === "End") { next = options.length - 1; }
    if (next !== undefined) { event.preventDefault(); options[next].focus(); }
  });
  window.openHighlightColors = function () {
    if (!panel.hidden) { closePanel(true); return; }
    if (!underlinePanel.hidden) { closeUnderlinePanel(true); }
    savedRange = currentRange(); savedMode = editor.getCurrentMode();
    picker.value = color; hexInput.value = color.toUpperCase();
    hexInput.removeAttribute("aria-invalid"); error.hidden = true;
    panel.hidden = false; button.setAttribute("aria-expanded", "true");
    panel.querySelectorAll("[data-color]").forEach(function (swatch) {
      var selected = swatch.dataset.color === color;
      swatch.setAttribute("aria-pressed", String(selected)); swatch.textContent = selected ? "✓" : "";
    });
    positionPanel(panel, button);
    panel.querySelector("button").focus({ preventScroll: true });
  };
  [["黄色", "#ffe58f"], ["绿色", "#bbf7d0"], ["蓝色", "#bfdbfe"],
   ["粉色", "#fecdd3"], ["紫色", "#ddd6fe"], ["橙色", "#fed7aa"]].forEach(function (preset) {
    var swatch = document.createElement("button");
    swatch.type = "button"; swatch.style.backgroundColor = preset[1];
    swatch.setAttribute("aria-label", preset[0]); swatch.title = preset[0]; swatch.dataset.color = preset[1];
    swatch.addEventListener("click", function () { chooseColor(preset[1]); });
    document.getElementById("mdv-highlight-presets").appendChild(swatch);
  });
  picker.addEventListener("input", function () {
    hexInput.value = picker.value.toUpperCase(); hexInput.removeAttribute("aria-invalid"); error.hidden = true;
  });
  hexInput.addEventListener("input", function () {
    var value = normalizedColor(hexInput.value);
    if (value) { picker.value = value; hexInput.removeAttribute("aria-invalid"); error.hidden = true; }
  });
  document.getElementById("mdv-highlight-apply").onclick = function () { chooseColor(hexInput.value); };
  document.getElementById("mdv-highlight-cancel").onclick = function () { closePanel(true); };
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target === hexInput) { event.preventDefault(); chooseColor(hexInput.value); }
    else if (event.key === "Tab") {
      var inputs = Array.from(panel.querySelectorAll("button, input"));
      var next = (inputs.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1) + inputs.length) % inputs.length;
      event.preventDefault(); inputs[next].focus();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      event.preventDefault(); event.stopImmediatePropagation(); closePanel(true);
    } else if (event.key === "Escape" && !underlinePanel.hidden) {
      event.preventDefault(); event.stopImmediatePropagation(); closeUnderlinePanel(true);
    }
  }, true);
  document.addEventListener("pointerdown", function (event) {
    if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) { closePanel(false); }
    if (!underlinePanel.hidden && !underlinePanel.contains(event.target) && !underlineButton.contains(event.target)) {
      closeUnderlinePanel(false);
    }
  }, true);
  window.addEventListener("resize", function () {
    if (!panel.hidden) { positionPanel(panel, button); }
    if (!underlinePanel.hidden) { positionPanel(underlinePanel, underlineButton); }
  });

  function refreshFormats() {
    if (!CSS.highlights) { return; }
    highlightNames.forEach(function (name) { CSS.highlights.delete(name); });
    highlightNames = [];
    var groups = {}, underline = new Map(), stack = [], element = root();
    element.querySelectorAll("[data-mdv-format-marker]").forEach(function (marker) {
      marker.removeAttribute("data-mdv-format-marker");
    });
    if (editor.getCurrentMode() !== "sv") {
      element.querySelectorAll('[data-type="html-inline"]').forEach(function (marker) {
        if (marker.closest('.vditor-ir__preview, .vditor-wysiwyg__preview')) { return; }
        var tag = marker.textContent.replace(/\u200b/g, "").trim();
        var closing = /^<\/(u|mark)\s*>$/i.exec(tag);
        var opening = /^<(u|mark)(?:\s[^>]*)?>$/i.exec(tag);
        if (opening) {
          var html = document.createElement("template"); html.innerHTML = tag;
          var node = html.content.firstElementChild;
          var selected = node && normalizedColor(node.style.backgroundColor || "");
          // 浏览器会把内联十六进制颜色规范化为 rgb()，读取原属性中的安全色值。
          var attr = /background-color\s*:\s*(#[0-9a-f]{3}(?:[0-9a-f]{3})?)(?:\s*;|\s*$)/i.exec(node && node.getAttribute("style") || "");
          if (attr) { selected = normalizedColor(attr[1]); }
          var lineStyle = node && node.style.textDecorationStyle;
          stack.push({ tag: opening[1].toLowerCase(), marker: marker, color: selected || "#ffe58f", depth: stack.length,
                       lineStyle: underlineStyles.includes(lineStyle) ? lineStyle : "solid" });
        } else if (closing) {
          var index = stack.length - 1;
          while (index >= 0 && stack[index].tag !== closing[1].toLowerCase()) { index--; }
          if (index < 0) { return; }
          var start = stack.splice(index, 1)[0];
          start.marker.dataset.mdvFormatMarker = "true"; marker.dataset.mdvFormatMarker = "true";
          var range = document.createRange(); range.setStartAfter(start.marker); range.setEndBefore(marker);
          // 只绘制正文文字，不给 Markdown 标记、公式代码和图片重复加背景。
          var walker = document.createTreeWalker(range.commonAncestorContainer, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            var text = walker.currentNode;
            if (!range.intersectsNode(text) || !text.nodeValue || text.parentElement.closest(
                '[data-type="html-inline"], .vditor-ir__marker, .vditor-ir__preview, .vditor-wysiwyg__preview, [data-type$="-marker"]')) { continue; }
            var textRange = document.createRange(); textRange.selectNodeContents(text);
            if (start.tag === "u") {
              // 重新选择线型时以最内层为准，避免同一文字同时出现两种下划线。
              var previous = underline.get(text);
              if (!previous || previous.depth < start.depth) {
                underline.set(text, { range: textRange, depth: start.depth, lineStyle: start.lineStyle });
              }
            }
            else {
              var key = start.color + "-" + start.depth;
              (groups[key] || (groups[key] = [])).push(textRange);
            }
          }
        }
      });
    }
    var rules = [];
    underlineStyles.forEach(function (lineStyle) {
      var ranges = Array.from(underline.values()).filter(function (entry) { return entry.lineStyle === lineStyle; })
        .map(function (entry) { return entry.range; });
      var name = lineStyle === "solid" ? "mdv-underline" : "mdv-underline-" + lineStyle;
      if (!ranges.length) { return; }
      CSS.highlights.set(name, new Highlight(...ranges)); highlightNames.push(name);
      rules.push("::highlight(" + name + ") { text-decoration-line: underline; text-decoration-style: " +
                 lineStyle + "; text-decoration-thickness: 1px; }");
    });
    Object.keys(groups).forEach(function (key) {
      var background = key.split("-")[0], depth = Number(key.split("-")[1]);
      var name = "mdv-color-" + key.slice(1), highlight = new Highlight(...groups[key]);
      highlight.priority = depth;
      CSS.highlights.set(name, highlight); highlightNames.push(name);
      rules.push("::highlight(" + name + ") { background-color: " + background + "; color: " + foreground(background) + "; }");
    });
    var css = rules.join("\n");
    if (style.textContent !== css) { style.textContent = css; }
  }
  window.refreshInlineFormats = refreshFormats;
  new MutationObserver(function () {
    clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshFormats, 30);
  }).observe(document.querySelector("#vditor .vditor-content"), { subtree: true, childList: true, characterData: true });
  refreshFormats();
};
