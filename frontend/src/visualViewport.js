/**
 * Keep the mobile shell inside the visible viewport.
 * Firefox Android (and others) overlay the keyboard without shrinking layout
 * height, so a bottom composer stays hidden. visualViewport reports the area
 * that is actually on screen.
 */

const MOBILE = "(max-width: 720px)";

export function readVisualViewport(win = window) {
  const vv = win.visualViewport;
  if (!vv) return null;
  return {
    top: Math.max(0, Number(vv.offsetTop) || 0),
    height: Math.max(0, Number(vv.height) || 0),
  };
}

export function applyVisualViewport(doc = document, win = window) {
  const box = readVisualViewport(win);
  if (!box) return null;
  const root = doc.documentElement;
  root.style.setProperty("--vv-top", `${box.top}px`);
  root.style.setProperty("--vvh", `${box.height}px`);
  return box;
}

export function clearVisualViewport(doc = document) {
  const root = doc.documentElement;
  root.style.removeProperty("--vv-top");
  root.style.removeProperty("--vvh");
}

function isField(target, win) {
  return target instanceof win.Element && target.matches("textarea, input, select, [contenteditable='true']");
}

export function bindVisualViewport(win = window) {
  const vv = win.visualViewport;
  if (!vv) return () => {};
  const sync = () => applyVisualViewport(win.document, win);
  sync();
  vv.addEventListener("resize", sync);
  vv.addEventListener("scroll", sync);
  win.addEventListener("orientationchange", sync);
  const onFocus = (ev) => {
    if (!isField(ev.target, win)) return;
    sync();
    win.requestAnimationFrame(sync);
    win.setTimeout(sync, 350);
  };
  win.addEventListener("focusin", onFocus);
  return () => {
    vv.removeEventListener("resize", sync);
    vv.removeEventListener("scroll", sync);
    win.removeEventListener("orientationchange", sync);
    win.removeEventListener("focusin", onFocus);
  };
}

export function installVisualViewport(win = window) {
  const mq = win.matchMedia(MOBILE);
  let stop = () => {};
  const update = () => {
    stop();
    stop = () => {};
    if (!mq.matches) {
      clearVisualViewport(win.document);
      return;
    }
    stop = bindVisualViewport(win);
  };
  update();
  mq.addEventListener("change", update);
  return () => {
    mq.removeEventListener("change", update);
    stop();
    clearVisualViewport(win.document);
  };
}
