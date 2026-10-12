/* Animate UI layout only; never observe or rewrite the document body. */
window.installMotion = function () {
  "use strict";
  const toolbar = document.querySelector("#vditor .vditor-toolbar");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const duration = 250, easing = "cubic-bezier(.22,1,.36,1)";
  const moving = new Map();
  let previous = new Map(), previousHeight = 0, heightMotion = null, scheduled = 0;
  const enabled = () => !reduced.matches && document.documentElement.dataset.motionEnabled !== "false" && !document.hidden;

  function settle() {
    moving.forEach(animation => animation.cancel()); moving.clear();
    if (heightMotion) heightMotion.cancel();
    heightMotion = null; toolbar.style.height = "";
  }
  function reflow() {
    if (scheduled) cancelAnimationFrame(scheduled);
    scheduled = 0;
    if (!toolbar.offsetWidth) { settle(); previous.clear(); previousHeight = 0; return; }
    // Batch all layout reads before starting animations. The stored positions
    // are untransformed, so an interrupted animation resumes where it is seen.
    const next = new Map(), deltas = [];
    let bottom = 0;
    for (const item of toolbar.children) {
      if (!item.classList.contains("vditor-toolbar__item") || !item.offsetWidth) continue;
      const rect = {x: item.offsetLeft, y: item.offsetTop, width: item.offsetWidth};
      next.set(item, rect); bottom = Math.max(bottom, rect.y + item.offsetHeight);
      const old = previous.get(item);
      if (old && (old.x !== rect.x || old.y !== rect.y)) {
        const transform = getComputedStyle(item).transform;
        const matrix = transform === "none" ? {m41: 0, m42: 0} : new DOMMatrixReadOnly(transform);
        deltas.push({item, x: old.x + matrix.m41 - rect.x, y: old.y + matrix.m42 - rect.y});
      }
    }
    const style = getComputedStyle(toolbar);
    const height = Math.max(bottom + parseFloat(style.paddingBottom) + parseFloat(style.borderBottomWidth), parseFloat(style.minHeight) || 0);
    const fromHeight = heightMotion ? toolbar.getBoundingClientRect().height : previousHeight;
    const animate = enabled() && previous.size > 0;
    moving.forEach((animation, item) => { if (!next.has(item)) { animation.cancel(); moving.delete(item); } });
    if (animate) {
      for (const delta of deltas) {
        const {item, x, y} = delta;
        if (moving.has(item)) moving.get(item).cancel();
        const animation = item.animate([{transform: `translate(${x}px, ${y}px)`}, {transform: "translate(0, 0)"}], {duration, easing});
        moving.set(item, animation);
        animation.onfinish = () => { if (moving.get(item) === animation) moving.delete(item); };
      }
      if (height !== previousHeight) {
        if (heightMotion) heightMotion.cancel();
        toolbar.style.height = height + "px";
        const animation = toolbar.animate([{height: fromHeight + "px"}, {height: height + "px"}], {duration, easing});
        heightMotion = animation;
        animation.onfinish = () => { if (heightMotion === animation) { heightMotion = null; toolbar.style.height = ""; } };
      }
    } else settle();
    previous = next; previousHeight = height;
  }
  function schedule() { if (!scheduled) scheduled = requestAnimationFrame(reflow); }
  // Observe the fixed-size editor, not the animated toolbar height itself.
  // This runs before paint without creating ResizeObserver feedback loops.
  new ResizeObserver(reflow).observe(toolbar.parentElement);
  new MutationObserver(schedule).observe(toolbar, {childList: true, characterData: true, subtree: true});
  new MutationObserver(schedule).observe(toolbar.parentElement, {attributes: true, attributeFilter: ["class"]});
  new MutationObserver(() => { if (!enabled()) settle(); schedule(); }).observe(document.documentElement,
    {attributes: true, attributeFilter: ["data-sidebar-visible", "data-motion-enabled"]});
  reduced.addEventListener("change", () => { settle(); schedule(); });
  document.addEventListener("visibilitychange", () => { settle(); previous.clear(); schedule(); });
  reflow();
};
