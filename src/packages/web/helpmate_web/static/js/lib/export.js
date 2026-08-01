// Client-side exports. No network, no DOM -- callers wrap the result in a Blob.

// One PGN game per optimal line. Helpmates start with Black, so the movetext
// opens with "1..." and each pair of plies is one numbered move.
export function toPgn(fen, lines) {
  return lines.map((line) => {
    const parts = [];
    for (let i = 0; i < line.length; i++) {
      const moveNo = Math.floor(i / 2) + 1;
      if (i === 0) parts.push(`${moveNo}... ${line[i]}`);
      else if (i % 2 === 1) parts.push(`${moveNo + 1}. ${line[i]}`);
      else parts.push(`${moveNo}... ${line[i]}`);
    }
    return [
      '[Event "helpmate"]',
      '[SetUp "1"]',
      `[FEN "${fen}"]`,
      "",
      `${parts.join(" ")} *`,
      "",
    ].join("\n");
  }).join("\n");
}

export function toFenList(fens) {
  return fens.map((f) => `${f}\n`).join("");
}

export function toCsv(rows) {
  const esc = (v) => (typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : String(v));
  const head = "fen,dtm,count";
  const body = rows.map((r) => [esc(r.fen), r.dtm, r.count].join(",")).join("\n");
  return rows.length ? `${head}\n${body}\n` : `${head}\n`;
}
