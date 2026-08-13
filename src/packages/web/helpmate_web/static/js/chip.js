// A one-line answer to "is the server there, and does it have anything?".
// Failure is not an error banner: the rest of the page will surface its own
// errors on the first real request, and a red chip says it once, quietly.
//
// The health body is passed in rather than fetched: index.html needs the same
// response to decide whether search exists, and one boot makes one request.
export function initServerChip(health) {
  const el = document.getElementById("server-chip");
  const corpus = document.getElementById("footer-corpus");
  if (health) {
    const remote = health.tables_remote ? ` · ${health.tables_remote} remote` : "";
    el.textContent = `v${health.version} · ${health.tables_local} tables${remote}`;
    el.classList.remove("down");
    if (corpus) {
      const total = health.tables_local + (health.tables_remote || 0);
      corpus.textContent = `The corpus holds ${total} tables ` +
        `(${health.tables_local} local${remote}).`;
    }
  } else {
    el.textContent = "server unreachable";
    el.classList.add("down");
    if (corpus) corpus.textContent = "";
  }
  el.hidden = false;
  window.__chipReady = true;
}
