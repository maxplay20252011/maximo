/**
 * FRAN GLORIOSO — HUD.
 * Especificación Visual Técnica §8. Los colores y medidas están en el CSS de
 * index.html; este módulo sólo mueve las barras y los números.
 *
 * El HUD es DOM y no canvas a propósito: texto nítido en cualquier densidad de
 * pantalla, cero draw calls contra el presupuesto de §9.
 */

import * as THREE from 'three';

const _v = new THREE.Vector3();

export class HUD {
  constructor() {
    this.el = {
      vida: document.querySelector('#vida .relleno'),
      vidaFantasma: document.querySelector('#vida .fantasma'),
      escudo: document.querySelector('#escudo .relleno'),
      escudoFantasma: document.querySelector('#escudo .fantasma'),
      stamina: document.querySelector('#stamina .relleno'),
      cifraVida: document.getElementById('cifra-vida'),
      enemigos: document.getElementById('cuenta-enemigos'),
      capaDanio: document.getElementById('capa-danio'),
      arma: document.getElementById('arma'),
    };
    this.flotantes = [];
    this.pool = [];
  }

  _barra(relleno, fantasma, valor, max) {
    const k = max > 0 ? Math.max(0, Math.min(1, valor / max)) : 0;
    relleno.style.transform = `scaleX(${k})`;
    if (fantasma) fantasma.style.transform = `scaleX(${k})`;
  }

  setVida(v, max) {
    this._barra(this.el.vida, this.el.vidaFantasma, v, max);
    this.el.cifraVida.textContent = `${Math.ceil(v)}/${max}`;
  }

  setEscudo(v, max) { this._barra(this.el.escudo, this.el.escudoFantasma, v, max); }
  setStamina(v, max) { this._barra(this.el.stamina, null, v, max); }
  setEnemigos(n) { this.el.enemigos.textContent = String(n); }

  /** §8: el borde del ícono toma el color de rareza del arma equipada. */
  setArma(nombre, rareza, glifo = '✊') {
    const etiquetas = {
      comun: 'Común', pocoComun: 'Poco común', rara: 'Rara',
      epica: 'Épica', legendaria: 'Legendaria', mitica: 'Mítica',
    };
    this.el.arma.dataset.rareza = rareza;
    this.el.arma.querySelector('.icono').textContent = glifo;
    this.el.arma.querySelector('.nombre').textContent = nombre;
    this.el.arma.querySelector('.rareza').textContent = etiquetas[rareza] ?? rareza;
  }

  /**
   * Número de daño flotante, proyectado desde el mundo.
   * Tipografía condensada por §8; el color lo pone la clase CSS.
   */
  numeroDanio(posicionMundo, camera, valor, { critico = false, recibido = false } = {}) {
    const el = this.pool.pop() ?? document.createElement('div');
    el.className = 'danio txt'
      + (critico ? ' critico' : '')
      + (recibido ? ' recibido' : '');
    el.textContent = recibido ? `−${valor}` : String(valor);
    el.style.opacity = '1';
    this.el.capaDanio.appendChild(el);

    this.flotantes.push({
      el,
      pos: posicionMundo.clone(),
      t: 0,
      dur: 0.9,
      deriva: (Math.random() - 0.5) * 44,
    });
  }

  update(dt, camera) {
    const w = window.innerWidth;
    const h = window.innerHeight;

    for (let i = this.flotantes.length - 1; i >= 0; i--) {
      const f = this.flotantes[i];
      f.t += dt;
      const k = f.t / f.dur;

      if (k >= 1) {
        f.el.remove();
        this.pool.push(f.el);
        this.flotantes.splice(i, 1);
        continue;
      }

      _v.copy(f.pos).project(camera);
      if (_v.z > 1) { f.el.style.opacity = '0'; continue; }   // detrás de la cámara

      const x = (_v.x * 0.5 + 0.5) * w + f.deriva * k;
      const y = (-_v.y * 0.5 + 0.5) * h - 70 * Math.sqrt(k);  // sube desacelerando
      const escala = critico(f) ? 1 + 0.25 * (1 - k) : 1;

      f.el.style.transform = `translate(${x}px, ${y}px) scale(${escala})`;
      f.el.style.opacity = String(Math.min(1, 2.2 * (1 - k)));
    }
  }
}

function critico(f) { return f.el.classList.contains('critico'); }
