import { api } from "./api.js";

// A one-line answer to "is the server there, and does it have anything?".
// Failure is not an error banner: the rest of the page will surface its own
// errors on the first real request, and a red chip says it once, quietly.
export async function initServerChip() {
  const el = document.getElementById("server-chip");
  const corpus = document.getElementById("footer-corpus");
  try {
    const { body } = await api.health();
    const remote = body.tables_remote ? ` · ${body.tables_remote} remote` : "";
    el.textContent = `v${body.version} · ${body.tables_local} tables${remote}`;
    el.classList.remove("down");
    // Same /v1/health response the chip above already fetched -- one
    // sentence naming what the corpus holds, no second request.
    if (corpus) {
      const total = body.tables_local + (body.tables_remote || 0);
      corpus.textContent = `The corpus holds ${total} tables ` +
        `(${body.tables_local} local${remote}).`;
    }
  } catch {
    el.textContent = "server unreachable";
    el.classList.add("down");
    if (corpus) corpus.textContent = "";
  }
  el.hidden = false;
  window.__chipReady = true;
}
