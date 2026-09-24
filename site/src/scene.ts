import * as THREE from 'three'
import { CATEGORY_HEX } from './data'
import { startViewDistance } from './layout'

// 领域颜色（以 data/categories.json 为准，UI 图例与此一致）
export { CATEGORY_HEX }
export const CATEGORY_COLORS = CATEGORY_HEX.map(h => new THREE.Color(h))

export function createScene(towerHeight: number, eraRadii: number[] = []): {
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  renderer: THREE.WebGLRenderer
} {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x05070f)
  scene.fog = new THREE.Fog(0x05070f, 140, 860)

  const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 3000)
  const d = eraRadii.length ? startViewDistance(eraRadii, towerHeight) / Math.SQRT2 : 260
  camera.position.set(d, towerHeight * 0.68, d)

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(innerWidth, innerHeight)
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1
  renderer.outputColorSpace = THREE.SRGBColorSpace
  document.getElementById('app')!.appendChild(renderer.domElement)

  // 灯光
  scene.add(new THREE.AmbientLight(0x8899bb, 0.75))
  const sun = new THREE.DirectionalLight(0xffffff, 1.3)
  sun.position.set(90, 240, 70)
  scene.add(sun)
  const fill = new THREE.PointLight(0x4a7fff, 200, 600, 1.6)
  fill.position.set(0, 160, 0)
  scene.add(fill)

  // 星空背景
  const starCount = 4000
  const starPos = new Float32Array(starCount * 3)
  for (let i = 0; i < starCount; i++) {
    const r = 550 + Math.random() * 380
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
    starPos[i * 3 + 1] = r * Math.cos(phi)
    starPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
  }
  const starGeo = new THREE.BufferGeometry()
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3))
  const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    color: 0xbfd0ff, size: 1.4, sizeAttenuation: false,
    transparent: true, opacity: 0.8, fog: false
  }))
  scene.add(stars)

  // 底部极坐标网格（增强空间感）
  const grid = new THREE.PolarGridHelper(130, 16, 8, 72, 0x1c2a4a, 0x101a30)
  grid.position.y = -3
  ;(grid.material as THREE.Material).transparent = true
  ;(grid.material as THREE.Material).opacity = 0.5
  scene.add(grid)

  return { scene, camera, renderer }
}
