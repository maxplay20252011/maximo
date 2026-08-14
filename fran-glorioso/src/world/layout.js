/**
 * FRAN GLORIOSO — Trazado del Barrio Norte (datos puros, sin THREE).
 *
 * Manzanas de 34 m con calles de 12 m: 3×3 bloques = 150×150 m de mundo, que
 * es exactamente lo que cubre el fog de §2 (60→150 m) sin que se vea el borde.
 *
 * El layout es determinístico (PRNG con semilla fija): la misma partida produce
 * siempre la misma ciudad, así los colliders y los spawns son reproducibles.
 */

export const L = {
  BLOQUE: 34,
  CALLE: 12,
  PITCH: 46,          // BLOQUE + CALLE
  GRID: 3,
  MUNDO: 150,         // 3×34 + 4×12
  VEREDA_ALTO: 0.15,
  VEREDA_ANCHO: 3.5,
};

export const CENTROS_BLOQUE = [-L.PITCH, 0, L.PITCH];

/** Mulberry32: PRNG chico, rápido y determinístico. */
function prng(semilla) {
  let a = semilla >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const entre = (r, min, max) => min + r() * (max - min);

/**
 * Edificios del barrio.
 * El bloque central (0,0) queda vacío: es la plaza donde ocurre el combate.
 *
 * @returns {Array<{x:number,z:number,w:number,d:number,h:number,
 *                  secundaria:boolean, madera:boolean, landmark:boolean}>}
 */
export function generarEdificios(semilla = 1971) {
  const r = prng(semilla);
  const edificios = [];
  const mitadUtil = L.BLOQUE / 2 - L.VEREDA_ANCHO;   // 13.5 m

  for (const bz of CENTROS_BLOQUE) {
    for (const bx of CENTROS_BLOQUE) {
      if (bx === 0 && bz === 0) continue;            // plaza central

      // Los bloques ortogonales a la plaza son los "de avenida": más altos.
      const enAvenida = bx === 0 || bz === 0;
      const [hMin, hMax] = enAvenida ? [9, 16] : [6, 12];

      // Un edificio por cuadrante, pegado a la esquina exterior de la manzana
      // (perímetro construido + patio interno, como una manzana porteña real).
      let landmarkAsignado = false;
      for (const sx of [-1, 1]) {
        for (const sz of [-1, 1]) {
          const w = entre(r, 9, 12.5);
          const d = entre(r, 9, 12.5);
          const h = entre(r, hMin, hMax);

          // ¿Este cuadrante mira a la plaza central? Ése es el landmark.
          const miraPlaza = enAvenida
            && (bx === 0 ? Math.sign(bz) !== sz : true)
            && (bz === 0 ? Math.sign(bx) !== sx : true);
          const landmark = enAvenida && miraPlaza && !landmarkAsignado;
          if (landmark) landmarkAsignado = true;

          edificios.push({
            x: bx + sx * (mitadUtil - w / 2),
            z: bz + sz * (mitadUtil - d / 2),
            w, d, h,
            secundaria: r() > 0.5,
            madera: r() > 0.4,
            landmark,
          });
        }
      }
    }
  }
  return edificios;
}

/** Canteros y bancos de la plaza central: cobertura para el combate. */
export function generarPlaza() {
  const canteros = [];
  for (const [x, z] of [[-9, -9], [9, -9], [-9, 9], [9, 9]]) {
    canteros.push({ x, z, w: 5, d: 5, h: 0.55, arbol: true });
  }
  for (const [x, z, w, d] of [[0, -13, 6, 1.4], [0, 13, 6, 1.4], [-13, 0, 1.4, 6], [13, 0, 1.4, 6]]) {
    canteros.push({ x, z, w, d, h: 0.45, arbol: false });
  }
  return canteros;
}

/** Árboles y faroles sobre las veredas, mirando a la calle. */
export function generarVeredaProps(semilla = 77) {
  const r = prng(semilla);
  const arboles = [];
  const faroles = [];
  const borde = L.BLOQUE / 2 - L.VEREDA_ANCHO / 2;   // eje de la vereda

  for (const bz of CENTROS_BLOQUE) {
    for (const bx of CENTROS_BLOQUE) {
      for (let i = -1; i <= 1; i++) {
        const t = i * 11;
        // Vereda norte/sur del bloque
        arboles.push({ x: bx + t, z: bz - borde, escala: entre(r, 0.85, 1.25) });
        arboles.push({ x: bx + t, z: bz + borde, escala: entre(r, 0.85, 1.25) });
        // Vereda este/oeste
        arboles.push({ x: bx - borde, z: bz + t, escala: entre(r, 0.85, 1.25) });
        arboles.push({ x: bx + borde, z: bz + t, escala: entre(r, 0.85, 1.25) });
      }
      // Un farol por esquina de manzana.
      for (const sx of [-1, 1]) {
        for (const sz of [-1, 1]) {
          faroles.push({ x: bx + sx * borde, z: bz + sz * borde });
        }
      }
    }
  }
  return { arboles, faroles };
}

/** Punto de aparición de Fran: centro de la plaza. */
export const SPAWN_JUGADOR = { x: 0, z: 4 };

/**
 * Puntos de aparición de enemigos dentro de la plaza.
 * Elegidos en los huecos entre canteros: un enemigo que nace dentro de un
 * collider sale expulsado en el primer frame y se le nota. `Enemigo` igual
 * corre `resolver()` al nacer como red de seguridad.
 */
export const SPAWNS_ENEMIGOS = [
  { x: 0,    z: -10 },
  { x: -5.5, z: -12 },
  { x: 5.5,  z: -12 },
  { x: -11,  z: -4 },
  { x: 11,   z: -4 },
];
