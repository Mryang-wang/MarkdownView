/* Table dimensions and contextual editing; reuse Vditor's document and undo stack. */
window.installTableFeatures = function (editor, changed) {
  "use strict";
  var button = document.querySelector('#vditor .vditor-toolbar [data-type="table"]');
  var panel = document.getElementById("mdv-table-panel");
  var rowsInput = document.getElementById("mdv-table-rows");
  var colsInput = document.getElementById("mdv-table-cols");
  var savedRange = null, savedMode = null, contextCell = null, selectedTable = null;

  function root() { return editor.vditor[editor.getCurrentMode()].element; }
  function editable() {
    return !window.mdvReadOnly && !window.mdvTranslationReading && root().isContentEditable;
  }
  function select(range) {
    root().focus({preventScroll: true});
    var selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
  }
  function caret(element) {
    var range = document.createRange(); range.selectNodeContents(element); range.collapse(true); select(range);
  }
  function close(restore) {
    panel.hidden = true; button.setAttribute("aria-expanded", "false");
    if (restore && savedMode === editor.getCurrentMode() && savedRange && root().contains(savedRange.startContainer)) {
      select(savedRange);
    }
    savedRange = null;
  }
  function position() {
    var rect = button.getBoundingClientRect();
    panel.style.left = Math.max(8, Math.min(rect.left, innerWidth - panel.offsetWidth - 8)) + "px";
    panel.style.top = Math.max(8, Math.min(rect.bottom + 8, innerHeight - panel.offsetHeight - 8)) + "px";
  }
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-controls", panel.id);
  button.setAttribute("aria-expanded", "false");
  // Override the bundled fixed 3 x 3 table action without modifying vendor code.
  button.addEventListener("click", function (event) {
    event.preventDefault(); event.stopImmediatePropagation();
    if (!panel.hidden) { close(true); return; }
    if (!editable() || button.classList.contains("vditor-menu--disabled")) { return; }
    var selection = getSelection();
    savedRange = selection.rangeCount && root().contains(selection.getRangeAt(0).commonAncestorContainer)
      ? selection.getRangeAt(0).cloneRange() : null;
    savedMode = editor.getCurrentMode();
    panel.hidden = false; button.setAttribute("aria-expanded", "true");
    document.getElementById("mdv-toolbar-tooltip").style.display = "none";
    position(); rowsInput.focus(); rowsInput.select();
  }, true);
  panel.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!editable() || savedMode !== editor.getCurrentMode()) { close(false); return; }
    if (!panel.reportValidity()) { return; }
    var rows = rowsInput.valueAsNumber, cols = colsInput.valueAsNumber;
    if (!Number.isInteger(rows) || rows < 1 || rows > 100 || !Number.isInteger(cols) || cols < 1 || cols > 50) { return; }
    close(true);
    editor.focus(); editor.vditor.undo.addToUndoStack(editor.vditor);
    var line = "|" + Array(cols).fill("   |").join("");
    var divider = "|" + Array(cols).fill(" --- |").join("");
    editor.insertMD("\n\n" + [line, divider].concat(Array(rows - 1).fill(line)).join("\n") + "\n\n");
    editor.vditor.undo.addToUndoStack(editor.vditor); changed();
  });
  document.getElementById("mdv-table-cancel").onclick = function () { close(true); };
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Tab") {
      var controls = Array.from(panel.querySelectorAll("input,button"));
      var next = (controls.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
      event.preventDefault(); controls[next].focus();
    }
  });
  window.addEventListener("resize", function () { if (!panel.hidden) { position(); } });
  document.addEventListener("pointerdown", function (event) {
    if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) { close(false); }
  }, true);

  function clearTableSelection() {
    if (selectedTable) { selectedTable.classList.remove("mdv-table-selected"); }
    selectedTable = null;
  }
  function isTableSelected() {
    var selection = getSelection();
    if (!selectedTable || !selectedTable.isConnected || !selection.rangeCount) { return false; }
    var range = selection.getRangeAt(0), expected = document.createRange(); expected.selectNode(selectedTable);
    return range.compareBoundaryPoints(Range.START_TO_START, expected) === 0 &&
      range.compareBoundaryPoints(Range.END_TO_END, expected) === 0;
  }
  document.addEventListener("selectionchange", function () {
    if (selectedTable && !isTableSelected()) { clearTableSelection(); }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      event.preventDefault(); event.stopImmediatePropagation(); close(true);
    } else if ((event.key === "Delete" || event.key === "Backspace") && root().contains(event.target) && editable() && isTableSelected()) {
      event.preventDefault(); event.stopImmediatePropagation();
      contextCell = selectedTable.rows[0].cells[0]; window.tableAction("deleteTable");
    } else if (event.key === "Escape" && root().contains(event.target) && isTableSelected()) {
      caret(selectedTable.rows[0].cells[0]); clearTableSelection();
    }
  }, true);

  window.tableContext = function (x, y) {
    contextCell = null;
    var target = document.elementFromPoint(x, y);
    var cell = target && target.closest("th,td");
    if (!cell || !root().contains(cell) || cell.closest('.vditor-ir__preview,.vditor-wysiwyg__preview')) { return null; }
    contextCell = cell;
    return {editable: editable(), row: cell.parentElement.rowIndex, column: cell.cellIndex};
  };

  function newCell(tag, align) {
    var cell = document.createElement(tag); cell.textContent = " ";
    if (align) { cell.setAttribute("align", align); }
    return cell;
  }
  function normalizeHeader(table) {
    // Markdown has one header row. Inserting above / deleting it promotes the new first row.
    var rows = Array.from(table.rows), head = document.createElement("thead"), body = document.createElement("tbody");
    rows.forEach(function (row, i) {
      Array.from(row.cells).forEach(function (cell) {
        var tag = i === 0 ? "TH" : "TD";
        if (cell.tagName !== tag) {
          var replacement = newCell(tag, cell.getAttribute("align"));
          replacement.innerHTML = cell.innerHTML; cell.replaceWith(replacement);
        }
      });
      (i === 0 ? head : body).appendChild(row);
    });
    table.replaceChildren(head); if (body.children.length) { table.appendChild(body); }
  }
  window.tableAction = function (action) {
    var cell = contextCell;
    if (!cell || !root().contains(cell) || !editable()) { return false; }
    var table = cell.closest("table"), r = cell.parentElement.rowIndex, c = cell.cellIndex;
    if (action === "selectTable") {
      clearTableSelection();
      var range = document.createRange(); range.selectNode(table); select(range);
      selectedTable = table; table.classList.add("mdv-table-selected"); return true;
    }
    if (!["rowAbove", "rowBelow", "columnLeft", "columnRight", "deleteRow", "deleteColumn", "deleteTable"].includes(action)) { return false; }
    clearTableSelection(); caret(cell);
    editor.vditor.undo.addToUndoStack(editor.vditor);
    if ((action === "deleteRow" && table.rows.length === 1) ||
        (action === "deleteColumn" && table.rows[0].cells.length === 1)) { action = "deleteTable"; }
    if (action === "deleteTable") {
      // Leave an editable paragraph at the former table position, also for a table-only document.
      var paragraph = document.createElement("p"); paragraph.dataset.block = "0";
      paragraph.appendChild(document.createElement("br")); table.replaceWith(paragraph); caret(paragraph);
      contextCell = null;
    } else {
      var alignments = Array.from(table.rows[0].cells).map(function (item) { return item.getAttribute("align"); });
      if (action === "rowAbove" || action === "rowBelow") {
        if (action === "rowBelow") { r++; }
        var row = table.insertRow(r);
        alignments.forEach(function (align) { row.appendChild(newCell("td", align)); });
      } else if (action === "columnLeft" || action === "columnRight") {
        if (action === "columnRight") { c++; }
        Array.from(table.rows).forEach(function (row, i) { row.insertBefore(newCell(i === 0 ? "th" : "td"), row.cells[c] || null); });
      } else if (action === "deleteRow") { table.deleteRow(r); }
      else { Array.from(table.rows).forEach(function (row) { row.deleteCell(c); }); }
      normalizeHeader(table);
      contextCell = table.rows[Math.min(r, table.rows.length - 1)].cells[Math.min(c, table.rows[0].cells.length - 1)];
      caret(contextCell);
    }
    // Run the editor's render/input/outline pipeline after the local DOM edit.
    // Empty Markdown changes no content; it avoids resetting the entire document.
    editor.insertMD(""); editor.vditor.undo.addToUndoStack(editor.vditor); changed();
    return true;
  };
};
