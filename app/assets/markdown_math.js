/* Convert math delimiters without rewriting literal Markdown code. */
(function () {
  "use strict";
  function outsideInlineCode(text, convert) {
    var ticks = /`+/g, match, start = 0, result = "";
    while ((match = ticks.exec(text))) {
      var end, closing = new RegExp("`+", "g");
      closing.lastIndex = ticks.lastIndex;
      while ((end = closing.exec(text)) && end[0].length !== match[0].length) {}
      if (!end) { continue; }
      result += convert(text.slice(start, match.index)) + text.slice(match.index, closing.lastIndex);
      start = ticks.lastIndex = closing.lastIndex;
    }
    return result + convert(text.slice(start));
  }
  function outsideCode(markdown, convert) {
    var lines = markdown.match(/[^\n]*\n|[^\n]+$/g) || [], result = "", prose = "", fence = null, indented = false;
    function flush() { result += outsideInlineCode(prose, convert); prose = ""; }
    lines.forEach(function (line, i) {
      if (fence) {
        result += line;
        var close = /^ {0,3}(`+|~+)[ \t]*\r?\n?$/.exec(line);
        if (close && close[1][0] === fence[0] && close[1].length >= fence.length) { fence = null; }
        return;
      }
      var opening = /^ {0,3}(`{3,}|~{3,})([^\n]*)/.exec(line);
      if (opening && (opening[1][0] !== "`" || !opening[2].includes("`"))) {
        flush(); result += line; fence = opening[1]; indented = false; return;
      }
      // Indented code starts after a blank line, and may contain blank lines.
      if (/^( {4}|\t)/.test(line) && (indented || i === 0 || !lines[i - 1].trim())) {
        flush(); result += line; indented = true; return;
      }
      if (indented && !line.trim()) { result += line; return; }
      indented = false; prose += line;
    });
    flush(); return result;
  }
  window.markdownMath = {
    toEditor: function (markdown) {
      return outsideCode(markdown, function (text) {
        return text.replace(/\\\\|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g, function (match, block, inline) {
          return block !== undefined ? "$$" + block + "$$" : inline !== undefined ? "$" + inline + "$" : match;
        });
      });
    },
    fromEditor: function (markdown) {
      return outsideCode(markdown, function (text) {
        // Consume escapes and display math first, including escaped dollars.
        return text.replace(/\\[\s\S]|\$\$[\s\S]*?\$\$|\$(?!\$|\s)((?:\\[^\n]|[^$\n])+?)\$(?!\$)/g, function (match, inline) {
          return inline !== undefined && !/\s$/.test(inline) ? "\\(" + inline + "\\)" : match;
        });
      });
    }
  };
})();
