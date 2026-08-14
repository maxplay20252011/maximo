/**
 * FRAN GLORIOSO — Texturas procedurales.
 * Especificación Visual Técnica §6.
 *
 * En el vertical slice no hay archivos de textura: todo se genera por código.
 * Así el checklist §11 ("sin warnings de textura faltante", "sin 404 de assets")
 * se cumple por construcción, no por suerte.
 */

import * as THREE from 'three';
import { NORTE, SUR } from '../config/palette.js';
import { maxTextura } from '../config/quality.js';

const cache = new Map();

function hex(n) { return '#' + n.toString(16).padStart(6, '0'); }

function lienzo(lado) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = lado;
  return { canvas, ctx: canvas.getContext('2d') };
}

function aTextura(canvas, { anisotropy = 4 } = {}) {
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;   // el canvas dibuja en sRGB
  tex.anisotropy = anisotropy;
  return tex;
}

/** Resolución de textura acotada al presupuesto §9 (512 mobile / 1024 desktop). */
function lado() { return Math.min(256, maxTextura()); }

/* ── Vereda: hormigón peinado claro con juntas cada 1.5 m ──────────────────
 * Un tile = UNA losa. La junta se dibuja como borde de media anchura: al
 * repetirse, cada borde se une con el del tile vecino y forma la junta entera.
 *
 * Nota de spec: el snippet de §6 recorre `i += 128` sobre un canvas de 256, lo
 * que mete una junta extra al medio del tile y deja el paso real en 0.75 m,
 * contra los 1.5 m que pide el mismo párrafo y la fórmula de repetición
 * (`metros / 1.5`). Mandan el paso declarado y la fórmula.                    */
export function crearTexturaVereda() {
  if (cache.has('vereda')) return cache.get('vereda');
  const L = lado();
  const { canvas, ctx } = lienzo(L);
  const junta = Math.max(2, Math.round((3 * L) / 256));

  ctx.fillStyle = '#C8C5BC';                       // color de junta como fondo
  ctx.fillRect(0, 0, L, L);
  ctx.fillStyle = hex(NORTE.vereda);
  ctx.fillRect(junta / 2, junta / 2, L - junta, L - junta);

  // Peinado del hormigón: líneas finas, sólo dentro de la losa.
  ctx.save();
  ctx.beginPath();
  ctx.rect(junta / 2, junta / 2, L - junta, L - junta);
  ctx.clip();
  ctx.strokeStyle = 'rgba(200, 197, 188, 0.35)';
  ctx.lineWidth = 1;
  for (let y = 0; y < L; y += 6) {
    ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(L, y + 0.5); ctx.stroke();
  }
  ctx.restore();

  const tex = aTextura(canvas);
  cache.set('vereda', tex);
  return tex;
}

/* ── Asfalto: base #4A4A48 con ruido sutil ───────────────────────────────── */
export function crearTexturaAsfalto() {
  if (cache.has('asfalto')) return cache.get('asfalto');
  const L = lado();
  const { canvas, ctx } = lienzo(L);

  ctx.fillStyle = hex(NORTE.calle);
  ctx.fillRect(0, 0, L, L);

  // Píxeles aleatorios entre #424240 y #525250, opacidad baja.
  const granos = L * L * 0.18;
  for (let i = 0; i < granos; i++) {
    const claro = Math.random() > 0.5;
    ctx.fillStyle = claro ? 'rgba(82, 82, 80, 0.5)' : 'rgba(66, 66, 64, 0.5)';
    ctx.fillRect((Math.random() * L) | 0, (Math.random() * L) | 0, 1, 1);
  }

  const tex = aTextura(canvas);
  cache.set('asfalto', tex);
  return tex;
}

/* ── Ladrillo (Sur / Oeste): hiladas 64×32 con offset alternado ──────────── */
export function crearTexturaLadrillo(colorBase = SUR.ladrilloVisto) {
  const clave = `ladrillo:${colorBase}`;
  if (cache.has(clave)) return cache.get(clave);
  const L = lado();
  const { canvas, ctx } = lienzo(L);
  const escala = L / 256;
  const anchoL = 64 * escala;
  const altoL = 32 * escala;
  const junta = 4 * escala;

  ctx.fillStyle = hex(SUR.hormigonSucio);   // la junta se ve como fondo
  ctx.fillRect(0, 0, L, L);

  ctx.fillStyle = hex(colorBase);
  let fila = 0;
  for (let y = 0; y < L; y += altoL, fila++) {
    const offset = fila % 2 === 0 ? 0 : -anchoL / 2;
    for (let x = offset; x < L; x += anchoL) {
      ctx.fillRect(x + junta / 2, y + junta / 2, anchoL - junta, altoL - junta);
    }
  }

  const tex = aTextura(canvas);
  cache.set(clave, tex);
  return tex;
}

/* ── Fachada: revoque mate con veteado muy leve ──────────────────────────── */
export function crearTexturaFachada(colorBase) {
  const clave = `fachada:${colorBase}`;
  if (cache.has(clave)) return cache.get(clave);
  const L = lado();
  const { canvas, ctx } = lienzo(L);

  ctx.fillStyle = hex(colorBase);
  ctx.fillRect(0, 0, L, L);
  for (let i = 0; i < L * L * 0.05; i++) {
    ctx.fillStyle = `rgba(0, 0, 0, ${0.02 + Math.random() * 0.03})`;
    ctx.fillRect((Math.random() * L) | 0, (Math.random() * L) | 0, 2, 1);
  }

  const tex = aTextura(canvas);
  cache.set(clave, tex);
  return tex;
}

/**
 * §6 — Repetición según superficie.
 * Vereda: 1 tile cada 1.5 m · Asfalto: cada 4 m · Ladrillo: cada 2 m.
 */
export const ESCALA_UV = { vereda: 1.5, asfalto: 4, ladrillo: 2, fachada: 3 };

/**
 * Clona una textura compartida con su propia repetición.
 * Clonar comparte la imagen en GPU pero permite `repeat` distinto por superficie.
 */
export function conRepeticion(tex, anchoEnMetros, largoEnMetros, tipo = 'vereda') {
  const paso = ESCALA_UV[tipo] ?? 1;
  const clon = tex.clone();
  clon.needsUpdate = true;
  clon.wrapS = clon.wrapT = THREE.RepeatWrapping;
  clon.repeat.set(anchoEnMetros / paso, largoEnMetros / paso);
  return clon;
}

export function disposeTexturas() {
  for (const t of cache.values()) t.dispose();
  cache.clear();
}
