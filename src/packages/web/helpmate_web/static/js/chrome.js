// Publishes the header's rendered height as `--header-h` on :root.
//
// The header is sticky, so everything that pins below it -- the board, the
// materials list, the search form -- needs to clear it. A constant would be
// wrong: the header is a wrapping flex row (brand, nav, server chip), and
// between roughly 860px and 1100px it wraps to two lines and doubles in
// height. Above 1100px it does not. Hardcoding either number puts the board
// under the header at one width or leaves a gap at the other.
//
// ResizeObserver rather than a resize listener: the header also grows when
// the server chip's text arrives (it is `hidden` until /v1/health answers,
// and "v0.14.0 · 295 tables" is wider than nothing), which is a size change
// with no window resize behind it.
//
// The CSS carries a fallback value for the same token, so a browser without
// ResizeObserver -- or the window between first paint and this module running
// -- still pins somewhere sane rather than at 0.
export function initStickyChrome(header = document.querySelector("header")) {
  if (!header) return;
  const apply = () => {
    // getBoundingClientRect, not offsetHeight: this feeds a `top` offset in
    // CSS pixels and offsetHeight is rounded to an integer, which on a
    // fractional-height header (66.25px here) leaves a sub-pixel seam of the
    // scrolling content visible above the pinned board.
    const h = header.getBoundingClientRect().height;
    if (h > 0) document.documentElement.style.setProperty("--header-h", `${h}px`);
  };
  apply();
  if (typeof ResizeObserver === "function") new ResizeObserver(apply).observe(header);
  else window.addEventListener("resize", apply);
}
