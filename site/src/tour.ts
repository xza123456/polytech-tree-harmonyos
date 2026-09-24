import * as THREE from 'three'
import { ERA_COUNT } from './data'
import { startViewDistance, type PlacedNode } from './layout'

// 漫游动画排期：摄像机沿中轴线自底部时代上升，视线全程朝上，各时代按科技数分配 10~30 秒。
export const FLASH = 0.5      // 多面体闪亮时长（秒）
export const NAME_LIFE = 2     // 科技名停留时长（秒）
export const BLEND = 2         // 开场由当前视角融入中轴线起点的时长（秒）
export const OUTRO = 5         // 末层之后拉出中轴线收尾的时长（秒）
const MIN_DUR = 10
const MAX_DUR = 30
const ROLL = 0.03              // 绕视轴的滚转角速度（弧度/秒 ≈ 1.7°/s，全片约 0.9 圈）
const LEAD = 130               // 摄像机领先正显现层的固定高度
const FOV_MARGIN = 1.1         // 圆盘外沿再留 10% 余量
const FOV_MIN = 45             // 小圆盘不收得过窄，否则透视 flattening 太厉害
const FOV_MAX = 125
const START_ANGLE = Math.PI * 0.25 // 与时代名/初始视角的方位一致
const NAME_FADE = 0.35         // 名称消失前的淡出时长

/**
 * 视场按"要看的圆盘"反推：俯视时半径 r 的盘面要落在画面内需 r ≤ LEAD·tan(fov/2)，
 * 故 fov = 2·atan(r ÷ LEAD)。传入的 r 用连续插值的塔身半径，随推进从本层滑向下一层，
 * 所以广角程度是渐变的，且小时代能收到 46° 左右（节点因此大 2 倍以上）。
 */
function fovFor(r: number): number {
  const deg = 2 * Math.atan(FOV_MARGIN * r / LEAD) * 180 / Math.PI
  return Math.min(FOV_MAX, Math.max(FOV_MIN, deg))
}

export interface EraWindow { start: number; dur: number; count: number }

function smoothstep(x: number): number {
  const t = Math.min(1, Math.max(0, x))
  return t * t * (3 - 2 * t)
}

// poseAt / upAt 每帧复用的暂存向量
const _dir = new THREE.Vector3()
const _look = new THREE.Vector3()
const _upY = new THREE.Vector3(0, 1, 0)

export class TourPlan {
  readonly windows: EraWindow[] = []
  readonly revealAt: Float32Array
  readonly total: number
  private readonly y: number[]
  private readonly radii: number[]
  private readonly eraEnd: number[] = []
  private readonly order: Int32Array
  private lo = 0
  private hi = 0

  constructor(placed: PlacedNode[], eraRadii: number[], eraY: number[]) {
    this.radii = eraRadii
    this.y = eraY
    this.revealAt = new Float32Array(placed.length).fill(Number.POSITIVE_INFINITY)

    const counts = new Array(ERA_COUNT).fill(0)
    placed.forEach(p => counts[p.node.era]++)
    const present = counts.filter(c => c > 0)
    const nMin = Math.min(...present)
    const nMax = Math.max(...present)

    let cursor = BLEND
    for (let e = 0; e < ERA_COUNT; e++) {
      const n = counts[e]
      const dur = n === 0 ? 0
        : nMax === nMin ? MIN_DUR
        : MIN_DUR + (MAX_DUR - MIN_DUR) * (n - nMin) / (nMax - nMin)
      this.windows.push({ start: cursor, dur, count: n })
      this.eraEnd.push(cursor + dur)
      cursor += dur
    }
    this.total = cursor + OUTRO

    // 时代内按 year 升序显现：顺序忠实于年代，节奏按排名均摊
    // （直接线性映射年份会让跨度数十万年的史前层把九成节点堆在最后一秒）
    const byEra: number[][] = Array.from({ length: ERA_COUNT }, () => [])
    placed.forEach((p, i) => byEra[p.node.era].push(i))
    byEra.forEach(list =>
      list.sort((a, b) => placed[a].node.year - placed[b].node.year || a - b))

    this.order = new Int32Array(placed.length)
    let head = 0
    byEra.forEach((list, e) => {
      const { start, dur } = this.windows[e]
      list.forEach((idx, k) => {
        this.revealAt[idx] = start + dur * (k + 0.5) / list.length
        this.order[head++] = idx
      })
    })
  }

  /** 时刻 t 所属的时代（漫游未开始时为 0） */
  eraOf(t: number): number {
    for (let e = 0; e < this.eraEnd.length; e++) if (t < this.eraEnd[e]) return e
    return this.eraEnd.length - 1
  }

  /** 该时代窗口结束的时刻 */
  eraWindowEnd(era: number): number {
    return this.eraEnd[Math.min(era, this.eraEnd.length - 1)]
  }

  /**
   * 摄像机跟踪的基准高度：本层环面 → 下一层环面之间 smoothstep 推进（顶层外推）。
   * 只依赖连续插值，跨层不跳变。
   */
  private trackY(t: number): number {
    const top = ERA_COUNT - 1
    const e = this.eraOf(t)
    const w = this.windows[e]
    const u = w.dur > 0 ? Math.min(1, Math.max(0, (t - w.start) / w.dur)) : 1
    const nextY = e < top ? this.y[e + 1] : this.y[top] + (this.y[top] - this.y[top - 1])
    return this.y[e] + (nextY - this.y[e]) * smoothstep(u)
  }

  /** 漫游视场：随"要看的圆盘"大小渐变（见 fovFor） */
  fovAt(t: number): number {
    return fovFor(this.radiusAtY(this.trackY(t)))
  }

  /**
   * 摄像机位姿：沿中轴线上升，视线全程完全朝下（−Y）；唯一的旋转自由度是绕视轴的
   * 滚转，由 upAt 缓慢给出。摄像机停在跟踪高度之上 LEAD，于是正显现的那一层始终位于
   * 镜头下方 LEAD..LEAD+层高 处，是视野里最近的物体 —— 下方已积累的树变成背景，
   * 显现中的科技不会被任何东西挡住。
   */
  poseAt(t: number, pos: THREE.Vector3, target: THREE.Vector3) {
    const top = ERA_COUNT - 1
    const y = this.trackY(t) + LEAD

    if (t <= this.eraEnd[top]) {
      pos.set(0, y, 0)
      target.set(0, y - 100, 0)
      return
    }

    // 收尾：离开中轴线后撤到全景位，落点与 resetView 一致，交接回环绕模式时无跳变
    const s = smoothstep((t - this.eraEnd[top]) / OUTRO)
    const d = startViewDistance(this.radii, this.y[top]) / Math.SQRT2
    pos.set(
      THREE.MathUtils.lerp(0, d, s),
      THREE.MathUtils.lerp(y, this.y[top] * 0.68, s),
      THREE.MathUtils.lerp(0, d, s)
    )
    _look.set(0, this.y[top] * 0.5, 0)
    target.copy(pos).addScaledVector(_dir.set(0, -1, 0), 100).lerp(_look, s)
  }

  /** 高度 → 该处塔身半径（线性插值），用于连续地推导滞后量 */
  radiusAtY(y: number): number {
    if (y <= this.y[0]) return this.radii[0]
    for (let i = 0; i < ERA_COUNT - 1; i++) {
      if (y <= this.y[i + 1]) {
        const f = (y - this.y[i]) / (this.y[i + 1] - this.y[i])
        return this.radii[i] + (this.radii[i + 1] - this.radii[i]) * f
      }
    }
    return this.radii[ERA_COUNT - 1]
  }

  /** 滚转基向量：视线朝上时 up 必须水平；收尾阶段随视线摆回世界竖直 */
  upAt(t: number, out: THREE.Vector3) {
    const a = START_ANGLE + t * ROLL
    out.set(Math.cos(a), 0, Math.sin(a))
    const top = ERA_COUNT - 1
    if (t > this.eraEnd[top]) {
      out.lerp(_upY, smoothstep((t - this.eraEnd[top]) / OUTRO)).normalize()
    }
    return out
  }

  /** 显现时刻即出现顺序，故用一对单调指针取"显现后 NAME_LIFE 秒内"的条目 */
  collectNames(t: number, idxOut: Int32Array, alphaOut: Float32Array): number {
    const n = this.order.length
    while (this.lo < n && this.revealAt[this.order[this.lo]] < t - NAME_LIFE) this.lo++
    while (this.hi < n && this.revealAt[this.order[this.hi]] <= t) this.hi++
    const count = Math.min(this.hi - this.lo, idxOut.length)
    for (let k = 0; k < count; k++) {
      const idx = this.order[this.lo + k]
      const age = t - this.revealAt[idx]
      idxOut[k] = idx
      alphaOut[k] = Math.min(1, age / 0.15, (NAME_LIFE - age) / NAME_FADE)
    }
    return count
  }

  reset() {
    this.lo = 0
    this.hi = 0
  }
}
