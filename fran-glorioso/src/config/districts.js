/**
 * FRAN GLORIOSO — Configuración de luz y atmósfera por distrito.
 * Especificación Visual Técnica §1 (cielo/fog) y §2 (tabla de luz por distrito).
 *
 * El vertical slice sólo instancia `norte`, pero los otros cuatro quedan
 * definidos para que expandir sea cambiar una constante, no reescribir código.
 */

import { PALETAS } from './palette.js';

/**
 * @typedef {Object} DistritoConfig
 * @property {string} nombre
 * @property {number} cielo        Color del clearColor del renderer (§1).
 * @property {{color:number, intensidad:number}} ambient
 * @property {{color:number, intensidad:number}} sol
 * @property {{color:number, cielo:number, suelo:number, intensidad:number}} relleno
 * @property {{color:number, near:number, far:number}} fog
 * @property {Object} paleta
 */

/** @type {Record<string, DistritoConfig>} */
export const DISTRITOS = {
  norte: {
    nombre: 'Barrio Norte — Los Elegantes',
    cielo: 0x87A9C4,
    ambient: { color: 0xFFF4E6, intensidad: 0.6 },
    sol:     { color: 0xFFFFFF, intensidad: 1.0 },
    relleno: { cielo: 0x87A9C4, suelo: 0xD8D8D2, intensidad: 0.4 },
    fog:     { color: 0x87A9C4, near: 60, far: 150 },
    paleta:  PALETAS.norte,
  },

  sur: {
    nombre: 'Barrio Sur — Los Pesados',
    cielo: 0x9A9186,
    ambient: { color: 0xB8B0A0, intensidad: 0.4 },
    sol:     { color: 0xFFE8C4, intensidad: 0.8 },
    relleno: { cielo: 0x9A9186, suelo: 0x6B6B63, intensidad: 0.4 },
    fog:     { color: 0x9A9186, near: 30, far: 100 }, // más cerrado, polvo industrial
    paleta:  PALETAS.sur,
  },

  este: {
    nombre: 'Barrio Este — Los Tecnológicos',
    cielo: 0x1A2438,
    ambient: { color: 0x3A4A6A, intensidad: 0.35 },
    sol:     { color: 0xC4D8FF, intensidad: 0.7 },
    relleno: { cielo: 0x1A2438, suelo: 0x0D0D0F, intensidad: 0.4 },
    fog:     { color: 0x1A2438, near: 40, far: 120 },
    paleta:  PALETAS.este,
  },

  oeste: {
    nombre: 'Barrio Oeste — Los Rebeldes',
    cielo: 0xC4A26B,
    ambient: { color: 0xFFD9A0, intensidad: 0.55 },
    sol:     { color: 0xFFC46B, intensidad: 1.1 },   // hora dorada
    relleno: { cielo: 0xC4A26B, suelo: 0x6B5842, intensidad: 0.4 },
    fog:     { color: 0xC4A26B, near: 50, far: 130 },
    paleta:  PALETAS.oeste,
  },

  central: {
    nombre: 'Distrito Central — La Guardia del Rey',
    cielo: 0xC8CED8,
    ambient: { color: 0xE8E8F0, intensidad: 0.6 },
    sol:     { color: 0xFFFFFF, intensidad: 1.1 },
    relleno: { cielo: 0xC8CED8, suelo: 0xE8E4D8, intensidad: 0.4 },
    fog:     { color: 0xC8CED8, near: 70, far: 180 }, // más despejado
    paleta:  PALETAS.central,
  },
};

/** Distrito del vertical slice. */
export const DISTRITO_ACTIVO = 'norte';

export function getDistrito(id = DISTRITO_ACTIVO) {
  const d = DISTRITOS[id];
  if (!d) throw new Error(`Distrito desconocido: ${id}`);
  return d;
}
