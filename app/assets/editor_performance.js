/* Keep ordinary paragraph typing in the browser's native text node. Markdown
   syntax, boundaries, replacement, paste and IME retain Vditor's normal parser. */
window.installEditorPerformance = function (editor) {
  "use strict";
  const ir = editor.vditor.ir, root = ir.element;
  const lute = editor.vditor.lute;
  ["VditorIRDOM2Md", "VditorDOM2Md"].forEach(name => {
    const convert = lute[name];
    lute[name] = function (html) {
      // KaTeX/highlight previews are disposable render output. Keep their source
      // markers, and compact a detached copy before Lute parses a large snapshot.
      // The live editor, selection and undo snapshot are never rewritten here.
      if (html.length >= 262144 && /vditor-(?:ir|wysiwyg)__preview/.test(html)) {
        const template = document.createElement("template"); template.innerHTML = html;
        template.content.querySelectorAll(".vditor-ir__preview,.vditor-wysiwyg__preview").forEach(node => node.replaceChildren());
        html = template.innerHTML;
      }
      return convert.call(lute, html);
    };
  });
  const letters = /^[\p{L}\p{N}]+$/u;
  const plain = /^[\p{L}\p{N} \t\u00a0:：,，;；]+$/u;
  let insertion = null;
  root.addEventListener("beforeinput", event => {
    insertion = null;
    if (editor.getCurrentMode() !== "ir" || event.isComposing || ir.composingLock ||
        ir.preventInput || event.inputType !== "insertText" || !(letters.test(event.data || "") || event.data === " ")) return;
    const selection = getSelection();
    if (!selection.rangeCount) return;
    const range = selection.getRangeAt(0), node = range.startContainer, offset = range.startOffset;
    if (node.nodeType !== Node.TEXT_NODE) return;
    const endsAtSameBoundary = offset === node.length && (
      (range.endContainer === node.nextSibling && node.nextSibling?.nodeType === Node.TEXT_NODE && range.endOffset === 0) ||
      (range.endContainer === node.parentNode && node.parentNode.childNodes[range.endOffset - 1] === node));
    if (!range.collapsed && !endsAtSameBoundary) return;
    // Vditor's caret marker can leave two adjacent text nodes inside one word.
    let next = node.nextSibling, gaps = 0;
    while (next?.nodeType === Node.TEXT_NODE && !next.data) {
      // Let the regular parser coalesce caret-marker fragments periodically.
      if (++gaps >= 8) return;
      next = next.nextSibling;
    }
    const following = offset === node.length && next?.nodeType === Node.TEXT_NODE ? next.data : "";
    // Restrict the fast path to plain text after a letter/number in a top-level
    // paragraph. A second trailing space, punctuation and block starts still
    // activate Markdown (hard breaks, autolinks, lists, etc.) normally.
    const atEnd = offset === node.length && !next;
    if (node.parentElement?.tagName !== "P" ||
        node.parentElement.parentElement !== root || !plain.test(node.data + following) ||
        !letters.test(node.data.slice(Math.max(0, offset - 1), offset)) ||
        (!atEnd && !letters.test((node.data.slice(offset) || following).slice(0, 1)))) return;
    insertion = {node, data: event.data};
  }, true);
  root.addEventListener("input", event => {
    const pending = insertion; insertion = null;
    if (!pending || event.isComposing || event.inputType !== "insertText" || pending.data !== event.data ||
        !pending.node.isConnected || getSelection().anchorNode !== pending.node) return;
    // This is Vditor's existing "DOM already updated" path. Its normal input,
    // hints and undo scheduler still run; no parallel undo stack or parser.
    ir.preventInput = true;
  }, true);
};
