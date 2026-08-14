/**
 * FRAN GLORIOSO — Paleta oficial.
 * Especificación Visual Técnica §3 (distritos + personajes) y §8 (HUD + rarezas).
 *
 * REGLA: ningún color literal se escribe fuera de este archivo. Si un color no
 * está acá, no existe en el juego.
 */

/* ── §3 Barrio Norte — Los Elegantes ─────────────────────────────────────── */
export const NORTE = {
  fachadaPrincipal:  0xF5F5F0,
  fachadaSecundaria: 0xD8D8D2,
  detalleMadera:     0xC9A876,
  aberturas:         0x1A1A1A,
  vegetacion:        0x4A7A3C,
  vereda:            0xE5E2D8,
  calle:             0x4A4A48,
  techo:             0x3A3A38,
};

/* ── §3 Barrio Sur — Los Pesados ─────────────────────────────────────────── */
export const SUR = {
  ladrilloVisto:  0x8B4A3A,
  hormigonSucio:  0x6B6B63,
  oxido:          0xB5541E,
  metalExpuesto:  0x2B2B26,
  grafitiRojo:    0xC23B22,
  grafitiAmarillo:0xD9A441,
  grafitiAzul:    0x2E5C8A,
};

/* ── §3 Barrio Este — Los Tecnológicos ───────────────────────────────────── */
export const ESTE = {
  baseOscura:     0x0D0D0F,
  blancoFrio:     0xEAEAEF,
  azulElectrico:  0x00D4FF,   // emisivo
  violetaNeon:    0x8B5CF6,   // emisivo
  vidrio:         0x2A3A4A,
};

/* ── §3 Barrio Oeste — Los Rebeldes ──────────────────────────────────────── */
export const OESTE = {
  ladrilloRojo:    0x9C4A3C,
  chapaGris:       0x8A8A82,
  verdeOxidado:    0x5C7A5E,
  maderaEnvejecida:0x6B5842,
  tierra:          0xC4A26B,
};

/* ── §3 Distrito Central — La Guardia del Rey ────────────────────────────── */
export const CENTRAL = {
  piedraClara:        0xE8E4D8,
  vidrioEspejado:     0x3A4A5A,
  doradoInstitucional:0xC9A227,
  negroSeguridad:     0x1A1A1A,
};

export const PALETAS = { norte: NORTE, sur: SUR, este: ESTE, oeste: OESTE, central: CENTRAL };

/* ── §3 Personajes (placeholders del vertical slice) ─────────────────────────
 * capsula: argumentos exactos de THREE.CapsuleGeometry(radius, length).
 * alturaModelo: altura objetivo en metros cuando se reemplace por .glb (§12).
 *   Fran tiene ~12 años → ~1.5 m. La cápsula placeholder mide 1.7 m
 *   (1.0 + 2×0.35); la diferencia es intencional y sólo afecta al placeholder.
 */
export const PERSONAJES = {
  fran:     { color: 0x3B7DD8, capsula: { radio: 0.35, largo: 1.00 }, alturaModelo: 1.50 },
  cadete:   { color: 0xD84343, capsula: { radio: 0.32, largo: 1.00 }, alturaModelo: 1.65 },
  boxeador: { color: 0xE8792B, capsula: { radio: 0.42, largo: 1.05 }, alturaModelo: 1.85 },
  aliado:   { color: 0x43D87D, capsula: { radio: 0.35, largo: 1.00 }, alturaModelo: 1.60 },
};

/* ── §5 Contorno (outline) ───────────────────────────────────────────────── */
export const OUTLINE_COLOR = 0x1A1A1A;
export const OUTLINE_SCALE = 1.05;

/* ── §7 VFX de combate ───────────────────────────────────────────────────── */
export const VFX = {
  flashImpacto:  0xFFFFFF,
  tinteEsquive:  0x7DB8FF,
  polvoNorte:    0xD8D8D2,
  polvoOeste:    0xC4A26B,
};

/* ── §8 HUD ──────────────────────────────────────────────────────────────── */
export const HUD = {
  vida:    '#D84343',
  escudo:  '#3B9DD8',
  stamina: '#5CC94A',
  fondoBarras:  'rgba(26, 26, 26, 0.5)',    // #1A1A1A @ 0.5
  bordeBarras:  'rgba(255, 255, 255, 0.3)', // #FFFFFF @ 0.3, 2px
  texto:        '#FFFFFF',
  sombraTexto:  '#000000',
};

/* ── §8 Rareza de armas (bordes de íconos en toda la UI) ─────────────────── */
export const RAREZA = {
  comun:      '#9E9E9E',
  pocoComun:  '#4CAF50',
  rara:       '#2196F3',
  epica:      '#9C27B0',
  legendaria: '#FFB300',
  mitica:     '#E53935',
};

/** Rareza → número, para tintar partículas de impacto (§7). */
export const RAREZA_HEX = {
  comun: 0x9E9E9E, pocoComun: 0x4CAF50, rara: 0x2196F3,
  epica: 0x9C27B0, legendaria: 0xFFB300, mitica: 0xE53935,
};
