/* Paragraph metadata stays inline so headings, lists and tables remain Markdown. */
(function () {
  "use strict";
  const alignments = [["left", "左对齐"], ["center", "居中对齐"], ["right", "右对齐"],
    ["justify", "两端对齐"], ["distribute", "分散对齐"]];
  const blocks = "p,h1,h2,h3,h4,h5,h6,li,td,th";
  function icon(alignment) {
    const paths = {left: "M3 4h18M3 9h12M3 14h18M3 19h12", center: "M3 4h18M6 9h12M3 14h18M6 19h12",
      right: "M3 4h18M9 9h12M3 14h18M9 19h12", justify: "M3 4h18M3 9h18M3 14h18M3 19h18",
      distribute: "M3 9h18M3 14h18M3 19h18M3 2v4M21 2v4M6 4h12m-9-2-3 2 3 2m6-4 3 2-3 2",
      line: "M10 5h11M10 12h11M10 19h11M4 3v18M1 6l3-3 3 3M1 18l3 3 3-3"};
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + paths[alignment] +
      '" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  window.paragraphToolbar = alignments.map(([value, tip]) => ({name: "mdv-align-" + value, tip, tipPosition: "s",
    icon: icon(value), click() { window.applyParagraphAlignment(value); }})).concat({name: "mdv-line-spacing", tip: "段落行距", tipPosition: "s",
    icon: icon("line"), click() { window.openLineSpacing(); }});

  function properties(style) {
    const result = {};
    if (["left", "center", "right", "justify"].includes(style.textAlign)) {
      result.align = style.textAlign === "justify" && style.textAlignLast === "justify" ? "distribute" : style.textAlign;
    }
    if (/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(style.lineHeight)) {
      const line = Number(style.lineHeight);
      if (line >= 0.5 && line <= 5) result.line = line;
    }
    return result;
  }
  function applyStyle(block, value) {
    const styles = {textAlign: value.align === "distribute" ? "justify" : value.align || "",
      textAlignLast: value.align === "distribute" ? "justify" : "", textJustify: value.align === "distribute" ? "inter-character" : "",
      lineHeight: value.line ? String(value.line) : ""};
    Object.keys(styles).forEach(key => { if (block.style[key] !== styles[key]) block.style[key] = styles[key]; });
  }
  window.renderParagraphStyles = function (root) {
    root.querySelectorAll('span[data-mdv-paragraph="true"]').forEach(marker => {
      const block = marker.closest(blocks);
      if (block && root.contains(block)) applyStyle(block, properties(marker.style));
    });
  };

  window.installParagraphFeatures = function (editor, selectionTools, changed) {
    const panel = document.getElementById("mdv-line-panel"), input = document.getElementById("mdv-line-value");
    const buttons = Array.from(document.querySelectorAll('[data-type^="mdv-align-"], [data-type="mdv-line-spacing"]'));
    const lineButton = buttons[buttons.length - 1];
    let savedRange = null, savedMode = null, selectionFrame = 0, composing = false;
    const parsedMarkers = new WeakMap();
    function root() { return editor.vditor[editor.getCurrentMode()].element; }
    function editable() { return editor.getCurrentMode() !== "sv" && !window.mdvReadOnly && !window.mdvTranslationReading && root().isContentEditable; }
    function eligible(block) {
      const excluded = block.closest('pre,[data-type="html-block"],.vditor-ir__preview,.vditor-wysiwyg__preview');
      return (!excluded || excluded === root()) && !Array.from(block.children).some(child => child.matches(blocks));
    }
    function targetBlocks(range) {
      if (!range || !root().contains(range.commonAncestorContainer)) return [];
      if (range.collapsed || !range.toString().replace(/\u200b/g, "")) {
        const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
        const block = node.closest(blocks);
        return block && root().contains(block) && eligible(block) ? [block] : [];
      }
      const ancestor = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
      const scopeRoot = ancestor.closest(blocks) || ancestor;
      const candidates = Array.from(scopeRoot.querySelectorAll(blocks));
      if (scopeRoot.matches(blocks)) candidates.unshift(scopeRoot);
      return candidates.filter(block => {
        if (!eligible(block)) return false;
        const scope = document.createRange(); scope.selectNodeContents(block);
        const nested = block.querySelector(':scope > ul,:scope > ol');
        if (nested) scope.setEndBefore(nested);
        if (range.compareBoundaryPoints(Range.END_TO_START, scope) >= 0 || range.compareBoundaryPoints(Range.START_TO_END, scope) <= 0) return false;
        const overlap = range.cloneRange();
        if (overlap.compareBoundaryPoints(Range.START_TO_START, scope) < 0) overlap.setStart(scope.startContainer, scope.startOffset);
        if (overlap.compareBoundaryPoints(Range.END_TO_END, scope) > 0) overlap.setEnd(scope.endContainer, scope.endOffset);
        const fragment = overlap.cloneContents();
        return selectionTools.textNodes(fragment).some(node => node.nodeValue.replace(/\u200b/g, "").length) || !!fragment.querySelector("img,br");
      });
    }
    function markers(block) {
      const found = [];
      const nodes = Array.from(block.querySelectorAll('[data-type="html-inline"]')).filter(node => node.closest(blocks) === block);
      nodes.forEach((node, i) => {
        const raw = node.textContent.replace(/\u200b/g, "").trim();
        if (!/^<span\s/i.test(raw) || !/data-mdv-paragraph=["']true["']/.test(raw)) return;
        let cached = parsedMarkers.get(node);
        if (!cached || cached.raw !== raw) {
          const template = document.createElement("template"); template.innerHTML = raw;
          const element = template.content.firstElementChild;
          cached = {raw, value: element && element.matches('span[data-mdv-paragraph="true"]') ? properties(element.style) : null};
          parsedMarkers.set(node, cached);
        }
        if (!cached.value) return;
        const closing = nodes[i + 1];
        if (closing && /^<\/span\s*>$/i.test(closing.textContent.replace(/\u200b/g, "").trim())) {
          found.push({node, closing, value: cached.value});
        }
      });
      return found;
    }
    function value(block) { return Object.assign({}, ...markers(block).map(entry => entry.value)); }
    function marker(tag) {
      const ir = editor.getCurrentMode() === "ir", node = document.createElement(ir ? "span" : "code");
      node.dataset.type = "html-inline";
      if (ir) {
        node.className = "vditor-ir__node";
        const code = document.createElement("code"); code.className = "vditor-ir__marker"; code.textContent = tag; node.append(code);
      } else node.textContent = "\u200b" + tag;
      return node;
    }
    function apply(patch, range, mode) {
      if (!editable() || composing || mode !== editor.getCurrentMode()) return false;
      range = selectionTools.restoreRange(range);
      if (!targetBlocks(range).length) return false;
      editor.vditor.undo.addToUndoStack(editor.vditor);
      range = selectionTools.restoreRange(range);
      const selected = targetBlocks(range), bookmark = selectionTools.currentRange();
      if (!selected.length) return false;
      const scroll = root().closest(".vditor-ir,.vditor-wysiwyg"), top = scroll.scrollTop;
      selected.forEach(block => {
        const style = Object.assign(value(block), patch);
        markers(block).forEach(entry => { entry.node.remove(); entry.closing.remove(); });
        if (style.align || style.line) {
          const span = document.createElement("span"); span.dataset.mdvParagraph = "true"; applyStyle(span, style);
          // An empty paragraph needs an inline anchor to avoid becoming an HTML block.
          if (!selectionTools.textNodes(block).length && !block.querySelector("img")) block.insertBefore(document.createTextNode("\u200b"), block.firstChild);
          const nested = block.querySelector(':scope > ul,:scope > ol');
          block.insertBefore(marker(span.outerHTML.replace("</span>", "")), nested);
          block.insertBefore(marker("</span>"), nested);
        }
      });
      range = selectionTools.restoreRange(bookmark);
      if (range) { range.collapse(false); getSelection().removeAllRanges(); getSelection().addRange(range); }
      editor.insertMD(""); window.refreshInlineFormats(); selectionTools.restoreRange(bookmark);
      editor.vditor.undo.addToUndoStack(editor.vditor); scroll.scrollTop = top; changed(); updateButtons(); return true;
    }
    window.applyParagraphAlignment = function (alignment) {
      if (alignments.some(entry => entry[0] === alignment)) apply({align: alignment}, selectionTools.currentRange(), editor.getCurrentMode());
    };
    function close(restore) {
      if (panel.hidden) return;
      panel.hidden = true; lineButton.setAttribute("aria-expanded", "false");
      if (restore && savedMode === editor.getCurrentMode()) selectionTools.restoreRange(savedRange);
      savedRange = null;
    }
    window.openLineSpacing = function () {
      if (!panel.hidden) { close(true); return; }
      if (!editable()) return;
      savedRange = selectionTools.currentRange(); savedMode = editor.getCurrentMode();
      const selected = targetBlocks(savedRange);
      if (!selected.length) return;
      input.value = value(selected[0]).line || Number(getComputedStyle(document.documentElement).getPropertyValue("--reading-line")) || 1.9;
      panel.hidden = false; lineButton.setAttribute("aria-expanded", "true");
      selectionTools.positionPanel(panel, lineButton); input.focus(); input.select();
    };
    function setLine(line) { if (apply({line}, savedRange, savedMode)) close(false); }
    [1, 1.15, 1.5, 2, 2.5, 3].forEach(line => {
      const button = document.createElement("button"); button.type = "button"; button.dataset.line = line;
      button.textContent = line + " ×"; button.onclick = () => setLine(line);
      document.getElementById("mdv-line-presets").append(button);
    });
    panel.onsubmit = event => { event.preventDefault(); if (panel.reportValidity()) setLine(input.valueAsNumber); };
    panel.querySelector("[data-reset]").onclick = () => setLine(null);
    panel.querySelector("[data-cancel]").onclick = () => close(true);
    lineButton.setAttribute("aria-haspopup", "dialog"); lineButton.setAttribute("aria-controls", panel.id); lineButton.setAttribute("aria-expanded", "false");
    function updateButtons() {
      const allowed = editable(), selection = getSelection();
      const range = !panel.hidden && savedMode === editor.getCurrentMode() ? savedRange : selection.rangeCount ? selection.getRangeAt(0) : null;
      const selected = allowed ? targetBlocks(range) : [];
      const values = selected.map(block => value(block).align || (getComputedStyle(block).textAlign === "start" ? "left" : getComputedStyle(block).textAlign));
      buttons.forEach(button => {
        const disabled = !allowed || !selected.length;
        if (button.getAttribute("aria-disabled") !== String(disabled)) button.setAttribute("aria-disabled", String(disabled));
        button.classList.toggle("vditor-menu--disabled", disabled);
        if (button !== lineButton) {
          const pressed = String(!!values.length && values.every(item => item === button.dataset.type.slice(10)));
          if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
        }
      });
    }
    window.refreshParagraphFormats = function (scope) {
      if (composing) return;
      if (editor.getCurrentMode() !== "sv") {
        const element = scope || root();
        const candidates = new Set(element.querySelectorAll("[data-mdv-paragraph-styled]"));
        if (element.matches("[data-mdv-paragraph-styled]")) candidates.add(element);
        element.querySelectorAll('[data-type="html-inline"]').forEach(node => {
          if (node.textContent.includes("data-mdv-paragraph")) {
            const block = node.closest(blocks); if (block) candidates.add(block);
          }
        });
        candidates.forEach(block => {
          if (!eligible(block)) return;
          const entries = markers(block);
          if (!entries.length) { applyStyle(block, {}); block.removeAttribute("data-mdv-paragraph-styled"); return; }
          entries.forEach(entry => {
            if (!entry.node.hasAttribute("data-mdv-paragraph-marker")) entry.node.dataset.mdvParagraphMarker = "true";
            if (!entry.closing.hasAttribute("data-mdv-paragraph-marker")) entry.closing.dataset.mdvParagraphMarker = "true";
          });
          applyStyle(block, Object.assign({}, ...entries.map(entry => entry.value)));
          if (!block.hasAttribute("data-mdv-paragraph-styled")) block.dataset.mdvParagraphStyled = "true";
        });
      }
      document.querySelectorAll(".vditor-preview").forEach(window.renderParagraphStyles);
      updateButtons();
    };
    document.addEventListener("selectionchange", () => {
      if (!selectionFrame) selectionFrame = requestAnimationFrame(() => { selectionFrame = 0; updateButtons(); });
    });
    document.addEventListener("compositionstart", () => { composing = true; });
    document.addEventListener("compositionend", () => { composing = false; });
    document.addEventListener("keydown", event => {
      if (event.isComposing || panel.hidden) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(true); }
      else if (event.key === "Tab") {
        const controls = Array.from(panel.querySelectorAll("input,button"));
        event.preventDefault(); controls[(controls.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1) + controls.length) % controls.length].focus();
      }
    }, true);
    document.addEventListener("pointerdown", event => {
      if (!panel.hidden && !panel.contains(event.target) && !lineButton.contains(event.target)) close(!!event.target.closest(".vditor-toolbar"));
    }, true);
    window.addEventListener("resize", () => { if (!panel.hidden) selectionTools.positionPanel(panel, lineButton); });
  };
})();
