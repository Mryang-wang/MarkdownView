/* 批注以 Markdown 尾部的 HTML 注释保存，不进入正文或文字统计。 */
window.installReviewFeatures = function (editor, changed, selectionChanged) {
  "use strict";
  var panel = document.getElementById("mdv-review-panel"), composer = document.getElementById("mdv-review-composer");
  var input = document.getElementById("mdv-review-input"), list = document.getElementById("mdv-review-list");
  var message = document.getElementById("mdv-review-message"), toolbar = document.querySelector('[data-type="mdv-review"]');
  var comments = [], activeId = null, editingId = null, pending = null, remembered = null, previous = null, previousMd = null;
  var timer = null, selectionTimer = null, loading = false;
  var excluded = '.vditor-ir__preview,.vditor-wysiwyg__preview,.vditor-ir__marker,[data-type$="-marker"],[data-type="html-inline"],[data-type="newline"],script,style,textarea';
  function root() { return editor.vditor[editor.getCurrentMode()].element; }
  function indexText(element) {
    var selector = excluded + (editor.getCurrentMode() === "sv" ? ',[class*="vditor-sv__marker"]' : '');
    // Reject rendered formula/preview subtrees once instead of visiting every
    // KaTeX text node and walking its ancestors for each statistics refresh.
    var walker = document.createTreeWalker(element, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          return node.matches(selector) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_SKIP;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }), text = "", segments = [], lastBlock = null;
    while (walker.nextNode()) {
      var node = walker.currentNode;
      var value = node.nodeValue.replace(/\u200b/g, "");
      if (!value) { continue; }
      var block = node.parentElement && node.parentElement.closest('p,h1,h2,h3,h4,h5,h6,td,th,li,[data-block]');
      if (lastBlock && block !== lastBlock) { text += "\n"; }
      var start = text.length;
      text += value;
      segments.push({node: node, start: start, end: text.length}); lastBlock = block;
    }
    return {text: text, segments: segments};
  }
  function nodeOffset(node, offset) {
    var count = 0;
    for (var i = 0; i < node.nodeValue.length; i++) {
      if (node.nodeValue[i] !== "\u200b" && count++ === offset) { return i; }
    }
    return node.nodeValue.length;
  }
  function rangeFor(data, anchor) {
    if (anchor.detached || anchor.end <= anchor.start) { return null; }
    // Paragraph separators in the text index have no DOM node. A whole-line
    // selection can end in that gap; use the actual text overlapping the anchor.
    var a = null, b = null;
    for (var i = 0; i < data.segments.length; i++) {
      var s = data.segments[i];
      if (s.start >= anchor.end) { break; }
      if (s.end > anchor.start) { if (!a) { a = s; } b = s; }
    }
    if (!a || !b) { return null; }
    var range = document.createRange();
    range.setStart(a.node, nodeOffset(a.node, Math.max(0, anchor.start - a.start)));
    range.setEnd(b.node, nodeOffset(b.node, Math.min(b.end - b.start, anchor.end - b.start)));
    return range;
  }
  function position(data, node, offset) {
    var segment = data.segments.find(function (s) { return s.node === node; });
    if (segment) { return segment.start + node.nodeValue.slice(0, offset).replace(/\u200b/g, "").length; }
    var point = document.createRange(); point.setStart(node, offset); point.collapse(true);
    for (var i = 0; i < data.segments.length; i++) {
      var s = data.segments[i];
      if (point.comparePoint(s.node, 0) >= 0) { return s.start; }
    }
    return data.text.length;
  }
  function selectedRange() {
    var selection = getSelection();
    if (!selection.rangeCount) { return null; }
    var range = selection.getRangeAt(0);
    return root().contains(range.startContainer) && root().contains(range.endContainer) ? range : null;
  }
  function selectedText() {
    var range = selectedRange();
    return range && !range.collapsed ? indexText(range.cloneContents()).text : "";
  }
  window.editorSelectedText = selectedText;
  window.canAddReviewComment = function () {
    return root().contains(document.activeElement) && !!selectedText().trim();
  };
  window.editorDocumentText = function () { return indexText(root()).text; };
  function anchorAt(data, start, end) {
    return {start: start, end: end, quote: data.text.slice(start, end), before: data.text.slice(Math.max(0, start - 32), start), after: data.text.slice(end, end + 32), detached: false};
  }
  function selectionAnchor() {
    var range = selectedRange();
    if (!range || range.collapsed) { return null; }
    var data = indexText(root());
    var start = position(data, range.startContainer, range.startOffset), end = position(data, range.endContainer, range.endOffset);
    if (end <= start || !data.text.slice(start, end).trim()) { return null; }
    return anchorAt(data, start, end);
  }
  function locate(anchor, data) {
    if (anchor.detached || !anchor.quote) { return false; }
    var text = data.text, candidates = [], at = text.indexOf(anchor.quote);
    while (at >= 0) {
      var before = text.slice(Math.max(0, at - 32), at), after = text.slice(at + anchor.quote.length, at + anchor.quote.length + 32);
      var score = 0;
      for (var i = 1; i <= Math.min(before.length, anchor.before.length); i++) {
        if (before[before.length - i] !== anchor.before[anchor.before.length - i]) { break; } score += 2;
      }
      for (var j = 0; j < Math.min(after.length, anchor.after.length); j++) {
        if (after[j] !== anchor.after[j]) { break; } score += 2;
      }
      candidates.push({at: at, score: score - Math.abs(at - anchor.start) / Math.max(text.length, 1)});
      at = text.indexOf(anchor.quote, at + 1);
    }
    if (!candidates.length) { return false; }
    candidates.sort(function (a, b) { return b.score - a.score; });
    Object.assign(anchor, anchorAt(data, candidates[0].at, candidates[0].at + anchor.quote.length));
    return true;
  }
  function textChange(old, text) {
    if (old === text) { return null; }
    var start = 0, suffix = 0;
    while (start < Math.min(old.length, text.length) && old[start] === text[start]) { start++; }
    while (suffix < Math.min(old.length, text.length) - start && old[old.length - suffix - 1] === text[text.length - suffix - 1]) { suffix++; }
    return {start: start, oldEnd: old.length - suffix, newEnd: text.length - suffix, delta: text.length - old.length};
  }
  function rebase(anchor, data, change) {
    if (anchor.detached || !change) { return; }
    var start = change.start, oldEnd = change.oldEnd, newEnd = change.newEnd, delta = change.delta, text = data.text;
    if (oldEnd <= anchor.start) {
      Object.assign(anchor, anchorAt(data, anchor.start + delta, anchor.end + delta));
    } else if (start >= anchor.end) {
      Object.assign(anchor, anchorAt(data, anchor.start, anchor.end));
    } else if (start <= anchor.start && oldEnd >= anchor.end) {
      // 被删除的原文不能悄悄重新挂到文档中另一处相同文字。
      if (start === oldEnd || !text.slice(start, newEnd).includes(anchor.quote)) { anchor.detached = true; }
      else if (!locate(anchor, data)) { anchor.detached = true; }
    } else {
      var a = Math.min(anchor.start, start), b = anchor.end >= oldEnd ? anchor.end + delta : newEnd;
      if (b <= a) { anchor.detached = true; }
      else { Object.assign(anchor, anchorAt(data, a, b)); }
    }
  }
  function paint(data) {
    CSS.highlights.delete("mdv-comments"); CSS.highlights.delete("mdv-comment-active");
    if (panel.hidden) { return; }
    var ranges = comments.map(function (c) { return rangeFor(data, c.anchor); }).filter(Boolean);
    if (ranges.length) { var highlights = new Highlight(...ranges); highlights.priority = -1; CSS.highlights.set("mdv-comments", highlights); }
    var current = comments.find(function (c) { return c.id === activeId; });
    var range = current && rangeFor(data, current.anchor);
    if (range) { CSS.highlights.set("mdv-comment-active", new Highlight(range)); }
  }
  function refresh() {
    clearTimeout(timer); timer = null;
    if (loading || (!comments.length && !pending && !remembered)) { return; }
    var data = indexText(root()), md = editor.getValue(), edited = previousMd !== null && md !== previousMd;
    // A format/toolbar refresh can rebuild DOM nodes without changing the text.
    // Repaint using the new nodes, but retain the already-resolved anchors.
    var textChanged = !previous || previous.text !== data.text;
    var change = edited && previous ? textChange(previous.text, data.text) : null;
    comments.forEach(function (comment) {
      if (edited && previous) { rebase(comment.anchor, data, change); }
      else if (textChanged && !comment.anchor.detached && !locate(comment.anchor, data)) { comment.anchor.detached = true; }
    });
    [pending, remembered].filter(Boolean).forEach(function (a) {
      if (edited && previous) { rebase(a, data, change); }
      else if (textChanged) { locate(a, data); }
    });
    previous = data; previousMd = md; paint(data); renderList();
  }
  window.refreshReview = function () {
    if (comments.length || pending || remembered) { clearTimeout(timer); timer = setTimeout(refresh, 120); }
  };
  function notice(text) { message.textContent = text; message.hidden = !text; }
  function closeComposer() { pending = null; input.value = ""; composer.hidden = true; }
  window.showReview = function (visible) {
    if (visible && window.translationUI && window.translationUI.active()) { window.translationUI.leave(); }
    panel.hidden = !visible; document.documentElement.setAttribute("data-review-visible", String(!!visible));
    toolbar.classList.toggle("vditor-menu--current", !!visible); toolbar.setAttribute("aria-expanded", String(!!visible));
    if (!visible) { notice(""); }
    if (comments.length) { refresh(); } else { paint(indexText(root())); }
  };
  function focusComment(comment) {
    activeId = comment.id; window.showReview(true); var data = indexText(root()), range = rangeFor(data, comment.anchor);
    if (range) {
      root().focus({preventScroll: true}); var selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
      var scroller = root().scrollHeight > root().clientHeight ? root() : root().parentElement;
      var viewport = scroller.getBoundingClientRect();
      var scale = viewport.height / scroller.offsetHeight || 1;
      scroller.scrollTop += (range.getBoundingClientRect().top - viewport.top) / scale - scroller.clientHeight / 2;
    } else { notice("原文已修改或删除，批注内容仍保留。"); }
    paint(data); renderList();
  }
  function renderList() {
    // Keep existing cards and textareas attached so anchor refreshes cannot
    // interrupt typing, IME composition or the panel's scroll position.
    var signature = JSON.stringify([editingId, comments.map(function (c) { return [c.id, c.text, c.anchor.quote, c.anchor.detached, c.id === activeId]; })]);
    if (list.dataset.signature === signature) { return; } list.dataset.signature = signature;
    var cards = new Map(Array.from(list.children).map(function (card) { return [card.dataset.commentId, card]; }));
    var ids = new Set(comments.map(function (comment) { return comment.id; }));
    cards.forEach(function (card, id) { if (!ids.has(id)) card.remove(); });
    document.getElementById("mdv-review-count").textContent = comments.length;
    document.getElementById("mdv-review-empty").hidden = !!comments.length;
    comments.forEach(function (comment, i) {
      var card = cards.get(comment.id);
      if (!card) {
        card = document.createElement("article"); card.className = "review-card"; card.dataset.commentId = comment.id;
        var header = document.createElement("div"); header.className = "review-card-header";
        var title = document.createElement("span"); title.className = "review-card-title";
        var actions = document.createElement("div"); actions.className = "review-card-actions";
        var edit = document.createElement("button"); edit.type = "button"; edit.className = "review-edit"; edit.textContent = window.uiText("编辑"); edit.title = window.uiText("编辑批注");
        edit.onclick = function (event) { event.stopPropagation(); window.editReviewComment(comment.id); };
        var remove = document.createElement("button"); remove.type = "button"; remove.className = "review-delete"; remove.textContent = "×"; remove.title = window.uiText("删除批注");
        remove.onclick = function (event) { event.stopPropagation(); window.deleteReviewComment(comment.id); };
        actions.append(edit, remove); header.append(title, actions);
        var quote = document.createElement("button"); quote.type = "button"; quote.className = "review-quote"; quote.title = window.uiText("定位原文");
        quote.onclick = function (event) { event.stopPropagation(); var current = comments.find(function (c) { return c.id === comment.id; }); if (current) focusComment(current); };
        var body = document.createElement("p"); card.append(header, quote, body);
        card.onclick = function (event) {
          if (event.target.closest("button,form")) return;
          activeId = comment.id; renderList(); paint(indexText(root()));
        };
      }
      card.classList.toggle("is-active", comment.id === activeId);
      card.querySelector(".review-card-title").textContent = window.uiText("批注 {0}").replace("{0}", i + 1);
      card.querySelector(".review-delete").setAttribute("aria-label", window.uiText("删除批注 {0}").replace("{0}", i + 1));
      var quote = card.querySelector(".review-quote"), body = card.querySelector("p");
      if (quote.textContent !== comment.anchor.quote) quote.textContent = comment.anchor.quote;
      if (body.textContent !== comment.text) body.textContent = comment.text;
      var orphan = card.querySelector("small");
      if (comment.anchor.detached && !orphan) { orphan = document.createElement("small"); orphan.textContent = window.uiText("原文已修改或删除"); card.append(orphan); }
      else if (!comment.anchor.detached && orphan) orphan.remove();
      body.hidden = comment.id === editingId;
      var form = card.querySelector(".review-edit-form");
      if (comment.id === editingId && !form) card.append(createEditForm(comment));
      else if (comment.id !== editingId && form) form.remove();
      if (list.children[i] !== card) list.insertBefore(card, list.children[i] || null);
    });
  }
  function finishEditing() {
    var card = Array.from(list.children).find(function (card) { return card.dataset.commentId === editingId; });
    editingId = null; renderList(); notice("");
    if (card && card.isConnected) card.querySelector(".review-edit").focus({preventScroll: true});
  }
  function validText(text, field) {
    if (!text || text.length > 10000) {
      notice(text ? "批注不能超过 10000 个字符。" : "请输入批注内容。"); field.focus({preventScroll: true}); return false;
    }
    return true;
  }
  function createEditForm(comment) {
    var form = document.createElement("form"); form.className = "review-edit-form";
    var field = document.createElement("textarea"); field.className = "review-edit-input"; field.rows = 4; field.maxLength = 10000;
    field.value = comment.text; field.setAttribute("aria-label", window.uiText("编辑批注"));
    var actions = document.createElement("div"); actions.className = "review-actions";
    var cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "review-edit-cancel"; cancel.textContent = window.uiText("取消"); cancel.onclick = finishEditing;
    var save = document.createElement("button"); save.type = "submit"; save.className = "review-edit-save"; save.textContent = window.uiText("保存修改");
    actions.append(cancel, save); form.append(field, actions);
    form.onsubmit = function (event) {
      event.preventDefault(); event.stopPropagation(); var text = field.value.trim();
      if (!validText(text, field)) return;
      var current = comments.find(function (c) { return c.id === comment.id; });
      if (!current) return;
      var modified = current.text !== text; current.text = text;
      finishEditing(); if (modified) changed();
    };
    form.onkeydown = function (event) { if (!event.isComposing && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finishEditing(); } };
    return form;
  }
  window.editReviewComment = function (id) {
    if (editingId && editingId !== id) { notice("请先保存或取消正在编辑的批注。"); return; }
    if (!comments.some(function (c) { return c.id === id; })) return;
    closeComposer(); editingId = activeId = id; notice(""); renderList(); paint(indexText(root()));
    var field = list.querySelector(".review-edit-input"); field.focus({preventScroll: true}); field.closest("form").scrollIntoView({block: "nearest"});
  };
  window.addReviewComment = function () {
    if (editingId) { notice("请先保存或取消正在编辑的批注。"); return; }
    refresh(); var anchor = selectionAnchor() || remembered;
    window.showReview(true);
    if (!anchor || anchor.detached || !locate(anchor, indexText(root()))) { notice("请先选中需要批注的正文文字。"); return; }
    pending = JSON.parse(JSON.stringify(anchor)); notice("");
    document.getElementById("mdv-review-quote").textContent = anchor.quote;
    composer.hidden = false; input.value = ""; panel.scrollTop = 0; input.focus({preventScroll: true});
  };
  window.deleteReviewComment = function (id) {
    var target = id || activeId;
    if (!target) {
      var anchor = selectionAnchor();
      var current = anchor && comments.find(function (c) { return !c.anchor.detached && c.anchor.start < anchor.end && c.anchor.end > anchor.start; });
      target = current && current.id;
    }
    var index = comments.findIndex(function (c) { return c.id === target; });
    if (index < 0) { window.showReview(true); notice("请先点击需要删除的批注。"); return; }
    comments.splice(index, 1); if (editingId === target) editingId = null;
    activeId = null; renderList(); paint(indexText(root())); notice(""); changed();
  };
  composer.addEventListener("submit", function (event) {
    event.preventDefault(); refresh(); var text = input.value.trim();
    if (!validText(text, input)) return;
    if (!pending || pending.detached) { notice("选中的原文已修改，请重新选择文字。"); return; }
    var comment = {id: crypto.randomUUID(), text: text, anchor: JSON.parse(JSON.stringify(pending))};
    comments.push(comment); activeId = comment.id; closeComposer(); renderList(); paint(indexText(root())); notice(""); changed();
  });
  document.getElementById("mdv-review-cancel").addEventListener("click", closeComposer);
  document.getElementById("mdv-review-close").addEventListener("click", function () { window.showReview(false); });
  document.getElementById("mdv-review-add").addEventListener("click", window.addReviewComment);
  [toolbar, document.getElementById("mdv-review-add")].forEach(function (button) {
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
  });
  document.addEventListener("selectionchange", function () {
    clearTimeout(selectionTimer); selectionTimer = setTimeout(function () {
      var range = selectedRange();
      if (range) { remembered = range.collapsed ? null : selectionAnchor(); }
      selectionChanged(selectedText());
    }, 40);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key.toLowerCase() === "m" && (event.ctrlKey || event.metaKey) && event.altKey) { event.preventDefault(); window.addReviewComment(); }
    if (!event.isComposing && event.key === "Escape" && !composer.hidden) { event.preventDefault(); closeComposer(); root().focus({preventScroll: true}); }
  }, true);
  new MutationObserver(window.refreshReview).observe(document.getElementById("vditor"), {childList: true, characterData: true, subtree: true});
  window.loadReviewDocument = function (md) {
    loading = true; comments = []; previous = null; previousMd = null; remembered = null; activeId = editingId = null; closeComposer(); notice("");
    var match = /\n\n<!-- markdownview-review:v1\n([\s\S]*?)\n-->\s*$/.exec(md);
    if (match) {
      try {
        var payload = JSON.parse(match[1]);
        if (payload.version !== 1 || !Array.isArray(payload.comments) || payload.comments.length > 2000) { throw new Error("Invalid review data"); }
        var ids = new Set();
        payload.comments.forEach(function (c) {
          var a = c.anchor;
          if (typeof c.id !== "string" || c.id.length > 128 || ids.has(c.id) || typeof c.text !== "string" || c.text.length > 10000 || !a ||
              typeof a.quote !== "string" || typeof a.before !== "string" || typeof a.after !== "string" ||
              !Number.isInteger(a.start) || !Number.isInteger(a.end) || a.start < 0 || a.end < a.start) { throw new Error("Invalid comment"); }
          ids.add(c.id);
        });
        comments = payload.comments; md = md.slice(0, match.index);
      } catch (error) { notice("批注数据无法读取，原始内容已保留。"); }
    }
    renderList(); loading = false; return md;
  };
  window.reviewDocumentLoaded = function () {
    previous = indexText(root()); previousMd = editor.getValue();
    comments.forEach(function (c) { if (!c.anchor.detached && !locate(c.anchor, previous)) { c.anchor.detached = true; } });
    renderList(); paint(previous);
    selectionChanged("");
  };
  window.serializeReviewDocument = function (md) {
    refresh();
    if (!comments.length) { return md; }
    var json = JSON.stringify({version: 1, comments: comments}).replace(/[<>&]/g, function (c) { return "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"); });
    return md.replace(/\n*$/, "") + "\n\n<!-- markdownview-review:v1\n" + json + "\n-->\n";
  };
  function fitPanel() {
    panel.style.top = document.querySelector("#vditor .vditor-toolbar").getBoundingClientRect().bottom + "px";
    panel.style.bottom = document.getElementById("editor-statusbar").getBoundingClientRect().height + "px";
  }
  new ResizeObserver(fitPanel).observe(document.querySelector("#vditor .vditor-toolbar"));
  fitPanel(); toolbar.setAttribute("aria-expanded", "false"); renderList();
};
