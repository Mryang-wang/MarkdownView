/* Selection actions reuse the main toolbar; showing this UI never scans the document. */
window.installSelectionToolbar = function (editor) {
  "use strict";
  const bar = document.createElement("div");
  bar.id = "mdv-selection-toolbar"; bar.hidden = true;
  bar.setAttribute("role", "toolbar"); bar.setAttribute("aria-label", "选中文字操作");
  document.body.appendChild(bar);
  const actions = new Map(), popups = new Map([
    ["mdv-font", ["mdv-font-panel", "openFontPicker"]],
    ["mdv-font-size", ["mdv-size-panel", "openSizePicker"]],
    ["mdv-text-color", ["mdv-color-panel", "openTextColorPicker"]]
  ]);
  let savedRange = null, savedMode = null, popup = null;
  let dragging = false, composing = false, dismissed = false, applying = false, timer = 0, frame = 0;
  const root = () => editor.vditor[editor.getCurrentMode()].element;
  const viewport = () => root().closest(".vditor-ir,.vditor-wysiwyg,.vditor-sv");
  const editable = () => !window.mdvReadOnly && !window.mdvTranslationReading && root().isContentEditable && !root().closest("[inert]");
  function liveRange() {
    const selection = getSelection();
    if (!editable() || !selection.rangeCount || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0), element = root();
    return element.contains(range.startContainer) && element.contains(range.endContainer) ? range : null;
  }
  function cancel() {
    clearTimeout(timer); timer = 0;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }
  function hide() {
    cancel(); bar.hidden = true; bar.classList.remove("is-visible"); savedRange = null;
  }
  function dismiss() { dismissed = true; hide(); }
  function schedule() {
    cancel();
    if (dragging || composing || dismissed || document.hidden || (popup && !popup.hidden)) return;
    timer = setTimeout(() => { timer = 0; frame = requestAnimationFrame(prepare); }, 60);
  }
  // Read only the two endpoints. Measuring an entire Ctrl+A range would force
  // layout of off-screen paragraphs and formula previews in a long document.
  function edgeRect(range, start) {
    const edge = range.cloneRange(); edge.collapse(start);
    const rect = edge.getBoundingClientRect();
    if (rect.height) return rect;
    const node = edge.startContainer;
    const element = node.nodeType === Node.ELEMENT_NODE
      ? (node.childNodes[edge.startOffset] || node.childNodes[edge.startOffset - 1] || node)
      : node.parentElement;
    return (element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement).getBoundingClientRect();
  }
  function prepare() {
    frame = 0;
    const range = liveRange(), focused = document.activeElement;
    if (!range || dragging || composing || dismissed ||
        (!root().contains(focused) && !bar.contains(focused))) { hide(); return; }
    const pane = viewport().getBoundingClientRect();
    const width = Math.max(0, Math.min(innerWidth, pane.right) - Math.max(0, pane.left) - 16);
    if (!pane.height || width < 80) { hide(); return; }
    savedRange = range.cloneRange(); savedMode = editor.getCurrentMode();
    const maxWidth = width + "px", resizing = bar.style.maxWidth !== maxWidth;
    const opening = bar.hidden;
    if (resizing) bar.style.maxWidth = maxWidth;
    if (opening) { bar.style.visibility = "hidden"; bar.hidden = false; }
    // New content/width is laid out before measuring the small toolbar next frame.
    if (opening || resizing) frame = requestAnimationFrame(place);
    else place();
  }
  function place() {
    frame = 0;
    const range = liveRange();
    if (!range || dragging || composing || dismissed || document.hidden) { hide(); return; }
    const pane = viewport().getBoundingClientRect();
    const first = edgeRect(range, true), last = edgeRect(range, false);
    const top = Math.max(0, pane.top) + 8, bottom = Math.min(innerHeight, pane.bottom) - 8;
    const left = Math.max(0, pane.left) + 8, right = Math.min(innerWidth, pane.right) - 8;
    const width = bar.offsetWidth, height = bar.offsetHeight, gap = 8;
    const visible = rect => rect.height && rect.bottom > top && rect.top < bottom && rect.right >= left && rect.left <= right;
    if ((!visible(first) && !visible(last)) || bottom - top < height) { hide(); return; }
    let anchor, y;
    if (visible(first) && first.top - height - gap >= top) { anchor = first; y = first.top - height - gap; }
    else if (visible(last) && last.bottom + height + gap <= bottom) { anchor = last; y = last.bottom + gap; }
    else { anchor = visible(last) ? last : first; y = Math.max(top, Math.min(bottom - height, anchor.top - height - gap)); }
    const center = Math.abs(first.top - last.top) < 2 ? (first.left + last.right) / 2 : anchor.left;
    const x = Math.max(left, Math.min(right - width, center - width / 2));
    savedRange = range.cloneRange(); savedMode = editor.getCurrentMode();
    bar.style.left = Math.round(x) + "px"; bar.style.top = Math.round(y) + "px";
    bar.style.visibility = ""; bar.classList.add("is-visible");
  }
  ["mdv-font", "mdv-font-size", "bold", "italic", "u-underline", "mdv-text-color", "u-mark"].forEach(name => {
    const original = document.querySelector('#vditor .vditor-toolbar [data-type="' + name + '"]');
    const button = document.createElement("button");
    button.type = "button"; button.dataset.selectionAction = name;
    button.innerHTML = original.innerHTML;
    button.title = original.getAttribute("data-mdv-tip"); button.setAttribute("aria-label", button.title);
    if (popups.has(name)) {
      button.setAttribute("aria-haspopup", "dialog"); button.setAttribute("aria-expanded", "false");
      button.setAttribute("aria-controls", popups.get(name)[0]);
    }
    button.onclick = () => {
      if (!editable() || savedMode !== editor.getCurrentMode() || !savedRange || savedRange.collapsed ||
          !root().contains(savedRange.startContainer) || !root().contains(savedRange.endContainer) || button.disabled) { dismiss(); return; }
      applying = true;
      try {
        root().focus({preventScroll: true});
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(savedRange.cloneRange());
        if (popups.has(name)) {
          const [id, open] = popups.get(name); popup = document.getElementById(id);
          window[open](button); if (popup.hidden) popup = null;
        } else original.click();
      } finally { applying = false; }
      schedule();
    };
    actions.set(name, button); bar.appendChild(button);
    function sync() {
      button.disabled = original.disabled || original.classList.contains("vditor-menu--disabled");
      if (name === "bold" || name === "italic") button.setAttribute("aria-pressed", String(original.classList.contains("vditor-menu--current")));
      if (name === "mdv-text-color") button.querySelector("rect").setAttribute("fill", original.querySelector("rect").getAttribute("fill"));
    }
    new MutationObserver(sync).observe(original, {attributes: true, subtree: name === "mdv-text-color", attributeFilter: ["class", "disabled", "fill"]});
    sync();
  });
  bar.addEventListener("mousedown", event => { if (event.button === 0) event.preventDefault(); });
  bar.addEventListener("keydown", event => {
    const buttons = [...actions.values()].filter(button => !button.disabled);
    const index = buttons.indexOf(document.activeElement);
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault(); buttons[(index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    } else if (event.key === "Escape") { event.preventDefault(); dismiss(); root().focus({preventScroll: true}); }
  });
  document.addEventListener("selectionchange", schedule);
  document.addEventListener("pointerdown", event => {
    if (bar.contains(event.target) || (popup && popup.contains(event.target))) return;
    if (event.button === 0 && root().contains(event.target)) { dismissed = false; dragging = true; hide(); }
    else dismiss();
  }, true);
  document.addEventListener("pointerup", event => {
    if (event.button !== 0 || !dragging) return;
    dragging = false; schedule();
  }, true);
  document.addEventListener("pointercancel", () => { dragging = false; dismiss(); }, true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !popup) { dismiss(); return; }
    if (event.altKey && event.key === "F10" && !bar.hidden) {
      event.preventDefault(); [...actions.values()].find(button => !button.disabled)?.focus();
    }
  });
  document.addEventListener("keyup", event => {
    if (!root().contains(event.target) || event.isComposing) return;
    if (/^(Arrow|Home|End|Page)/.test(event.key) || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a")) {
      dismissed = false; schedule();
    }
  });
  document.addEventListener("beforeinput", event => { if (!applying && root().contains(event.target)) dismiss(); }, true);
  document.addEventListener("compositionstart", event => { if (root().contains(event.target)) { composing = true; dismiss(); } }, true);
  document.addEventListener("compositionend", () => { composing = false; }, true);
  document.addEventListener("scroll", event => { if (!popup || !popup.contains(event.target)) dismiss(); }, true);
  document.addEventListener("visibilitychange", () => { dragging = false; dismiss(); });
  window.addEventListener("blur", () => { dragging = false; dismiss(); });
  window.addEventListener("resize", dismiss);
  const stateObserver = new MutationObserver(() => { if (!editable()) dismiss(); else if (!bar.hidden) schedule(); });
  ["ir", "wysiwyg", "sv"].forEach(mode => {
    stateObserver.observe(editor.vditor[mode].element, {attributes: true, attributeFilter: ["contenteditable", "style"]});
    stateObserver.observe(editor.vditor[mode].element.parentElement, {attributes: true, attributeFilter: ["style"]});
  });
  stateObserver.observe(document.getElementById("vditor"), {attributes: true, attributeFilter: ["inert"]});
  new MutationObserver(() => { if (!bar.hidden) schedule(); }).observe(document.documentElement, {attributes: true, attributeFilter: ["lang", "style"]});
  const popupObserver = new MutationObserver(() => { if (popup && popup.hidden) { popup = null; schedule(); } });
  popups.forEach(([id]) => popupObserver.observe(document.getElementById(id), {attributes: true, attributeFilter: ["hidden"]}));
};
