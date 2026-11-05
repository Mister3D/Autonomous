/** Couleur stable par bot, en attendant l'icône animée. */
const PALETTE = [
  "#2f80ed",
  "#f5a623",
  "#9b51e0",
  "#27ae60",
  "#1abc9c",
  "#eb5757",
  "#2d9cdb",
  "#f2994a",
  "#bb6bd9",
  "#219653",
  "#56ccf2",
  "#eb4d8a",
];

export function avatarColor(seed) {
  const s = String(seed || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
