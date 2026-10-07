/* 更新界面标签，不触碰文档、批注内容、选区或撤销历史。 */
window.installLanguage = function (editor) {
  "use strict";
  var locale = "zh_CN", dictionary = {}, reverse = {}, patterns = [], editorPairs = {};
  var ignored = '.vditor-reset,.vditor-sv,.vditor-preview,.review-quote,.review-card p,#mdv-review-quote,#mdv-review-input,.translation-source,.translation-name,.translation-stream';
  function translate(text) {
    var source = locale === "en" ? dictionary : reverse;
    if (Object.prototype.hasOwnProperty.call(source, text)) { return source[text]; }
    var trimmed = text.trim();
    if (Object.prototype.hasOwnProperty.call(source, trimmed)) { return text.replace(trimmed, source[trimmed]); }
    for (var i = 0; i < patterns.length; i++) {
      var rule = patterns[i], match = (locale === "en" ? rule.zh : rule.en).exec(text);
      if (match) { return (locale === "en" ? rule.target : rule.source).replace(/\{(\d+)\}/g, function (_, n) { return match[Number(n) + 1]; }); }
    }
    var shortcut = /^(.+?)(\s*<[^>]+>)$/.exec(text);
    if (shortcut && source[shortcut[1]]) { return source[shortcut[1]] + shortcut[2]; }
    return text;
  }
  function blocked(node) { var el = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement; return el && el.closest(ignored); }
  function translateElement(element) {
    if (blocked(element) || element.matches('script,style')) { return; }
    ["title", "aria-label", "placeholder"].forEach(function (name) {
      if (element.hasAttribute(name)) {
        var before = element.getAttribute(name), after = translate(before);
        if (before !== after) { element.setAttribute(name, after); }
      }
    });
    Array.from(element.childNodes).forEach(function (node) {
      if (node.nodeType === Node.TEXT_NODE) {
        var result = translate(node.nodeValue); if (result !== node.nodeValue) { node.nodeValue = result; }
      } else if (node.nodeType === Node.ELEMENT_NODE) { translateElement(node); }
    });
  }
  function expression(template) {
    var escaped = template.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{\d+\\\}/g, "(.*?)");
    return new RegExp("^" + escaped + "$", "s");
  }
  window.uiText = translate;
  window.setLanguage = function (value, strings) {
    locale = value === "en" ? "en" : "zh_CN";
    dictionary = Object.assign({}, strings);
    Object.keys(window.__editorLocales.zh_CN).forEach(function (key) {
      var zh = window.__editorLocales.zh_CN[key], en = window.__editorLocales.en[key];
      if (typeof zh === "string" && typeof en === "string") { editorPairs[zh] = en; }
    });
    dictionary = Object.assign({}, editorPairs, dictionary); reverse = {}; patterns = [];
    Object.keys(dictionary).forEach(function (source) {
      var target = dictionary[source]; reverse[target] = source;
      if (source.includes("{0}")) { patterns.push({source: source, target: target, zh: expression(source), en: expression(target)}); }
    });
    window.VditorI18n = window.__editorLocales[locale];
    editor.vditor.options.lang = locale === "en" ? "en_US" : "zh_CN";
    editor.vditor.options.i18n = window.VditorI18n;
    document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
    translateElement(document.body);
  };
  new MutationObserver(function (records) {
    records.forEach(function (record) {
      if (blocked(record.target)) { return; }
      if (record.type === "characterData") {
        var result = translate(record.target.nodeValue);
        if (result !== record.target.nodeValue) { record.target.nodeValue = result; }
      } else if (record.type === "attributes") { translateElement(record.target); }
      else { record.addedNodes.forEach(function (node) {
        if (node.nodeType === Node.ELEMENT_NODE) { translateElement(node); }
        else if (node.nodeType === Node.TEXT_NODE) { var text = translate(node.nodeValue); if (text !== node.nodeValue) { node.nodeValue = text; } }
      }); }
    });
  }).observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["title", "aria-label", "placeholder"]});
};
