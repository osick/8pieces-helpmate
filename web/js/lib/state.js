// URL <-> view state. The position lives in the hash so a link is shareable
// and the browser's back button navigates position history.
export function encodeState({ fen, panel = "explorer" }) {
  const p = new URLSearchParams();
  if (fen) p.set("fen", fen);
  if (panel && panel !== "explorer") p.set("panel", panel);
  const s = p.toString();
  return s ? `#${s}` : "#";
}

export function decodeState(hash) {
  const p = new URLSearchParams((hash || "").replace(/^#/, ""));
  return { fen: p.get("fen"), panel: p.get("panel") || "explorer" };
}
