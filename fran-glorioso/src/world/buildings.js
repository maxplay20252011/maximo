/**
 * FRAN GLORIOSO — Edificios del Barrio Norte.
 * Especificación Visual Técnica §3 (paleta), §4 (materiales), §9 (instancing + LOD).
 *
 * Dos caminos, los dos exigidos por §9:
 *  · El grueso del barrio va en InstancedMesh → 4 draw calls para 28 edificios.
 *  · Los 4 edificios que dan a la plaza son THREE.LOD con 3 niveles: son los
 *    únicos que el jugador ve de cerca, así que se pagan detalle sólo ahí.
 *
 * Los edificios NO llevan outline (§5): el contorno marca lo interactivo.
 */

import * as THREE from 'three';
import { NORTE } from '../config/palette.js';
import { materialEdificio, materialMate, materialFachadaTexturada } from '../render/materials.js';

const dummy = new THREE.Object3D();

/**
 * Rejilla de ventanas de una fachada.
 * @param {number} largo  ancho de la cara (w para las caras ±Z, d para las ±X)
 * @param {number} h      altura del edificio
 * @returns {Array<{u:number, y:number}>} posiciones locales sobre la cara
 */
function ventanasDeCara(largo, h) {
  const puntos = [];
  const cols = Math.max(1, Math.floor(largo / 3.2));
  const filas = Math.max(1, Math.floor((h - 2.6) / 3.4));
  const pasoC = largo / (cols + 1);
  for (let c = 1; c <= cols; c++) {
    for (let f = 0; f < filas; f++) {
      puntos.push({ u: -largo / 2 + c * pasoC, y: 2.4 + f * 3.4 });
    }
  }
  return puntos;
}

function contarVentanas(edificios) {
  let n = 0;
  for (const e of edificios) {
    n += ventanasDeCara(e.w, e.h).length * 2;
    n += ventanasDeCara(e.d, e.h).length * 2;
  }
  return n;
}

/**
 * @param {THREE.Scene} scene
 * @param {Array} edificios  descriptores de layout.js
 * @param {import('./collision.js').MundoColisiones} colisiones
 */
export function crearEdificios(scene, edificios, colisiones) {
  const grupo = new THREE.Group();
  grupo.name = 'edificios';

  const normales = edificios.filter((e) => !e.landmark);
  const landmarks = edificios.filter((e) => e.landmark);

  // Todos los edificios (instanciados o LOD) aportan collider.
  for (const e of edificios) colisiones.agregarCaja(e.x, e.z, e.w, e.d);

  /* ── Cuerpos ────────────────────────────────────────────────────────────
   * Un solo material blanco + instanceColor: la variación entre fachada
   * principal (#F5F5F0) y secundaria (#D8D8D2) sale por instancia, sin
   * multiplicar materiales (§9: "compartir materiales").                    */
  const geoCuerpo = new THREE.BoxGeometry(1, 1, 1);
  const cuerpos = new THREE.InstancedMesh(geoCuerpo, materialEdificio(0xFFFFFF), normales.length);
  cuerpos.castShadow = true;
  cuerpos.receiveShadow = true;
  cuerpos.name = 'edificios:cuerpos';

  const cPrincipal = new THREE.Color(NORTE.fachadaPrincipal);
  const cSecundaria = new THREE.Color(NORTE.fachadaSecundaria);

  normales.forEach((e, i) => {
    dummy.position.set(e.x, e.h / 2, e.z);
    dummy.scale.set(e.w, e.h, e.d);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    cuerpos.setMatrixAt(i, dummy.matrix);
    cuerpos.setColorAt(i, e.secundaria ? cSecundaria : cPrincipal);
  });
  cuerpos.instanceMatrix.needsUpdate = true;
  if (cuerpos.instanceColor) cuerpos.instanceColor.needsUpdate = true;
  grupo.add(cuerpos);

  /* ── Techos: membrana asfáltica, apenas volada sobre la fachada ───────── */
  const techos = new THREE.InstancedMesh(geoCuerpo, materialMate(NORTE.techo), normales.length);
  techos.castShadow = true;
  techos.receiveShadow = true;
  techos.name = 'edificios:techos';
  normales.forEach((e, i) => {
    dummy.position.set(e.x, e.h + 0.25, e.z);
    dummy.scale.set(e.w + 0.5, 0.5, e.d + 0.5);
    dummy.updateMatrix();
    techos.setMatrixAt(i, dummy.matrix);
  });
  techos.instanceMatrix.needsUpdate = true;
  grupo.add(techos);

  /* ── Paneles de madera decorativos ───────────────────────────────────── */
  const conMadera = normales.filter((e) => e.madera);
  if (conMadera.length) {
    const madera = new THREE.InstancedMesh(geoCuerpo, materialMate(NORTE.detalleMadera), conMadera.length);
    madera.castShadow = true;
    madera.receiveShadow = true;
    madera.name = 'edificios:madera';
    conMadera.forEach((e, i) => {
      const alto = e.h * 0.45;
      dummy.position.set(e.x, alto / 2, e.z + e.d / 2 + 0.08);
      dummy.scale.set(e.w * 0.34, alto, 0.16);
      dummy.updateMatrix();
      madera.setMatrixAt(i, dummy.matrix);
    });
    madera.instanceMatrix.needsUpdate = true;
    grupo.add(madera);
  }

  /* ── Marcos de ventana: negros, en las cuatro caras ──────────────────── */
  const total = contarVentanas(normales);
  const marcos = new THREE.InstancedMesh(geoCuerpo, materialMate(NORTE.aberturas), total);
  marcos.castShadow = false;          // detalle plano: no vale el costo de sombra
  marcos.receiveShadow = true;
  marcos.name = 'edificios:ventanas';

  let k = 0;
  for (const e of normales) {
    for (const { u, y } of ventanasDeCara(e.w, e.h)) {
      for (const sz of [-1, 1]) {
        dummy.position.set(e.x + u, y, e.z + sz * (e.d / 2 + 0.06));
        dummy.scale.set(1.15, 1.55, 0.12);
        dummy.updateMatrix();
        marcos.setMatrixAt(k++, dummy.matrix);
      }
    }
    for (const { u, y } of ventanasDeCara(e.d, e.h)) {
      for (const sx of [-1, 1]) {
        dummy.position.set(e.x + sx * (e.w / 2 + 0.06), y, e.z + u);
        dummy.scale.set(0.12, 1.55, 1.15);
        dummy.updateMatrix();
        marcos.setMatrixAt(k++, dummy.matrix);
      }
    }
  }
  marcos.count = k;
  marcos.instanceMatrix.needsUpdate = true;
  grupo.add(marcos);

  /* ── Landmarks con LOD ───────────────────────────────────────────────── */
  for (const e of landmarks) grupo.add(crearLandmarkLOD(e));

  scene.add(grupo);
  return grupo;
}

/**
 * Edificio "héroe" con tres niveles de detalle (§9).
 *   0 m  → fachada texturada + cornisa + balcones + ventanas
 *   40 m → cuerpo + cornisa
 *   80 m → sólo el cuerpo
 */
export function crearLandmarkLOD(e) {
  const lod = new THREE.LOD();
  lod.position.set(e.x, 0, e.z);
  lod.name = 'landmark';

  const color = e.secundaria ? NORTE.fachadaSecundaria : NORTE.fachadaPrincipal;
  const geo = new THREE.BoxGeometry(1, 1, 1);

  const cuerpo = (mat) => {
    const m = new THREE.Mesh(geo, mat);
    m.position.y = e.h / 2;
    m.scale.set(e.w, e.h, e.d);
    m.castShadow = true;
    m.receiveShadow = true;
    return m;
  };

  const cornisa = () => {
    const m = new THREE.Mesh(geo, materialMate(NORTE.techo));
    m.position.y = e.h + 0.25;
    m.scale.set(e.w + 0.8, 0.5, e.d + 0.8);
    m.castShadow = true;
    m.receiveShadow = true;
    return m;
  };

  /* Nivel 0 — detallado */
  const detallado = new THREE.Group();
  detallado.add(cuerpo(materialFachadaTexturada(color, e.w, e.h)));
  detallado.add(cornisa());

  // Balcones sobre la cara que da a la plaza (la de +Z por convención de layout).
  const matMadera = materialMate(NORTE.detalleMadera);
  const matAbertura = materialMate(NORTE.aberturas);
  for (let piso = 1; piso <= 3; piso++) {
    const y = 2.4 + piso * 3.4;
    if (y > e.h - 1.5) break;

    const losa = new THREE.Mesh(geo, matMadera);
    losa.position.set(0, y - 0.85, e.d / 2 + 0.5);
    losa.scale.set(e.w * 0.55, 0.18, 1.0);
    losa.castShadow = true;
    losa.receiveShadow = true;
    detallado.add(losa);

    const baranda = new THREE.Mesh(geo, matAbertura);
    baranda.position.set(0, y - 0.35, e.d / 2 + 0.95);
    baranda.scale.set(e.w * 0.55, 0.9, 0.08);
    baranda.castShadow = true;
    detallado.add(baranda);
  }

  // Ventanas sólo en la cara visible: el resto no se ve desde la plaza.
  for (const { u, y } of ventanasDeCara(e.w, e.h)) {
    const v = new THREE.Mesh(geo, matAbertura);
    v.position.set(u, y, e.d / 2 + 0.06);
    v.scale.set(1.15, 1.55, 0.12);
    v.receiveShadow = true;
    detallado.add(v);
  }

  /* Nivel 1 — simple */
  const simple = new THREE.Group();
  simple.add(cuerpo(materialEdificio(color)));
  simple.add(cornisa());

  /* Nivel 2 — muy simple */
  const muySimple = new THREE.Group();
  muySimple.add(cuerpo(materialEdificio(color)));

  lod.addLevel(detallado, 0);
  lod.addLevel(simple, 40);
  lod.addLevel(muySimple, 80);
  return lod;
}
