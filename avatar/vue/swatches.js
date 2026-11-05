/** 18 presets [name, hue, saturation %, lightness factor]; null = original drawing */
export const SWATCHES = [
  ["Original", null],
  ["Rouge", 2, 62, -0.05],
  ["Corail", 12, 72, 0.05],
  ["Ambre", 34, 78, 0],
  ["Jaune", 46, 75, 0.08],
  ["Brun", 24, 38, -0.22],
  ["Vert", 110, 38, -0.05],
  ["Menthe", 150, 40, 0.1],
  ["Sarcelle", 178, 45, -0.08],
  ["Ciel", 198, 62, 0.08],
  ["Bleu", 218, 58, -0.05],
  ["Marine", 225, 45, -0.32],
  ["Violet", 270, 45, -0.05],
  ["Lavande", 255, 45, 0.12],
  ["Rose", 330, 62, 0.08],
  ["Framboise", 345, 52, -0.12],
  ["Gris", 220, 6, 0.02],
  ["Anthracite", 220, 8, -0.35],
];

/** Pastille « Original » : coupée en deux (gris moyen | orange). */
export const ORIGINAL_SWATCH_CSS =
  "linear-gradient(90deg, #9a9aa2 0 50%, #f08c12 50% 100%)";

export function swatchCss(sw) {
  if (!sw || sw[1] == null) return null;
  return `hsl(${sw[1]} ${sw[2]}% ${Math.round(58 * (1 + sw[3]))}%)`;
}

export function swatchCssAt(index) {
  const i = Math.max(0, Math.min(SWATCHES.length - 1, Number(index) || 0));
  return swatchCss(SWATCHES[i]);
}

/** Background CSS for a swatch button (Original = split disk). */
export function swatchButtonBackground(sw) {
  if (!sw || sw[1] == null) return ORIGINAL_SWATCH_CSS;
  return swatchCss(sw);
}
