// Thin wrapper over the read-only API. Two rules the UI depends on:
//   * 202 is NOT an error -- it means "the table is downloading"; the caller
//     polls. We return the status so callers can branch.
//   * 4xx/5xx carry the {"error": {code, message, hint}} envelope; we turn
//     that into an ApiError so every screen can render it the same way.
// How long a screen keeps polling a 202 "fetching" response before it gives
// up and tells the user to retry: 40 attempts at 1500ms is ~60s. One policy,
// shared by every screen that can meet a downloading table.
export const DOWNLOAD_RETRY_CAP = 40;
export const DOWNLOAD_RETRY_MS = 1500;

export class ApiError extends Error {
  constructor(status, code, message, hint) {
    super(message || `HTTP ${status}`);
    this.status = status; this.code = code; this.hint = hint || null;
  }
}

export async function getJson(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    // A repeatable parameter (theme=a&theme=b) needs append, not set --
    // searchParams.set can only ever hold the LAST value of a repeated key.
    if (Array.isArray(v)) {
      for (const item of v) url.searchParams.append(k, item);
      continue;
    }
    url.searchParams.set(k, v);
  }
  let res;
  try {
    res = await fetch(url);
  } catch {
    // status 0 marks "no HTTP response was received at all" (server down,
    // DNS failure, CORS block) so callers can tell it apart from a real
    // HTTP error status and don't have to also handle a raw TypeError.
    throw new ApiError(0, "network", "cannot reach the server", null);
  }
  let body = null;
  try { body = await res.json(); } catch { /* empty or non-JSON body */ }
  if (res.status >= 400) {
    const e = body && body.error ? body.error : {};
    throw new ApiError(res.status, e.code || "error", e.message || res.statusText, e.hint);
  }
  return { status: res.status, body };
}

export const api = {
  health: () => getJson("/v1/health"),
  materials: () => getJson("/v1/materials"),
  stats: (name) => getJson(`/v1/materials/${encodeURIComponent(name)}/stats`),
  overall: () => getJson("/v1/stats"),
  probe: (fen, themes = false) => getJson("/v1/probe", { fen, themes: themes ? "true" : "" }),
  line: (fen, all = false) => getJson("/v1/line", { fen, all: all ? "true" : "" }),
  moves: (fen) => getJson("/v1/moves", { fen }),
  mine: (q) => getJson("/v1/mine", q),
  themes: () => getJson("/v1/themes"),
};
