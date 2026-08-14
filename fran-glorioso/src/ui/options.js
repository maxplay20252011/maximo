/**
 * FRAN GLORIOSO — Menú de opciones.
 * Especificación Visual Técnica §10.
 *
 * `antialias` es la única opción que no se puede cambiar en caliente: se fija
 * al crear el contexto WebGL. En vez de recrear el renderer (y perder shadow
 * maps, texturas y estado), se guarda la preferencia y se avisa que aplica al
 * recargar. El resto —sombras, pixel ratio, fog, distancia, partículas— cambia
 * en el acto.
 */

import { NIVELES, preset, guardarNivel, esMobile } from '../config/quality.js';

export class MenuOpciones {
  /**
   * @param {string} nivelActual
   * @param {(nivel:string)=>void} alCambiar
   */
  constructor(nivelActual, alCambiar) {
    this.nivelArranque = nivelActual;
    this.nivel = nivelActual;
    this.alCambiar = alCambiar;

    this.panel = document.getElementById('opciones');
    this.nota = document.getElementById('nota-calidad');
    this.botones = [...document.querySelectorAll('#calidad button')];

    for (const b of this.botones) {
      b.addEventListener('click', () => this.seleccionar(b.dataset.nivel));
    }
    document.getElementById('cerrar-opciones').addEventListener('click', () => this.cerrar());
    document.getElementById('engranaje').addEventListener('click', () => this.alternar());
    this.panel.addEventListener('click', (e) => { if (e.target === this.panel) this.cerrar(); });

    this.pintar();
  }

  seleccionar(nivel) {
    if (!NIVELES.includes(nivel) || nivel === this.nivel) return;
    this.nivel = nivel;
    guardarNivel(nivel);
    this.alCambiar(nivel);
    this.pintar();
  }

  pintar() {
    for (const b of this.botones) {
      b.setAttribute('aria-pressed', String(b.dataset.nivel === this.nivel));
    }

    const q = preset(this.nivel);
    const partes = [
      q.sombras ? `sombras ${q.shadowMapSize}px` : 'sin sombras',
      `render ${q.distanciaRender} m`,
      `pixel ratio ${q.pixelRatio}`,
      `partículas ×${q.particulas}`,
    ];

    const cambioAA = preset(this.nivelArranque).antialias !== q.antialias;
    this.nota.textContent = partes.join(' · ')
      + (cambioAA ? ' — el antialiasing se aplica al recargar.' : '')
      + (esMobile() && this.nivel === 'alta' ? ' Alta puede no llegar a 30 FPS en mobile.' : '');
  }

  abrir()   { this.panel.classList.add('abierto'); }
  cerrar()  { this.panel.classList.remove('abierto'); }
  alternar(){ this.panel.classList.toggle('abierto'); }
  get abierto() { return this.panel.classList.contains('abierto'); }
}
