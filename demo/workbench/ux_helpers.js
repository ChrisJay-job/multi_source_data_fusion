/** TASK-009 UX helpers: stable fusionId colors and safe text. */

const PALETTE = [
  "#ffd166",
  "#06d6a0",
  "#118ab2",
  "#ef476f",
  "#9b5de5",
  "#f4a261",
  "#2a9d8f",
  "#e9c46a",
  "#e76f51",
  "#8ecae6",
];

/** Stable color from full fusionId (same run, filter/page-independent). */
export function colorFromFusionId(fid) {
  const s = String(fid || "");
  if (!s || s.startsWith("raw:")) {
    if (s === "raw:rid") return "#4cc9f0";
    if (s === "raw:spectrum") return "#f72585";
    if (s === "raw:radar") return "#7209b7";
    return "#adb5bd";
  }
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return PALETTE[Math.abs(h) % PALETTE.length];
}

export function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function shortFid(fid) {
  const s = String(fid || "");
  if (s.length <= 14) return s;
  return "…" + s.slice(-10);
}

/** Distance from point to segment in canvas pixels. */
export function distPointSeg(px, py, x0, y0, x1, y1) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-9) return Math.hypot(px - x0, py - y0);
  let t = ((px - x0) * dx + (py - y0) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
}
