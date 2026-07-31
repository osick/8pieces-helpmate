// Thin wrapper over the read-only API. Two rules the UI depends on:
//   * 202 is NOT an error -- it means "the table is downloading"; the caller
//     polls. We return the status so callers can branch.
//   * 4xx/5xx carry the {"error": {code, message, hint}} envelope; we turn
//     that into an ApiError so every screen can render it the same way.
export class ApiError extends Error {
  constructor(status, code, message, hint) {
    super(message || `HTTP ${status}`);
    this.status = status; this.code = code; this.hint = hint || null;
  }
}

export async function getJson(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const res = await fetch(url);
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
  probe: (fen) => getJson("/v1/probe", { fen }),
  line: (fen, all = false) => getJson("/v1/line", { fen, all: all ? "true" : "" }),
  moves: (fen) => getJson("/v1/moves", { fen }),
  mine: (q) => getJson("/v1/mine", q),
};
