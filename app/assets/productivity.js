/* Native preferences and writing modes; no background indexing in the page. */
window.installProductivity = function (editor, changed) {
  "use strict";
  var focusBlock = null;
  window.mdvReadOnly = false;
  window.mdvLightweight = false;
  window.applyReadingPreferences = function (settings) {
    var style = document.documentElement.style;
    style.setProperty("--reading-font", JSON.stringify(settings.font || "Segoe UI"));
    style.setProperty("--reading-size", (Number(settings.size) || 15) + "px");
    style.setProperty("--reading-line", String(Number(settings.line) || 1.9));
    style.setProperty("--reading-paragraph", (Number(settings.paragraph) || 1.2) + "em");
    style.setProperty("--reading-width", (Number(settings.width) || 760) + "px");
  };
  window.setReadOnly = function (enabled) {
    window.mdvReadOnly = !!enabled;
    if (enabled || window.mdvTranslationReading) { editor.disabled(); } else { editor.enable(); }
    document.documentElement.classList.toggle("mdv-readonly", !!enabled);
    var replaceRow = document.getElementById("mdv-replace-row");
    if (enabled && replaceRow) { replaceRow.hidden = true; }
  };
  window.setLightweight = function (enabled) {
    window.mdvLightweight = !!enabled;
    document.documentElement.classList.toggle("mdv-lightweight", !!enabled);
    var readOnly = window.mdvReadOnly;
    if (readOnly) { editor.enable(); }
    var mode = enabled ? "sv" : "ir";
    if (editor.getCurrentMode() !== mode) {
      var control = document.querySelector('[data-mode="' + mode + '"]');
      if (control) { control.click(); }
    }
    if (readOnly || window.mdvTranslationReading) { editor.disabled(); }
  };
  window.setFocusWriting = function (enabled, highlight) {
    document.documentElement.classList.toggle("mdv-focus", !!enabled);
    document.documentElement.classList.toggle("mdv-focus-highlight", !!enabled && !!highlight);
    focusSelection();
  };
  function focusSelection() {
    if (focusBlock) { focusBlock.classList.remove("mdv-current-paragraph"); focusBlock = null; }
    if (!document.documentElement.classList.contains("mdv-focus-highlight")) { return; }
    var selection = window.getSelection(), node = selection && selection.anchorNode;
    if (node) {
      var element = node.nodeType === 1 ? node : node.parentElement;
      var root = editor.vditor[editor.getCurrentMode()].element;
      if (root.contains(element)) {
        while (element && element.parentElement !== root) { element = element.parentElement; }
        if (element) { focusBlock = element; focusBlock.classList.add("mdv-current-paragraph"); }
      }
    }
  }
  document.addEventListener("selectionchange", focusSelection);
  ["beforeinput", "paste", "drop", "cut"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      if (window.mdvReadOnly && event.target.closest("#vditor")) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
  });
  document.addEventListener("click", function (event) {
    if (!window.mdvReadOnly) { return; }
    var target = event.target.closest("#vditor [data-type], #vditor input[type=checkbox]");
    if (!target) { return; }
    var allowed = ["outline", "preview", "mdv-fullscreen", "mdv-review"];
    if (target.closest(".vditor-toolbar") && allowed.indexOf(target.getAttribute("data-type")) < 0 || target.matches("input[type=checkbox]")) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && document.documentElement.classList.contains("mdv-focus")) {
      if (window.bridge && window.bridge.leaveFocusMode) { window.bridge.leaveFocusMode(); }
      event.preventDefault();
    }
  }, true);
  window.insertSnippet = function (markdown) {
    if (window.mdvReadOnly) { return; }
    editor.focus();
    editor.insertValue(markdown);
    changed();
  };
  window.locateSourceLine = function (line) {
    var readOnly = window.mdvReadOnly;
    if (readOnly) { editor.enable(); }
    var control = document.querySelector('[data-mode="sv"]');
    if (editor.getCurrentMode() !== "sv" && control) { control.click(); }
    requestAnimationFrame(function () {
      var root = editor.vditor.sv.element;
      var text = root.textContent, start = 0, end;
      for (var i = 1; i < Number(line); i++) {
        var next = text.indexOf("\n", start); if (next < 0) { break; } start = next + 1;
      }
      end = text.indexOf("\n", start); if (end < 0) { end = text.length; }
      var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), offset = 0, first = null, last = null;
      while (walker.nextNode()) {
        var node = walker.currentNode, size = node.nodeValue.length;
        if (!first && start < offset + size) { first = {node: node, offset: Math.max(0, start - offset)}; }
        if (first && end <= offset + size) { last = {node: node, offset: Math.max(0, end - offset)}; break; }
        offset += size;
      }
      if (first && last) {
        root.focus();
        var range = document.createRange(); range.setStart(first.node, first.offset); range.setEnd(last.node, last.offset);
        var selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        first.node.parentElement.scrollIntoView({block: "center"});
      }
      if (readOnly) { editor.disabled(); }
    });
  };
};
