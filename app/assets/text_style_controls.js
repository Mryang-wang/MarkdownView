/* Size and foreground controls share the selection-preserving inline style path. */
window.installTextStyleControls = function (editor, selectionTools, applyStyles) {
  "use strict";
  var size = document.getElementById("mdv-size-panel"), color = document.getElementById("mdv-color-panel");
  var sizeValue = document.getElementById("mdv-size-value");
  var colorValue = document.getElementById("mdv-text-color-value"), hex = document.getElementById("mdv-text-color-hex");
  var sizeButton = document.querySelector('[data-type="mdv-font-size"]'), currentSize = 12;
  var sizePicker = document.createElement("button");
  sizePicker.type = "button"; sizePicker.dataset.type = "mdv-font-size-picker";
  sizePicker.innerHTML = '<svg viewBox="0 0 16 16"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
  sizePicker.onmousedown = function (event) { event.preventDefault(); };
  sizePicker.onclick = function () { window.openSizePicker(); };
  sizeButton.parentElement.appendChild(sizePicker);
  var colorButton = document.querySelector('[data-type="mdv-text-color"]'), currentColor = colorValue.value;
  var colorPicker = document.createElement("button");
  colorPicker.type = "button"; colorPicker.dataset.type = "mdv-text-color-picker";
  colorPicker.innerHTML = sizePicker.innerHTML;
  colorPicker.onmousedown = function (event) { event.preventDefault(); };
  colorPicker.onclick = function () { window.openTextColorPicker(); };
  colorButton.parentElement.appendChild(colorPicker);
  var active = null, range = null, mode = null, anchor = null;
  var buttons = new Map([[size, sizePicker], [color, colorPicker]]);
  function editable() { return !window.mdvReadOnly && !window.mdvTranslationReading && editor.vditor[editor.getCurrentMode()].element.isContentEditable; }
  function close(restore) {
    if (!active) { return; }
    active.hidden = true; buttons.get(active).setAttribute("aria-expanded", "false"); anchor.setAttribute("aria-expanded", "false"); active = null;
    if (restore && mode === editor.getCurrentMode()) { selectionTools.restoreRange(range); }
    range = null;
  }
  function open(panel, trigger) {
    if (!editable()) { return; }
    if (active === panel) { close(true); return; }
    close(true); range = selectionTools.currentRange(); mode = editor.getCurrentMode(); active = panel;
    anchor = trigger || buttons.get(panel);
    var selected = !!range && !range.collapsed;
    panel.querySelectorAll("button:not([data-cancel])").forEach(function (button) {
      button.disabled = !selected && (panel !== size || button.hasAttribute("data-reset"));
    });
    if (panel === size) {
      sizeValue.value = currentSize;
      panel.querySelector(".text-style-notice").textContent = window.uiText("未选中文字时，仅记住字号，不修改正文。");
    } else {
      colorValue.value = currentColor; hex.value = currentColor.toUpperCase();
    }
    panel.querySelector(".text-style-notice").hidden = selected;
    panel.hidden = false; buttons.get(panel).setAttribute("aria-expanded", "true"); anchor.setAttribute("aria-expanded", "true");
    selectionTools.positionPanel(panel, anchor);
    var input = panel === size ? sizeValue : hex; input.focus({preventScroll: true}); input.select();
  }
  function apply(styles) {
    if (applyStyles(styles, range, mode)) { close(false); }
  }
  function applyColor(value) {
    if (!/^#[\da-f]{6}$/i.test(value)) { hex.reportValidity(); return; }
    currentColor = value.toLowerCase();
    hex.value = value.toUpperCase(); colorValue.value = currentColor;
    colorButton.querySelector("rect").setAttribute("fill", currentColor);
    apply({color: currentColor});
  }
  window.openSizePicker = function (trigger) { open(size, trigger); };
  function chooseSize(value) {
    if (!editable() || !Number.isFinite(value) || value < 6 || value > 96 || value * 2 !== Math.round(value * 2)) { return; }
    currentSize = value; sizeValue.value = value;
    sizeButton.querySelector("span").textContent = value + " pt";
    sizeButton.dataset.fontSize = String(value);
    // A redraw can collapse the saved DOM Range; applyStyles restores its text
    // bookmark before checking whether any text is selected.
    if (range && mode === editor.getCurrentMode()) { applyStyles({fontSize: value + "pt"}, range, mode); }
    close(false);
  }
  window.applyFontSize = function () {
    if (!editable()) { return; }
    close(true);
    var selected = selectionTools.currentRange();
    if (selected && !selected.collapsed) { applyStyles({fontSize: currentSize + "pt"}, selected, editor.getCurrentMode()); }
  };
  window.openTextColorPicker = function (trigger) { open(color, trigger); };
  window.applyTextColor = function () {
    if (!editable()) { return; }
    close(true);
    var selected = selectionTools.currentRange();
    if (selected && !selected.collapsed) { applyStyles({color: currentColor}, selected, editor.getCurrentMode()); }
  };
  [[9, "小五"], [10.5, "五号"], [12, "小四"], [14, "四号"], [15, "小三"], [16, "三号"],
   [18, "小二"], [22, "二号"], [24, "小一"], [26, "一号"], [36, "小初"]].forEach(function (preset) {
    var button = document.createElement("button"); button.type = "button"; button.dataset.size = preset[0];
    button.textContent = preset[0] + " pt · " + preset[1];
    button.onclick = function () { chooseSize(preset[0]); };
    document.getElementById("mdv-size-presets").appendChild(button);
  });
  [["黑色", "#2d2d29"], ["灰色", "#6b7280"], ["红色", "#c62828"], ["橙色", "#d97706"],
   ["绿色", "#16803c"], ["蓝色", "#2563eb"], ["紫色", "#7c3aed"], ["白色", "#ffffff"]].forEach(function (preset) {
    var button = document.createElement("button"); button.type = "button"; button.dataset.color = preset[1];
    button.style.backgroundColor = preset[1]; button.setAttribute("aria-label", preset[0]); button.title = preset[0];
    button.onclick = function () { applyColor(preset[1]); }; document.getElementById("mdv-text-colors").appendChild(button);
  });
  size.onsubmit = function (event) {
    event.preventDefault(); if (!size.reportValidity()) { return; }
    var value = sizeValue.valueAsNumber;
    chooseSize(value);
  };
  color.onsubmit = function (event) { event.preventDefault(); if (color.reportValidity()) { applyColor(hex.value.trim()); } };
  colorValue.oninput = function () { hex.value = colorValue.value.toUpperCase(); };
  hex.oninput = function () { if (/^#[\da-f]{6}$/i.test(hex.value)) { colorValue.value = hex.value; } };
  size.querySelector("[data-reset]").onclick = function () {
    var value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--reading-size")) || 15;
    apply({fontSize: value + "px"});
  };
  color.querySelector("[data-reset]").onclick = function () { apply({color: "var(--mdv-text-color)"}); };
  buttons.forEach(function (button, panel) {
    button.setAttribute("aria-haspopup", "dialog"); button.setAttribute("aria-expanded", "false"); button.setAttribute("aria-controls", panel.id);
    panel.querySelector("[data-cancel]").onclick = function () { close(true); };
    panel.addEventListener("keydown", function (event) {
      if (event.isComposing) { return; }
      if (event.key === "Tab") {
        var controls = Array.from(panel.querySelectorAll("input,button:not(:disabled)"));
        var next = (controls.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
        event.preventDefault(); controls[next].focus();
      }
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.isComposing) { return; }
    if (event.key === "Escape" && active) { event.preventDefault(); event.stopImmediatePropagation(); close(true); }
  }, true);
  document.addEventListener("pointerdown", function (event) {
    if (active && !active.contains(event.target) && !buttons.get(active).contains(event.target) && !anchor.contains(event.target) &&
        !(active === size && sizeButton.contains(event.target)) && !(active === color && colorButton.contains(event.target))) { close(false); }
  }, true);
  window.addEventListener("resize", function () { if (active) { selectionTools.positionPanel(active, anchor); } });
};
