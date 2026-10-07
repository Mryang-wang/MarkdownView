/* Translation and comments share the right rail; bilingual reading never edits Vditor. */
window.installTranslation = function (editor, getBridge, markdownHTML, rewriteImage) {
  "use strict";
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; };
  const tr = text => window.uiText(text);
  const panel = el("aside", "translation-panel"); panel.id = "mdv-translation-panel"; panel.hidden = true;
  panel.setAttribute("aria-label", "翻译");
  const header = el("div", "translation-header"); header.appendChild(el("h2", "", "翻译"));
  function button(text, action, parent, cls) { const b = el("button", cls, text); b.type = "button"; b.onclick = action; parent.appendChild(b); return b; }
  button("×", () => show(false), header, "translation-close").setAttribute("aria-label", "收起翻译栏");
  panel.appendChild(header);
  const name = el("div", "translation-name"); panel.appendChild(name);
  const modelRow = el("div", "translation-row"), model = el("span", "translation-muted"); modelRow.appendChild(model);
  const configure = button("模型设置…", () => send("settings"), modelRow, "translation-link"); panel.appendChild(modelRow);
  const form = el("div", "translation-form"); panel.appendChild(form);
  const languages = [
    ["简体中文", "简体中文"], ["繁體中文", "繁体中文"], ["English", "英语 English"],
    ["日本語", "日语"], ["한국어", "韩语"], ["Français", "法语"], ["Deutsch", "德语"],
    ["Español", "西班牙语"], ["Português", "葡萄牙语"], ["Italiano", "意大利语"],
    ["Русский", "俄语"], ["Українська", "乌克兰语"], ["Polski", "波兰语"], ["Čeština", "捷克语"],
    ["Nederlands", "荷兰语"], ["Svenska", "瑞典语"], ["Dansk", "丹麦语"], ["Norsk", "挪威语"],
    ["Suomi", "芬兰语"], ["Ελληνικά", "希腊语"], ["Türkçe", "土耳其语"], ["العربية", "阿拉伯语"],
    ["עברית", "希伯来语"], ["हिन्दी", "印地语"], ["ไทย", "泰语"], ["Tiếng Việt", "越南语"],
    ["Bahasa Indonesia", "印尼语"], ["Bahasa Melayu", "马来语"], ["Română", "罗马尼亚语"], ["Magyar", "匈牙利语"]
  ];
  const languageFields = [], customLanguage = "__custom__";
  function languageField(role, caption, value, parent) {
    const field = el("label", "translation-field", caption), select = el("select"), input = el("input");
    select.dataset.translationLanguage = role; select.setAttribute("aria-label", caption);
    const options = role === "source" ? [["auto detect", "自动检测"], ...languages] : languages;
    [...options, [customLanguage, "其他语言…"]].forEach(([value, caption]) => {
      const option = el("option", "", tr(caption)); option.value = value; select.appendChild(option);
    });
    input.maxLength = 100; input.hidden = true; input.placeholder = tr("输入语言名称");
    input.setAttribute("aria-label", role === "source" ? "自定义原文语言" : "自定义目标语言");
    field.append(select, input); parent.appendChild(field);
    const control = {role, select, input,
      value: () => select.value === customLanguage ? input.value.trim() : select.value,
      set(value) {
        const known = options.some(([key]) => key === value);
        select.value = known ? value : customLanguage; input.value = known ? "" : value;
        input.hidden = known;
      }
    };
    function changed() {
      input.hidden = select.value !== customLanguage;
      languageFields.filter(other => other !== control && other.role === role).forEach(other => {
        other.select.value = select.value; other.input.value = input.value; other.input.hidden = input.hidden;
      });
      // Changing either language cancels the old task, but never starts a paid
      // request until the user presses Translate. Both surfaces share values.
      resetUI();
      send("reset");
    }
    select.addEventListener("change", () => { changed(); if (!input.hidden) input.focus(); });
    input.addEventListener("change", changed);
    languageFields.push(control); control.set(value); return control;
  }
  const source = languageField("source", "从", "auto detect", form), target = languageField("target", "译为", "简体中文", form);
  const promptRow = el("div", "translation-row"), prompt = el("select"); prompt.setAttribute("aria-label", "翻译提示词");
  promptRow.appendChild(prompt); const editPrompt = button("编辑 / 新增…", () => send("prompt"), promptRow, "translation-link"); panel.appendChild(promptRow);
  const advanced = el("details", "translation-advanced"); advanced.appendChild(el("summary", "", "专业术语"));
  const glossary = el("textarea"); glossary.rows = 3; glossary.maxLength = 4000; glossary.placeholder = "每行：原词 = 译词"; glossary.setAttribute("aria-label", "术语表"); advanced.appendChild(glossary); panel.appendChild(advanced);
  const full = button("全文翻译模式", () => send("full"), panel, "translation-full");
  const quoteLabel = el("div", "translation-caption", "选中原文"), quote = el("blockquote", "translation-source");
  panel.append(quoteLabel, quote);
  const resultLabel = el("div", "translation-caption", "译文"), result = el("div", "translation-result vditor-reset");
  const streaming = el("pre", "translation-stream"); result.appendChild(streaming); panel.append(resultLabel, result);
  const committedText = document.createTextNode(""), partialText = document.createTextNode(""); streaming.append(committedText, partialText);
  const progress = el("progress"); progress.max = 1; progress.value = 0; panel.appendChild(progress);
  const status = el("p", "translation-status", "连接模型后即可翻译。原文会保持不变。"); status.setAttribute("role", "status"); panel.appendChild(status);
  const actions = el("div", "translation-actions"); panel.appendChild(actions);
  const start = button("开始翻译", () => send("start"), actions, "primary");
  const cancel = button("取消", () => send("cancel"), actions); cancel.disabled = true;
  const reset = button("新任务", () => send("reset"), actions); reset.hidden = true;
  const outputs = el("div", "translation-outputs"); panel.appendChild(outputs);
  const copy = button("复制", () => { send("copy"); status.textContent = tr("译文已复制。"); }, outputs);
  const save = button("另存译文…", () => send("save"), outputs);
  const open = button("打开为新文档", () => send("open"), outputs);
  [copy, save, open].forEach(b => b.disabled = true);
  document.body.appendChild(panel);

  const reader = el("section", "translation-reader"); reader.id = "mdv-translation-reader"; reader.hidden = true;
  reader.setAttribute("aria-label", "全文翻译模式");
  const readerBar = el("div", "translation-reader-bar");
  readerBar.appendChild(el("strong", "", "全文翻译模式"));
  languageField("source", "从", "auto detect", readerBar);
  languageField("target", "译为", "简体中文", readerBar);
  const readerState = el("span", "translation-muted", "原文与译文逐段对照"); readerBar.appendChild(readerState);
  const view = el("select", "translation-view"); view.setAttribute("aria-label", "阅读显示");
  [["edit", "左右对照编辑"], ["bilingual", "双语对照"], ["translated", "只看译文"], ["original", "只看原文"]].forEach(([value, text]) => { const o = el("option", "", text); o.value = value; view.appendChild(o); });
  view.onchange = () => { reader.dataset.view = view.value; showReader(!reader.hidden); }; readerBar.appendChild(view);
  const readerToggle = button("开始翻译", () => {
    if (!getBridge()) return;
    readerToggle.disabled = true;
    send(running ? "cancel" : "start");
  }, readerBar, "primary");
  readerToggle.dataset.translationAction = "toggle";
  const update = button("更新改动", () => send("update"), readerBar); update.title = "只翻译修改或新增的句子，复用其余译文";
  button("翻译设置", () => show(panel.hidden), readerBar);
  button("返回编辑", () => send("exit"), readerBar);
  const article = el("article", "translation-article vditor-reset"); reader.append(readerBar, article); document.body.appendChild(reader);
  const live = el("div", "translation-live"), liveText = el("pre", "translation-stream");
  live.append(el("div", "translation-live-label", "正在生成译文…"), liveText);
  let liveTarget = null, livePlaceholder = null, liveUnchanged = false;
  let generation = 0, mode = "selection", sourceText = "", sourceBase = "", resultText = "", layoutText = null, liveSource = null, originalNodes = [], cards = [], running = false;
  let sourceStale = false, scrollFrame = 0, scrollPasses = 0, scrollDriver = "left";
  let readingPosition = null, readingFrame = 0;
  const synchronizedPositions = new WeakMap();
  function sourcePane() {
    const root = editor.vditor[editor.getCurrentMode()].element;
    return {root, scroller: root.scrollHeight > root.clientHeight ? root : root.parentElement};
  }
  function scrollEnabled() { return !reader.hidden && view.value === "edit"; }
  function setScroll(scroller, position) {
    scroller.scrollTop = Math.max(0, Math.min(scroller.scrollHeight - scroller.clientHeight, position));
    synchronizedPositions.set(scroller, scroller.scrollTop);
  }
  function syncScroll(side) {
    if (!scrollEnabled()) return;
    const pane = sourcePane(), left = pane.scroller;
    if (!left.clientHeight || !article.clientHeight) return;
    const from = side === "left" ? left : article, to = side === "left" ? article : left;
    const fromMax = from.scrollHeight - from.clientHeight, toMax = to.scrollHeight - to.clientHeight;
    if (fromMax <= 0 || toMax <= 0) return;
    let position = from.scrollTop / fromMax * toMax;
    // Matching top-level blocks provide a better anchor than document percentage
    // when translated paragraphs wrap to very different heights. Source mode,
    // pending edits and fallback layouts use percentage until alignment is known.
    const blocks = Array.from(pane.root.children);
    if (!sourceStale && editor.getCurrentMode() !== "sv" && cards.length && blocks.length === cards.length &&
        from.scrollTop > 1 && from.scrollTop < fromMax - 1) {
      const a = side === "left" ? blocks : cards.map(c => c.pair);
      const b = side === "left" ? cards.map(c => c.pair) : blocks;
      const fromRect = from.getBoundingClientRect(), toRect = to.getBoundingClientRect();
      const fromScale = fromRect.height / from.offsetHeight || 1, toScale = toRect.height / to.offsetHeight || 1;
      const top = (node, container, rect, scale) => container.scrollTop + (node.getBoundingClientRect().top - rect.top) / scale;
      // Binary search reads only a few block rectangles, even for long documents.
      let low = 0, high = a.length;
      while (low < high) {
        const mid = (low + high) >> 1;
        if (top(a[mid], from, fromRect, fromScale) <= from.scrollTop) low = mid + 1; else high = mid;
      }
      const index = low - 1;
      const a0 = index < 0 ? 0 : top(a[index], from, fromRect, fromScale);
      const b0 = index < 0 ? 0 : top(b[index], to, toRect, toScale);
      const a1 = low < a.length ? top(a[low], from, fromRect, fromScale) : from.scrollHeight;
      const b1 = low < b.length ? top(b[low], to, toRect, toScale) : to.scrollHeight;
      position = b0 + (from.scrollTop - a0) / Math.max(1, a1 - a0) * (b1 - b0);
    }
    if (Math.abs(to.scrollTop - position) > 1) setScroll(to, position);
  }
  function queueScroll(side) {
    if (!scrollEnabled() || readingPosition) return;
    scrollDriver = side; scrollPasses = 2;
    // content-visibility lays out newly visible paragraphs after a scroll. One
    // follow-up frame accounts for their actual heights without rendering all rows.
    function frame() {
      scrollFrame = 0; syncScroll(scrollDriver);
      if (--scrollPasses > 0 && scrollEnabled()) scrollFrame = requestAnimationFrame(frame);
    }
    if (!scrollFrame) scrollFrame = requestAnimationFrame(frame);
  }
  function scrolled(side, event) {
    if (!scrollEnabled() || readingPosition) return;
    if (scrollFrame && side !== scrollDriver) return;
    const scroller = side === "left" ? sourcePane().scroller : article;
    if (event.target !== scroller) return; // Ignore nested code/image scrolling.
    const expected = synchronizedPositions.get(scroller);
    if (expected !== undefined && Math.abs(scroller.scrollTop - expected) < 2) return;
    synchronizedPositions.delete(scroller);
    queueScroll(side);
  }
  function releaseReadingPosition() {
    cancelAnimationFrame(readingFrame); readingFrame = 0; readingPosition = null;
  }
  function preserveReadingPosition() {
    if (reader.hidden) return;
    if (!readingPosition) {
      const pane = sourcePane();
      readingPosition = {left: pane.scroller, top: pane.scroller.scrollTop, right: article.scrollTop};
    }
    cancelAnimationFrame(scrollFrame); scrollFrame = 0;
    cancelAnimationFrame(readingFrame); readingFrame = 0;
  }
  function restoreReadingPosition() {
    if (!readingPosition) return;
    function restore() {
      const saved = readingPosition;
      if (!saved) return;
      setScroll(saved.left, saved.top);
      // The unchanged source is the stable reading anchor, even when the
      // translation temporarily falls back to a single whole-document block.
      if (scrollEnabled() && saved.left.scrollHeight > saved.left.clientHeight) syncScroll("left");
      else setScroll(article, saved.right);
    }
    restore();
    // Recheck after content-visibility has laid out the new viewport. Scroll
    // events caused by this replacement must never drive the source to the top.
    readingFrame = requestAnimationFrame(() => {
      restore();
      readingFrame = requestAnimationFrame(() => { restore(); releaseReadingPosition(); });
    });
  }
  const editorHost = document.getElementById("vditor");
  editorHost.addEventListener("scroll", event => scrolled("left", event), {capture: true, passive: true});
  article.addEventListener("scroll", event => scrolled("right", event), {passive: true});
  [editorHost, article].forEach(host => {
    ["wheel", "pointerdown", "keydown"].forEach(type => host.addEventListener(type, () => {
      const settling = readingPosition || scrollFrame;
      releaseReadingPosition(); // An actual user gesture always takes priority.
      synchronizedPositions.delete(host === article ? article : sourcePane().scroller);
      if (settling) queueScroll(host === article ? "right" : "left");
    }, {passive: true}));
  });
  function values() { return {source: source.value() || "auto detect", target: target.value(), prompt: prompt.value, glossary: glossary.value}; }
  function send(action) { const bridge = getBridge(); if (bridge) bridge.translationAction(action, JSON.stringify(values())); }
  function show(visible) {
    if (visible && window.showReview) window.showReview(false);
    panel.hidden = !visible;
    document.documentElement.dataset.translationVisible = String(visible);
    fit();
  }
  function showReader(visible) {
    releaseReadingPosition();
    reader.hidden = !visible;
    const editing = visible && view.value === "edit";
    document.documentElement.classList.toggle("mdv-translating-document", visible);
    document.documentElement.classList.toggle("mdv-translation-editing", editing);
    document.getElementById("vditor").inert = visible && !editing;
    window.mdvTranslationReading = visible && !editing;
    if ((visible && !editing) || window.mdvReadOnly) editor.disabled(); else editor.enable();
    if (visible && window.showReview) window.showReview(false);
    if (!visible) editor.focus();
    fit();
    if (editing) queueScroll("left");
  }
  function fit() {
    const top = document.querySelector("#vditor .vditor-toolbar").getBoundingClientRect().bottom;
    const bottom = document.getElementById("editor-statusbar").getBoundingClientRect().height;
    panel.style.top = (reader.hidden ? top : 0) + "px";
    panel.style.bottom = bottom + "px";
    reader.style.bottom = bottom + "px";
  }
  new ResizeObserver(fit).observe(document.querySelector("#vditor .vditor-toolbar"));
  // Raw HTML is displayed as static reading content. No event handlers, forms or active URLs.
  function parsed(markdown) {
    const root = el("div"); root.innerHTML = markdownHTML(markdown);
    root.querySelectorAll("script,style,iframe,object,embed,base,meta,link,form,button,textarea,select,foreignObject").forEach(n => n.remove());
    root.querySelectorAll("input").forEach(n => { if (n.type === "checkbox") n.disabled = true; else n.remove(); });
    root.querySelectorAll("*").forEach(node => {
      Array.from(node.attributes).forEach(a => {
        if (/^on/i.test(a.name) || ["srcdoc", "contenteditable", "autofocus", "style", "id"].includes(a.name)) node.removeAttribute(a.name);
        if (["href", "src", "xlink:href"].includes(a.name) && /^(?:javascript|vbscript|data):/i.test(a.value.trim())) node.removeAttribute(a.name);
      });
    });
    Array.from(root.childNodes).forEach(node => {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) { const p = el("p", "", node.textContent); node.replaceWith(p); }
    });
    return root;
  }
  function finishRender(root) {
    root.querySelectorAll("img").forEach(img => {
      const path = img.getAttribute("src");
      if (sourceBase && path && !/^[a-z][a-z\d+.-]*:|^\/\//i.test(path)) img.src = new URL(path, sourceBase).href;
      else rewriteImage(img);
    });
    Vditor.mathRender(root, {cdn: "./vditor", math: {engine: "KaTeX"}});
  }
  function initializeReader(resetPosition = true) {
    clearLive(); liveTarget = null;
    originalNodes = Array.from(parsed(sourceText).children);
    cards = []; article.replaceChildren();
    const fragment = document.createDocumentFragment();
    originalNodes.forEach(node => {
      const pair = el("section", "translation-pair"), original = el("div", "translation-original"), translated = el("div", "translation-rendered");
      original.appendChild(node.cloneNode(true));
      translated.appendChild(el("span", "translation-pending", "等待翻译…"));
      pair.append(original, translated); fragment.appendChild(pair); cards.push({pair, original, translated, html: null});
    });
    article.appendChild(fragment); finishRender(article);
    if (resetPosition) { setScroll(article, 0); queueScroll("left"); }
  }
  function renderPairs(final) {
    clearLive(); liveTarget = null;
    const display = layoutText === null ? resultText : layoutText;
    const nodes = Array.from(parsed(display).children);
    // Structure is protected by the backend. If a model still changes block shape, avoid false alignment.
    const compatible = nodes.length <= originalNodes.length && nodes.every((node, i) => node.tagName === originalNodes[i].tagName);
    if (!compatible || (final && nodes.length !== originalNodes.length)) {
      article.replaceChildren(); cards = [];
      const pair = el("section", "translation-pair"), a = el("div", "translation-original"), b = el("div", "translation-rendered");
      a.append(...Array.from(parsed(sourceText).childNodes)); b.append(...Array.from(parsed(display).childNodes)); pair.append(a, b); article.appendChild(pair); finishRender(pair);
      if (!final) liveTarget = b;
      return;
    }
    if (cards.length !== originalNodes.length) initializeReader(false);
    const count = nodes.length;
    for (let i = 0; i < count; i++) {
      const card = cards[i], html = nodes[i].outerHTML;
      if (card.html === html) continue;
      card.html = html;
      const unchanged = html === originalNodes[i].outerHTML;
      card.pair.classList.toggle("translation-unchanged", unchanged);
      if (unchanged) card.translated.replaceChildren();
      else { card.translated.replaceChildren(nodes[i]); finishRender(card.translated); }
    }
    if (!final) {
      // A chunk may end inside a paragraph/list. Continue beside that block until
      // validation supplies its final layout; a blank line starts the next block.
      const prefix = liveSource === null ? resultText : liveSource;
      const previous = liveSource === null ? nodes.length : parsed(prefix).children.length;
      const nextBlock = !previous || /\n[ \t]*\n[ \t]*$/.test(prefix);
      const index = Math.min(cards.length - 1, Math.max(0, previous - (nextBlock ? 0 : 1)));
      if (cards[index]) liveTarget = cards[index].translated;
    }
  }
  function clearLive() {
    if (live.parentElement) live.closest(".translation-pair").classList.toggle("translation-unchanged", liveUnchanged);
    if (livePlaceholder) livePlaceholder.hidden = false;
    livePlaceholder = null; live.remove(); liveText.textContent = "";
  }
  function updateLive(text) {
    if (!text || !liveTarget) { clearLive(); return; }
    if (live.parentElement !== liveTarget) {
      clearLive(); livePlaceholder = liveTarget.querySelector(".translation-pending");
      if (livePlaceholder) livePlaceholder.hidden = true;
      liveUnchanged = liveTarget.closest(".translation-pair").classList.contains("translation-unchanged");
      liveTarget.closest(".translation-pair").classList.remove("translation-unchanged");
      liveTarget.appendChild(live);
    }
    // Plain text is safe even for incomplete Markdown/HTML; math runs only on commit.
    if (liveText.textContent !== text) liveText.textContent = text;
  }
  function settings(data) {
    languageFields.forEach(field => field.set(data.options[field.role] || (field.role === "source" ? "auto detect" : "简体中文")));
    glossary.value = data.options.glossary;
    prompt.replaceChildren(); data.prompts.forEach(p => { const o = el("option", "", p.label); o.value = p.name; prompt.appendChild(o); });
    prompt.value = data.options.prompt; if (!prompt.value && prompt.options.length) prompt.selectedIndex = 0;
    model.textContent = data.model || tr("尚未连接模型");
  }
  function resetUI() {
    releaseReadingPosition();
    const hadResult = !!resultText;
    resultText = ""; layoutText = liveSource = null; committedText.nodeValue = partialText.nodeValue = ""; result.replaceChildren(streaming); result.hidden = mode === "full";
    clearLive(); liveTarget = null;
    progress.value = 0; status.textContent = tr("连接模型后即可翻译。原文会保持不变。");
    [prompt, editPrompt, glossary, configure, full, start].forEach(b => b.disabled = false);
    [copy, save, open, cancel].forEach(b => b.disabled = true); reset.hidden = true; start.textContent = tr("开始翻译");
    running = false; sourceStale = false;
    readerToggle.disabled = false; readerToggle.textContent = tr("开始翻译"); readerToggle.title = tr("开始翻译");
    if (mode === "full" && (hadResult || !cards.length)) initializeReader();
    update.disabled = false; readerState.textContent = tr("等待翻译…");
  }
  window.translationUI = {
    settings,
    open(data) {
      generation = data.generation; mode = data.mode; sourceText = data.source; sourceBase = data.base || ""; name.textContent = data.name; settings(data);
      cards = [];
      quote.textContent = sourceText; quote.hidden = quoteLabel.hidden = mode === "full";
      full.hidden = mode === "full"; resultLabel.hidden = mode === "full";
      view.value = "edit"; reader.dataset.view = "edit";
      resetUI(); showReader(mode === "full"); show(mode !== "full" || !data.configured);
    },
    show(data) { showReader(data.mode === "full"); show(true); },
    hide() { show(false); },
    leave() { send("exit"); showReader(false); show(false); },
    exit() { showReader(false); show(false); },
    reset: resetUI,
    error(text) { status.textContent = text; readerToggle.disabled = false; show(true); },
    update(data) {
      if (data.generation !== generation) return;
      if (mode === "full") preserveReadingPosition();
      running = data.state === "running";
      sourceStale = !!data.stale;
      if (Object.prototype.hasOwnProperty.call(data, "result")) resultText = data.result;
      if (Object.prototype.hasOwnProperty.call(data, "layout")) layoutText = data.layout;
      if (Object.prototype.hasOwnProperty.call(data, "live_source")) liveSource = data.live_source;
      if (mode === "selection") {
        const follow = result.scrollHeight - result.scrollTop - result.clientHeight < 32;
        if (running) {
          if (!streaming.isConnected) result.replaceChildren(streaming);
          if (committedText.nodeValue !== resultText) committedText.nodeValue = resultText;
          partialText.nodeValue = data.preview;
        }
        else { result.replaceChildren(...Array.from(parsed(resultText).childNodes)); finishRender(result); }
        if (follow) result.scrollTop = result.scrollHeight;
      } else {
        if (Object.prototype.hasOwnProperty.call(data, "result") || !running) renderPairs(data.state === "complete");
        updateLive(running ? data.preview : "");
      }
      progress.max = data.total || 1; progress.value = data.done; status.textContent = data.status;
      readerState.textContent = data.stale ? tr("原文已修改，等待更新") : running ? tr("正在翻译…") + " " + data.done + "/" + data.total : data.state === "complete" ? tr("原文与译文逐段对照") : tr("翻译已暂停");
      if (data.reused && !data.stale) readerState.textContent += " · " + tr("已复用 {0} 个未改句段。").replace("{0}", data.reused);
      update.disabled = running;
      [prompt, editPrompt, glossary].forEach(b => b.disabled = running || data.retry);
      configure.disabled = full.disabled = start.disabled = running;
      cancel.disabled = !running; reset.hidden = running;
      start.textContent = tr(data.retry ? "继续翻译" : data.state === "complete" ? "重新翻译" : "开始翻译");
      readerToggle.disabled = false;
      readerToggle.textContent = tr(running ? "停止翻译" : data.stale ? "开始翻译" : data.retry ? "继续翻译" : data.state === "complete" ? "重新翻译" : "开始翻译");
      readerToggle.title = tr(running ? "停止当前请求，保留已完成的译文" : data.stale ? "只翻译修改或新增的句子，复用其余译文" : data.retry ? "继续翻译未完成的内容" : data.state === "complete" ? "重新翻译全文" : "开始翻译");
      [copy, save, open].forEach(b => b.disabled = running || !data.done || data.stale);
      open.textContent = tr(data.state === "complete" ? "打开为新文档" : "打开已完成部分");
      save.textContent = tr(data.state === "complete" ? "另存译文…" : "保存已完成部分…");
      if (mode === "full") restoreReadingPosition();
    },
    active() { return !reader.hidden || !panel.hidden || running; }
  };
  [reader, result].forEach(root => root.addEventListener("click", event => {
    const link = event.target.closest("a"); if (!link) return;
    event.preventDefault(); const bridge = getBridge(); if (bridge && link.getAttribute("href")) bridge.openUrl(link.getAttribute("href"));
  }));
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!panel.hidden) { show(false); event.preventDefault(); event.stopImmediatePropagation(); }
    else if (!reader.hidden) { send("exit"); event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
};
