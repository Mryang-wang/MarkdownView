"""Exercise real annotation rebasing without starting a browser or GUI."""
import argparse
import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine


ROOT = Path(__file__).resolve().parent


def load(path):
    engine = QJSEngine()
    source = Path(path).read_text(encoding="utf-8")
    # Expose the existing pure functions while bypassing DOM setup. The refresh
    # path itself is unchanged; only DOM indexing/rendering are replaced by data.
    seam = '''
    var supplied, calls, originalLocate = locate;
    locate = function () { calls.locate++; return originalLocate.apply(null, arguments); };
    root = function () {};
    indexText = function () { return {text: supplied, segments: []}; };
    paint = function () { calls.paint++; };
    renderList = function () {};
    return {
      anchor: function (text, start, end) { return anchorAt({text: text}, start, end); },
      apply: function (oldText, newText, anchors, edited) {
        supplied = newText; calls = {locate: 0, paint: 0};
        comments = anchors.map(function (anchor) { return {anchor: anchor}; });
        pending = remembered = null; previous = {text: oldText};
        previousMd = "old"; editor.getValue = function () { return edited ? "new" : "old"; };
        loading = false; timer = null;
        refresh();
        return {anchors: anchors, calls: calls};
      }
    };
    '''
    source = source.replace('  "use strict";', '  "use strict";' + seam, 1)
    result = engine.evaluate("var window = {}; function clearTimeout() {}\n" + source +
                             "\nvar review = window.installReviewFeatures({});")
    assert not result.isError(), result.toString()
    return engine


def evaluate(engine, code):
    result = engine.evaluate("JSON.stringify((function () {" + code + "})())")
    assert not result.isError(), result.toString()
    return json.loads(result.toString())


def run():
    app = QCoreApplication.instance() or QCoreApplication([])
    engine = load(ROOT / "app/assets/review_features.js")
    cases = [
        ("Before target after.", "NEW Before target after.", "target", "target"),
        ("Before target after.", "Before target after. END", "target", "target"),
        ("Before target after.", "Before taNEWrget after.", "target", "taNEWrget"),
        ("Before target after.", "Before taret after.", "target", "taret"),
    ]
    for old, new, quote, expected in cases:
        result = evaluate(engine, "var old = %s, next = %s, quote = %s; var at = old.indexOf(quote);"
                          "return review.apply(old, next, [review.anchor(old, at, at + quote.length)], true);" %
                          tuple(json.dumps(value) for value in (old, new, quote)))
        anchor = result["anchors"][0]
        assert not anchor["detached"] and anchor["quote"] == expected, result
        assert new[anchor["start"]:anchor["end"]] == expected, result
        assert result["calls"]["paint"] == 1
    detached = evaluate(engine, '''
      var old = "one target two target end", at = old.indexOf("target");
      return review.apply(old, "one  two target end", [review.anchor(old, at, at + 6)], true);
    ''')
    assert detached["anchors"][0]["detached"], detached
    for edited in (False, True):
        unchanged = evaluate(engine, '''
          var text = "one target two target end", at = text.lastIndexOf("target");
          return review.apply(text, text, [review.anchor(text, at, at + 6)], %s);
        ''' % json.dumps(edited))
        assert unchanged["calls"] == {"locate": 0, "paint": 1}, unchanged
        assert unchanged["anchors"][0]["start"] == 15, unchanged
    # Rendering-mode changes can alter the visible text without a Markdown edit.
    relocated = evaluate(engine, '''
      var old = "one target end", at = old.indexOf("target");
      return review.apply(old, "PREFIX " + old, [review.anchor(old, at, at + 6)], false);
    ''')
    assert relocated["calls"]["locate"] == 1 and relocated["anchors"][0]["start"] == 11, relocated
    print("PASS annotation insertion/deletion, duplicate anchors, formatting-only refresh and rendering-mode relocation")
    return app


def benchmark(path):
    engine = load(path)
    result = evaluate(engine, '''
      var source = ("Read this repeated paragraph and keep its annotations.\\n").repeat(400);
      var anchors = [];
      for (var i = 0; i < 100; i++) {
        var at = Math.floor(i * (source.length - 20) / 100);
        anchors.push(review.anchor(source, at, at + 12));
      }
      var start = Date.now();
      var unchanged = review.apply(source, source, JSON.parse(JSON.stringify(anchors)), false);
      var unchangedTime = Date.now() - start;
      start = Date.now();
      var edited = review.apply(source, source + "NEW", anchors, true);
      return {characters: source.length, comments: anchors.length, unchanged_ms: unchangedTime,
              append_ms: Date.now() - start, unchanged_locates: unchanged.calls.locate};
    ''')
    print(json.dumps({"source": str(path), **result}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    arguments = parser.parse_args()
    app = run()
    if arguments.baseline:
        before = benchmark(arguments.baseline)
        after = benchmark(ROOT / "app/assets/review_features.js")
        destination = ROOT / "tmp/review-performance/latest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"before": before, "after": after}, indent=2), encoding="utf-8")
