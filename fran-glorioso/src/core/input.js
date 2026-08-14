/**
 * FRAN GLORIOSO — Entrada unificada: teclado + mouse + táctil.
 * Los controles táctiles y sus medidas viven en index.html (§8); acá sólo se
 * les da comportamiento.
 *
 * Regla de diseño: el resto del juego nunca pregunta "¿es mobile?". Lee
 * `mover`, `correr` y consume `esquive` / `ataque`, y le da igual de dónde
 * vinieron.
 */

import * as THREE from 'three';

const TECLAS_MOV = {
  KeyW: [0, 1], ArrowUp: [0, 1],
  KeyS: [0, -1], ArrowDown: [0, -1],
  KeyA: [-1, 0], ArrowLeft: [-1, 0],
  KeyD: [1, 0], ArrowRight: [1, 0],
};

export class Entrada {
  constructor(canvas) {
    this.canvas = canvas;
    this.mover = new THREE.Vector2();       // x = lateral, y = adelante
    this.correr = false;
    this.mirada = { x: 0, y: 0 };           // delta acumulado, se consume por frame

    this._teclas = new Set();
    this._esquive = false;
    this._ataque = false;
    this._joystick = { id: null, x: 0, y: 0 };
    this._camara = { id: null, x: 0, y: 0 };
    /** @type {Record<string, Function[]>} */
    this._atajos = {};

    this._bindTeclado();
    this._bindMouse();
    this._bindTactil();

    if (window.matchMedia?.('(pointer: coarse)').matches) {
      document.body.classList.add('tactil');
    }
  }

  /** Registra un atajo de teclado global (F, V, Escape…). */
  atajo(code, fn) {
    (this._atajos[code] ??= []).push(fn);
  }

  consumirEsquive() { const v = this._esquive; this._esquive = false; return v; }
  consumirAtaque()  { const v = this._ataque;  this._ataque  = false; return v; }

  /** Consume el delta de cámara acumulado desde el frame anterior. */
  consumirMirada() {
    const m = { x: this.mirada.x, y: this.mirada.y };
    this.mirada.x = 0;
    this.mirada.y = 0;
    return m;
  }

  /* ── Teclado ──────────────────────────────────────────────────────────── */
  _bindTeclado() {
    addEventListener('keydown', (e) => {
      if (e.repeat) {
        if (TECLAS_MOV[e.code]) e.preventDefault();
        return;
      }
      this._teclas.add(e.code);

      if (e.code === 'Space') { this._esquive = true; e.preventDefault(); }
      if (e.code === 'KeyJ') this._ataque = true;
      if (TECLAS_MOV[e.code]) e.preventDefault();

      for (const fn of this._atajos[e.code] ?? []) fn();
      this._recalcularMovimiento();
    });

    addEventListener('keyup', (e) => {
      this._teclas.delete(e.code);
      this._recalcularMovimiento();
    });

    // Si la pestaña pierde el foco, soltar todo: si no, el jugador queda corriendo solo.
    addEventListener('blur', () => {
      this._teclas.clear();
      this._recalcularMovimiento();
    });
  }

  _recalcularMovimiento() {
    if (this._joystick.id !== null) return;   // el joystick manda si está activo
    let x = 0, y = 0;
    for (const code of this._teclas) {
      const d = TECLAS_MOV[code];
      if (d) { x += d[0]; y += d[1]; }
    }
    this.mover.set(x, y);
    if (this.mover.lengthSq() > 1) this.mover.normalize();
    this.correr = this._teclas.has('ShiftLeft') || this._teclas.has('ShiftRight');
  }

  /* ── Mouse: arrastrar para girar la cámara, click para atacar ─────────── */
  _bindMouse() {
    this.canvas.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'touch') return;   // el táctil se maneja aparte
      if (e.button === 0) this._ataque = true;
      this._camara.id = e.pointerId;
      this._camara.x = e.clientX;
      this._camara.y = e.clientY;
      this.canvas.setPointerCapture(e.pointerId);
    });

    this.canvas.addEventListener('pointermove', (e) => {
      if (e.pointerId !== this._camara.id) return;
      this.mirada.x += e.clientX - this._camara.x;
      this.mirada.y += e.clientY - this._camara.y;
      this._camara.x = e.clientX;
      this._camara.y = e.clientY;
    });

    const soltar = (e) => {
      if (e.pointerId === this._camara.id) this._camara.id = null;
    };
    this.canvas.addEventListener('pointerup', soltar);
    this.canvas.addEventListener('pointercancel', soltar);
    this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  /* ── Táctil: joystick + botones ───────────────────────────────────────── */
  _bindTactil() {
    const base = document.getElementById('joystick');
    const stick = document.getElementById('stick');
    if (!base || !stick) return;

    const RADIO = 35;               // (120 - 50) / 2 según las medidas de §8
    const centrar = () => { stick.style.transform = 'translate(0px, 0px)'; };

    const mover = (e) => {
      const r = base.getBoundingClientRect();
      let dx = e.clientX - (r.left + r.width / 2);
      let dy = e.clientY - (r.top + r.height / 2);
      const dist = Math.hypot(dx, dy);
      if (dist > RADIO) { dx = (dx / dist) * RADIO; dy = (dy / dist) * RADIO; }
      stick.style.transform = `translate(${dx}px, ${dy}px)`;

      // Zona muerta del 18%: evita deriva con el pulgar apenas apoyado.
      const nx = dx / RADIO, ny = -dy / RADIO;
      const mag = Math.hypot(nx, ny);
      if (mag < 0.18) { this.mover.set(0, 0); this.correr = false; return; }
      this.mover.set(nx, ny);
      if (mag > 1) this.mover.normalize();
      this.correr = mag > 0.85;     // empujar a fondo el joystick = correr
    };

    base.addEventListener('pointerdown', (e) => {
      this._joystick.id = e.pointerId;
      base.setPointerCapture(e.pointerId);
      mover(e);
    });
    base.addEventListener('pointermove', (e) => {
      if (e.pointerId === this._joystick.id) mover(e);
    });
    const soltarJoystick = (e) => {
      if (e.pointerId !== this._joystick.id) return;
      this._joystick.id = null;
      this.mover.set(0, 0);
      this.correr = false;
      centrar();
      this._recalcularMovimiento();
    };
    base.addEventListener('pointerup', soltarJoystick);
    base.addEventListener('pointercancel', soltarJoystick);

    this._boton('btn-atacar', () => { this._ataque = true; });
    this._boton('btn-esquivar', () => { this._esquive = true; });
    this._boton('btn-correr',
      () => { this._correrTactil = true; this.correr = true; },
      () => { this._correrTactil = false; this.correr = false; });

    // Arrastrar sobre la mitad derecha (fuera de los botones) gira la cámara.
    this.canvas.addEventListener('pointerdown', (e) => {
      if (e.pointerType !== 'touch') return;
      this._camara.id = e.pointerId;
      this._camara.x = e.clientX;
      this._camara.y = e.clientY;
    });
    this.canvas.addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'touch' || e.pointerId !== this._camara.id) return;
      this.mirada.x += e.clientX - this._camara.x;
      this.mirada.y += e.clientY - this._camara.y;
      this._camara.x = e.clientX;
      this._camara.y = e.clientY;
    });
  }

  _boton(id, alPresionar, alSoltar) {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      el.classList.add('activo');       // §8: opacity .6 → .9 al presionar
      el.setPointerCapture(e.pointerId);
      alPresionar?.();
    });
    const soltar = (e) => {
      e.preventDefault();
      el.classList.remove('activo');
      alSoltar?.();
    };
    el.addEventListener('pointerup', soltar);
    el.addEventListener('pointercancel', soltar);
  }
}
