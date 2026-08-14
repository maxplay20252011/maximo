/**
 * FRAN GLORIOSO — VFX de combate.
 * Especificación Visual Técnica §7. Sin sangre: decisión ya tomada, el tono va
 * acorde a la edad del protagonista.
 *
 * Duraciones exactas de la spec:
 *   impacto  0.15 s (flash del material 0.1 s)
 *   muerte   0.60 s (tinte blanco 0.1 s, después disolución)
 *   esquive  0.20 s de i-frames con estela y tinte azulado
 *   polvo    0.40 s
 */

import * as THREE from 'three';
import { VFX, RAREZA_HEX, OUTLINE_COLOR } from '../config/palette.js';

const _v = new THREE.Vector3();

export class VFXCombate {
  /**
   * @param {THREE.Scene} scene
   * @param {import('./particles.js').SistemaParticulas} particulas
   */
  constructor(scene, particulas) {
    this.scene = scene;
    this.particulas = particulas;
    /** @type {Array<{t:number,dur:number,paso:Function,fin?:Function}>} */
    this.activos = [];
    this.fantasmas = [];    // pool de copias fantasma del esquive
  }

  agregar(dur, paso, fin) {
    const efecto = { t: 0, dur, paso, fin };
    this.activos.push(efecto);
    return efecto;
  }

  update(dt) {
    for (let i = this.activos.length - 1; i >= 0; i--) {
      const e = this.activos[i];
      e.t += dt;
      const k = Math.min(1, e.t / e.dur);
      e.paso(k, dt);
      if (e.t >= e.dur) {
        e.fin?.();
        this.activos.splice(i, 1);
      }
    }

    for (let i = this.fantasmas.length - 1; i >= 0; i--) {
      const f = this.fantasmas[i];
      f.t += dt;
      const k = f.t / f.dur;
      if (k >= 1) {
        f.mesh.visible = false;
        this.fantasmas.splice(i, 1);
        continue;
      }
      f.mesh.material.opacity = f.opacidad * (1 - k);
    }
  }

  /* ── Impacto de golpe en enemigo ──────────────────────────────────────── */

  /**
   * Destello blanco breve + partículas del color de rareza del arma.
   * @param {THREE.Vector3} punto  dónde pegó el golpe
   * @param {Object} cuerpo        cuerpo devuelto por loadCharacterModel
   * @param {string|null} rareza   clave de RAREZA_HEX; null = mano limpia (blanco)
   */
  impacto(punto, cuerpo, rareza = null) {
    const color = rareza ? (RAREZA_HEX[rareza] ?? VFX.flashImpacto) : VFX.flashImpacto;

    // 8-12 sprites pequeños, dispersión radial, gravedad leve.
    this.particulas.emitir({
      origen: punto,
      cantidad: 8 + Math.floor(Math.random() * 5),
      color,
      velocidad: 4.5,
      gravedad: 3.5,          // leve
      vida: 0.15,
      tamano: 0.085,
      dispersion: 0.12,
    });

    if (cuerpo) this.flash(cuerpo);
  }

  /** Flash del material del enemigo: emissive blanco 0.8 durante 0.1 s, luego a 0. */
  flash(cuerpo) {
    const mat = cuerpo.material;
    if (mat.userData.flasheando) return;
    mat.userData.flasheando = true;

    mat.emissive.setHex(VFX.flashImpacto);
    mat.emissiveIntensity = 0.8;

    this.agregar(0.1, () => {}, () => {
      // No pisar el tinte de esquive si arrancó mientras tanto.
      if (!mat.userData.tintado) {
        mat.emissiveIntensity = 0;
        mat.emissive.setHex(0x000000);
      }
      mat.userData.flasheando = false;
    });
  }

  /* ── Muerte de enemigo: disolución, no ragdoll ────────────────────────── */

  /**
   * 0.6 s totales: 0.1 s de tinte blanco, después escala 1→0 con easing y
   * opacity 1→0, más 20-25 partículas ascendentes del color base del enemigo.
   * @param {Object} cuerpo
   * @param {number} colorBase
   * @param {Function} alTerminar  se llama para removerlo de la escena
   */
  muerte(cuerpo, colorBase, alTerminar) {
    const { root, mesh, material, outline } = cuerpo;
    const TINTE = 0.1;
    const TOTAL = 0.6;

    material.userData.tintado = true;
    material.emissive.setHex(VFX.flashImpacto);
    material.emissiveIntensity = 1.0;
    material.transparent = true;
    material.depthWrite = false;

    // El outline comparte material entre entidades: para poder desvanecerlo sin
    // afectar a los demás, esta entidad se queda con una copia propia.
    const outlinePropio = new THREE.MeshBasicMaterial({
      color: OUTLINE_COLOR, side: THREE.BackSide, transparent: true, depthWrite: false,
    });
    if (outline) outline.material = outlinePropio;

    let emitido = false;

    this.agregar(TOTAL, (k) => {
      if (k * TOTAL <= TINTE) return;                 // fase 1: sólo el tinte blanco

      if (!emitido) {
        emitido = true;
        mesh.getWorldPosition(_v);
        this.particulas.emitir({
          origen: _v,
          cantidad: 20 + Math.floor(Math.random() * 6),   // 20-25
          color: colorBase,
          velocidad: 2.6,
          gravedad: -1.4,                                  // ascendentes
          vida: 0.5,
          tamano: 0.1,
          dispersion: 0.28,
          direccion: new THREE.Vector3(0, 1, 0),
          radial: 0.55,
        });
      }

      // Reescalar k al tramo de disolución y suavizar (easeInCubic).
      const d = (k * TOTAL - TINTE) / (TOTAL - TINTE);
      const e = 1 - d * d * d;
      root.scale.setScalar(Math.max(0.0001, e));
      material.opacity = e;
      material.emissiveIntensity = 1.0 * (1 - d);
      // El contorno se apaga más rápido que el cuerpo: es BackSide, así que en
      // cuanto el cuerpo se vuelve translúcido se ve su cara interna y el
      // enemigo se pondría negro en vez de desvanecerse.
      outlinePropio.opacity = e * e;
    }, () => {
      outlinePropio.dispose();
      alTerminar?.();
    });
  }

  /* ── Esquive (roll) con i-frames ──────────────────────────────────────── */

  /**
   * Feedback visual OBLIGATORIO: el jugador tiene que saber cuándo fue invulnerable.
   * Tinte azulado #7DB8FF con emissiveIntensity 0.4 + 3-4 copias fantasma.
   * @param {Object} cuerpo
   * @param {number} duracion  duración de los i-frames (0.2 s por spec)
   */
  esquive(cuerpo, duracion = 0.2) {
    const mat = cuerpo.material;
    mat.userData.tintado = true;
    mat.emissive.setHex(VFX.tinteEsquive);
    mat.emissiveIntensity = 0.4;

    // Una copia cada ~1/4 de los i-frames: las más viejas ya se desvanecieron,
    // así el jugador ve la escalera de opacidades 0.3 / 0.2 / 0.1 de la spec.
    const paso = duracion / 4;
    let siguiente = 0;

    this.agregar(duracion, (k) => {
      const t = k * duracion;
      if (t >= siguiente) {
        siguiente += paso;
        this.fantasma(cuerpo);
      }
    }, () => {
      mat.userData.tintado = false;
      if (!mat.userData.flasheando) {
        mat.emissiveIntensity = 0;
        mat.emissive.setHex(0x000000);
      }
    });
  }

  /** Copia fantasma congelada en la pose actual (pool reutilizable). */
  fantasma(cuerpo) {
    let libre = null;
    for (const f of this.fantasmas) if (!f.mesh.visible) { libre = f; break; }

    if (!libre) {
      const mesh = new THREE.Mesh(cuerpo.mesh.geometry, new THREE.MeshBasicMaterial({
        color: cuerpo.material.color.getHex(),
        transparent: true,
        depthWrite: false,
      }));
      mesh.renderOrder = 1;
      this.scene.add(mesh);
      libre = { mesh, t: 0, dur: 0.25, opacidad: 0.3 };
    }

    cuerpo.mesh.getWorldPosition(libre.mesh.position);
    libre.mesh.quaternion.copy(cuerpo.root.quaternion);
    libre.mesh.material.opacity = 0.3;
    libre.mesh.visible = true;
    libre.t = 0;
    this.fantasmas.push(libre);
  }

  /* ── Polvo al correr / aterrizar ──────────────────────────────────────── */

  /** 5-8 partículas color tierra en los pies, expandiéndose durante 0.4 s. */
  polvo(posicionPies, color = VFX.polvoNorte) {
    this.particulas.emitirPolvo({
      origen: _v.copy(posicionPies).setY(posicionPies.y + 0.08),
      cantidad: 5 + Math.floor(Math.random() * 4),
      color,
      vida: 0.4,
      tamano: 0.11,
    });
  }
}
