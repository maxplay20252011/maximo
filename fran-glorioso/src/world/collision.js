/**
 * FRAN GLORIOSO — Colisión del mundo.
 *
 * AABB en XZ contra círculo (el radio de la cápsula del personaje). Alcanza de
 * sobra: el vertical slice es plano, y resolver por el eje de menor penetración
 * da deslizamiento sobre paredes sin engancharse en las esquinas.
 */

import { L } from './layout.js';

export class MundoColisiones {
  constructor() {
    /** @type {Array<{minX:number,maxX:number,minZ:number,maxZ:number}>} */
    this.cajas = [];
    const mitad = L.MUNDO / 2 - 1.5;
    this.limite = { min: -mitad, max: mitad };
  }

  agregarCaja(x, z, w, d, margen = 0) {
    this.cajas.push({
      minX: x - w / 2 - margen, maxX: x + w / 2 + margen,
      minZ: z - d / 2 - margen, maxZ: z + d / 2 + margen,
    });
  }

  /**
   * Empuja la posición fuera de todo collider y del borde del mundo.
   * Muta `pos` (THREE.Vector3) en el lugar.
   */
  resolver(pos, radio) {
    for (const c of this.cajas) {
      const minX = c.minX - radio, maxX = c.maxX + radio;
      const minZ = c.minZ - radio, maxZ = c.maxZ + radio;
      if (pos.x <= minX || pos.x >= maxX || pos.z <= minZ || pos.z >= maxZ) continue;

      // Dentro: salir por la cara más cercana.
      const dIzq = pos.x - minX, dDer = maxX - pos.x;
      const dAtras = pos.z - minZ, dAdel = maxZ - pos.z;
      const min = Math.min(dIzq, dDer, dAtras, dAdel);

      if (min === dIzq)        pos.x = minX;
      else if (min === dDer)   pos.x = maxX;
      else if (min === dAtras) pos.z = minZ;
      else                     pos.z = maxZ;
    }

    pos.x = Math.min(this.limite.max, Math.max(this.limite.min, pos.x));
    pos.z = Math.min(this.limite.max, Math.max(this.limite.min, pos.z));
  }

  /** ¿Hay pared entre a y b? Raycast XZ barato, para que el enemigo no cargue contra un edificio. */
  hayObstaculo(a, b) {
    const pasos = 8;
    for (let i = 1; i < pasos; i++) {
      const t = i / pasos;
      const x = a.x + (b.x - a.x) * t;
      const z = a.z + (b.z - a.z) * t;
      for (const c of this.cajas) {
        if (x > c.minX && x < c.maxX && z > c.minZ && z < c.maxZ) return true;
      }
    }
    return false;
  }
}
