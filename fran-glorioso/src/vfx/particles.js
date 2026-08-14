/**
 * FRAN GLORIOSO — Sistema de partículas.
 * Soporte de §7 (VFX de combate) dentro del presupuesto de §9.
 *
 * Un único THREE.Points con pool fijo = 1 draw call para TODAS las partículas
 * del juego. Las partículas muertas se apagan poniendo su tamaño en 0 (el
 * rasterizador las descarta), así nunca hay realloc ni resort del buffer.
 *
 * El shader es propio y dibuja un disco por punto: no hay textura de sprite, y
 * por lo tanto tampoco hay 404 ni warning de textura faltante (§11).
 */

import * as THREE from 'three';

const VERT = /* glsl */`
  attribute vec3 aColor;
  attribute float aSize;
  attribute float aAlpha;
  uniform float uEscala;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = min(aSize * uEscala / max(-mv.z, 0.001), 64.0);
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAG = /* glsl */`
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = dot(c, c);
    if (d > 0.25) discard;
    float a = vAlpha * smoothstep(0.25, 0.06, d);
    if (a <= 0.001) discard;
    gl_FragColor = vec4(vColor, a);
    #include <colorspace_fragment>
  }
`;

const _color = new THREE.Color();

export class SistemaParticulas {
  /**
   * @param {THREE.Scene} scene
   * @param {number} max            tamaño del pool
   * @param {number} multiplicador  §10 `particulas`: 0.5 / 1.0 / 1.5
   */
  constructor(scene, max = 700, multiplicador = 1) {
    this.max = max;
    this.multiplicador = multiplicador;
    this.cursor = 0;

    this.pos = new Float32Array(max * 3);
    this.col = new Float32Array(max * 3);
    this.size = new Float32Array(max);
    this.alpha = new Float32Array(max);

    this.vel = new Float32Array(max * 3);
    this.vida = new Float32Array(max);
    this.vidaMax = new Float32Array(max);
    this.gravedad = new Float32Array(max);
    this.size0 = new Float32Array(max);
    this.expansion = new Float32Array(max);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    geo.setAttribute('aColor', new THREE.BufferAttribute(this.col, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(this.size, 1));
    geo.setAttribute('aAlpha', new THREE.BufferAttribute(this.alpha, 1));
    // El pool cubre todo el barrio: sin bounding sphere fija, three lo cullea mal.
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 200);

    this.material = new THREE.ShaderMaterial({
      uniforms: { uEscala: { value: 500 } },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
    });

    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
    this.points.name = 'particulas';
    this.points.renderOrder = 2;
    scene.add(this.points);
    this.geo = geo;
  }

  /** Convierte "tamaño en metros" a píxeles para el vertex shader. */
  ajustarEscala(camera, alturaPx) {
    const fov = THREE.MathUtils.degToRad(camera.fov);
    this.material.uniforms.uEscala.value = alturaPx / (2 * Math.tan(fov / 2));
  }

  /**
   * @param {Object} o
   * @param {THREE.Vector3} o.origen
   * @param {number} o.cantidad      antes de aplicar el multiplicador de calidad
   * @param {number} o.color         hex
   * @param {number} [o.velocidad]   magnitud base del impulso (m/s)
   * @param {number} [o.gravedad]    m/s² (positivo = cae)
   * @param {number} [o.vida]        segundos
   * @param {number} [o.tamano]      metros
   * @param {number} [o.dispersion]  radio de emisión alrededor del origen
   * @param {THREE.Vector3} [o.direccion] sesgo direccional (p. ej. hacia arriba)
   * @param {number} [o.radial]      0 = usa `direccion`, 1 = totalmente radial
   */
  emitir({
    origen, cantidad, color, velocidad = 3, gravedad = 6, vida = 0.4,
    tamano = 0.09, dispersion = 0.15, direccion = null, radial = 1,
  }) {
    const n = Math.max(1, Math.round(cantidad * this.multiplicador));
    _color.set(color).convertSRGBToLinear();   // el shader escribe en espacio lineal

    for (let i = 0; i < n; i++) {
      const p = this.cursor;
      this.cursor = (this.cursor + 1) % this.max;
      const p3 = p * 3;

      this.pos[p3]     = origen.x + (Math.random() - 0.5) * dispersion * 2;
      this.pos[p3 + 1] = origen.y + (Math.random() - 0.5) * dispersion * 2;
      this.pos[p3 + 2] = origen.z + (Math.random() - 0.5) * dispersion * 2;

      // Dirección radial uniforme sobre la esfera.
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      let dx = Math.sin(phi) * Math.cos(theta);
      let dy = Math.cos(phi);
      let dz = Math.sin(phi) * Math.sin(theta);

      if (direccion) {
        dx = dx * radial + direccion.x * (1 - radial);
        dy = dy * radial + direccion.y * (1 - radial);
        dz = dz * radial + direccion.z * (1 - radial);
      }

      const v = velocidad * (0.6 + Math.random() * 0.8);
      this.vel[p3]     = dx * v;
      this.vel[p3 + 1] = dy * v;
      this.vel[p3 + 2] = dz * v;

      this.col[p3]     = _color.r;
      this.col[p3 + 1] = _color.g;
      this.col[p3 + 2] = _color.b;

      const t = tamano * (0.7 + Math.random() * 0.6);
      this.size[p] = t;
      this.size0[p] = t;
      this.alpha[p] = 1;
      this.vidaMax[p] = vida * (0.8 + Math.random() * 0.4);
      this.vida[p] = this.vidaMax[p];
      this.gravedad[p] = gravedad;
      this.expansion[p] = 0;
    }
  }

  /** Variante para el polvo (§7): crece y se desvanece en vez de caer. */
  emitirPolvo({ origen, cantidad, color, vida = 0.4, tamano = 0.12 }) {
    const antes = this.cursor;
    this.emitir({
      origen, cantidad, color, vida, tamano,
      velocidad: 1.2, gravedad: -0.6, dispersion: 0.2,
      direccion: new THREE.Vector3(0, 0.35, 0), radial: 0.75,
    });
    // Marca las recién emitidas para que se expandan.
    const n = Math.max(1, Math.round(cantidad * this.multiplicador));
    for (let i = 0; i < n; i++) {
      this.expansion[(antes + i) % this.max] = 1.8;
    }
  }

  update(dt) {
    const { pos, vel, vida, vidaMax, size, size0, alpha, gravedad, expansion } = this;
    for (let p = 0; p < this.max; p++) {
      if (vida[p] <= 0) continue;

      vida[p] -= dt;
      if (vida[p] <= 0) {
        size[p] = 0;
        alpha[p] = 0;
        continue;
      }

      const p3 = p * 3;
      vel[p3 + 1] -= gravedad[p] * dt;
      pos[p3]     += vel[p3] * dt;
      pos[p3 + 1] += vel[p3 + 1] * dt;
      pos[p3 + 2] += vel[p3 + 2] * dt;

      if (pos[p3 + 1] < 0.02) {              // no atravesar el piso
        pos[p3 + 1] = 0.02;
        vel[p3 + 1] *= -0.25;
      }

      const t = vida[p] / vidaMax[p];        // 1 → 0
      alpha[p] = t * t;                      // fade cuadrático: se apaga rápido al final
      size[p] = size0[p] * (1 + expansion[p] * (1 - t));
    }

    this.geo.attributes.position.needsUpdate = true;
    this.geo.attributes.aColor.needsUpdate = true;
    this.geo.attributes.aSize.needsUpdate = true;
    this.geo.attributes.aAlpha.needsUpdate = true;
  }

  setMultiplicador(m) { this.multiplicador = m; }

  /** Partículas vivas — para el overlay de debug. */
  get vivas() {
    let n = 0;
    for (let p = 0; p < this.max; p++) if (this.vida[p] > 0) n++;
    return n;
  }
}
