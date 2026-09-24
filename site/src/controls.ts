import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { startViewDistance } from './layout'
import { BLEND, type TourPlan } from './tour'

// 相机系统：环绕观察（默认）+ 螺旋上升漫游动画（轨道与排期见 tour.ts）
export type CameraMode = 'orbit' | 'tour'

const WORLD_UP = new THREE.Vector3(0, 1, 0)

export class CameraRig {
  mode: CameraMode = 'orbit'
  /** 漫游时钟（秒）：orbit 模式下无意义 */
  tourT = 0
  controls: OrbitControls
  onEraChange?: (era: number) => void
  onTourEnd?: () => void

  private camera: THREE.PerspectiveCamera
  private plan: TourPlan
  private eraRadii: number[]
  private towerHeight: number
  private lastEra = -1
  private startPos = new THREE.Vector3()
  private startTarget = new THREE.Vector3()
  private lookTarget = new THREE.Vector3()
  private pos = new THREE.Vector3()
  private up = new THREE.Vector3(0, 1, 0)

  constructor(
    camera: THREE.PerspectiveCamera, dom: HTMLElement,
    eraRadii: number[], towerHeight: number, plan: TourPlan
  ) {
    this.camera = camera
    this.plan = plan
    this.eraRadii = eraRadii
    this.towerHeight = towerHeight

    this.controls = new OrbitControls(camera, dom)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.06
    this.controls.autoRotate = true
    this.controls.autoRotateSpeed = 0.35
    this.controls.maxDistance = 950
    this.controls.minDistance = 6
    this.controls.target.set(0, this.towerHeight * 0.5, 0)

    // 用户一旦交互就停掉自动旋转
    this.controls.addEventListener('start', () => { this.controls.autoRotate = false })

    // ESC 中断漫游
    window.addEventListener('keydown', e => {
      if (e.key === 'Escape' && this.mode === 'tour') this.stopTour()
    })
    // 点击画布中断漫游
    dom.addEventListener('pointerdown', () => {
      if (this.mode === 'tour') this.stopTour()
    })
  }

  resetView() {
    this.stopTour()
    this.controls.target.set(0, this.towerHeight * 0.5, 0)
    const d = startViewDistance(this.eraRadii, this.towerHeight) / Math.SQRT2
    this.camera.position.set(d, this.towerHeight * 0.68, d)
    this.controls.autoRotate = true
    this.controls.update()
  }

  startTour() {
    if (this.mode === 'tour') return
    this.mode = 'tour'
    this.tourT = 0
    this.lastEra = -1
    this.plan.reset()
    this.startPos.copy(this.camera.position)
    this.startTarget.copy(this.controls.target)
    this.controls.enabled = false
  }

  stopTour() {
    if (this.mode !== 'tour') return
    this.mode = 'orbit'
    this.controls.enabled = true
    // 漫游把 up 改成了水平向量（视线朝上时必需），环绕模式要交还世界竖直
    this.camera.up.copy(WORLD_UP)
    this.controls.target.copy(this.lookTarget.lengthSq() > 0 ? this.lookTarget : new THREE.Vector3(0, this.camera.position.y, 0))
    this.controls.update()
    this.onTourEnd?.()
  }

  update(dt: number) {
    if (this.mode === 'orbit') {
      this.controls.update()
      return
    }

    this.tourT += dt
    if (this.tourT >= this.plan.total) {
      this.applyTourPose(this.plan.total)
      this.stopTour()
      return
    }
    this.applyTourPose(this.tourT)
  }

  private applyTourPose(t: number) {
    this.plan.poseAt(t, this.pos, this.lookTarget)
    this.plan.upAt(t, this.up)

    // 开场从当前位姿融入中轴线起点
    if (t < BLEND) {
      const k = t / BLEND
      const s = k * k * (3 - 2 * k) // smoothstep
      this.pos.lerpVectors(this.startPos, this.pos, s)
      this.lookTarget.lerpVectors(this.startTarget, this.lookTarget, s)
      this.up.lerpVectors(WORLD_UP, this.up, s)
    }

    this.camera.position.copy(this.pos)
    this.camera.up.copy(this.up)
    this.camera.lookAt(this.lookTarget)

    const era = this.plan.eraOf(t)
    if (era !== this.lastEra) {
      this.lastEra = era
      this.onEraChange?.(era)
    }
  }
}
