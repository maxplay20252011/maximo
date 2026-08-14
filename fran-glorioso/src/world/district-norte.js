/**
 * FRAN GLORIOSO — Armado del Barrio Norte (el distrito del vertical slice).
 *
 * Checklist §11 que se resuelve acá:
 *  · el suelo recibe sombra (`receiveShadow = true`)
 *  · los edificios y props la proyectan (`castShadow = true`)
 *  · ninguna textura viene de archivo → cero 404, cero warnings
 */

import * as THREE from 'three';
import { L, CENTROS_BLOQUE, generarEdificios, generarPlaza, generarVeredaProps } from './layout.js';
import { MundoColisiones } from './collision.js';
import { crearEdificios } from './buildings.js';
import { crearArboles, crearFaroles, crearCanteros } from './props.js';
import { materialAsfalto, materialVereda } from '../render/materials.js';

const dummy = new THREE.Object3D();

export function construirBarrioNorte(scene) {
  const colisiones = new MundoColisiones();
  const raiz = new THREE.Group();
  raiz.name = 'barrio-norte';

  /* ── Calzada: un único plano de asfalto bajo todo el barrio ───────────── */
  const geoSuelo = new THREE.PlaneGeometry(L.MUNDO + 10, L.MUNDO + 10);
  const suelo = new THREE.Mesh(geoSuelo, materialAsfalto(L.MUNDO + 10, L.MUNDO + 10));
  suelo.rotation.x = -Math.PI / 2;
  suelo.receiveShadow = true;                 // §11: el suelo recibe sombra
  suelo.name = 'calzada';
  raiz.add(suelo);

  /* ── Veredas: una plataforma por manzana, las 9 en un solo InstancedMesh ─ */
  const geoVereda = new THREE.BoxGeometry(1, 1, 1);
  const bloques = CENTROS_BLOQUE.length ** 2;
  const veredas = new THREE.InstancedMesh(geoVereda, materialVereda(L.BLOQUE, L.BLOQUE), bloques);
  veredas.receiveShadow = true;
  veredas.castShadow = false;                 // 15 cm de altura: la sombra no aporta
  veredas.name = 'veredas';

  let i = 0;
  for (const bz of CENTROS_BLOQUE) {
    for (const bx of CENTROS_BLOQUE) {
      dummy.position.set(bx, L.VEREDA_ALTO / 2, bz);
      dummy.rotation.set(0, 0, 0);
      dummy.scale.set(L.BLOQUE, L.VEREDA_ALTO, L.BLOQUE);
      dummy.updateMatrix();
      veredas.setMatrixAt(i++, dummy.matrix);
    }
  }
  veredas.instanceMatrix.needsUpdate = true;
  raiz.add(veredas);

  scene.add(raiz);

  /* ── Edificios y props ────────────────────────────────────────────────── */
  const edificios = generarEdificios();
  crearEdificios(scene, edificios, colisiones);

  const { arboles, faroles } = generarVeredaProps();
  crearArboles(scene, arboles);
  crearFaroles(scene, faroles);
  crearCanteros(scene, generarPlaza(), colisiones);

  return { raiz, colisiones, edificios };
}
