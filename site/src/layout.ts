import * as THREE from 'three'
import type { TechNode } from './data'
import { ERA_COUNT, CATEGORY_COUNT } from './data'

// 圆柱塔布局：Y 轴 = 时间（时代分层），角度 = 领域（CATEGORY_COUNT 扇区）
// 扇区的角度按"该领域在本时代的数量占比"分配（不设下限）：等角度会让冷门领域大片留白、
// 热门领域挤成一团 —— 实测各时代扇区密度 max/min 平均 47.7 倍
// 近代节点爆炸 → 超线性扩散：层间距更厚 + 半径超比例放大 + 节点最小间距放宽
export const BASE_RADIUS = 42      // 基准层半径
const RADIUS_EXPONENT = 0.65       // >0.5：近代层面密度实际下降，视觉更疏朗
const INNER_RATIO = 0.28           // 环空内径 / 外径
const SECTOR_FILL = 0.84           // 扇区实际占用的角度比例
// 面积目标占用率：按需求算层半径时留余量。圆形节点无法无缝铺满楔形，
// 若解到 fill=1.00（旧行为：peak/K 正好等于面积预算），松弛迭代必然要把节点挤出扇区或彼此重叠。
// 0.42 是"扇区按本层数量比例分角度"之后重标的：等角度时最挤的扇区会把整层半径顶高，
// 顺带给了别的扇区余量；比例化之后这份余量消失，实测占用率 0.8→137 对重叠、0.55→44、0.42→6。
const SECTOR_FILL_TARGET = 0.42
// 整圈环空面积 / R²（扇区按占比切分后再乘 SECTOR_FILL）
const SECTOR_UNIT_AREA = Math.PI * (1 - INNER_RATIO ** 2)

export interface PlacedNode {
  node: TechNode
  position: THREE.Vector3
  scale: number          // 多面体尺寸（由重要度决定）
  spinAxis: THREE.Vector3
  spinSpeed: number
  phase: number
}

export interface TowerLayout {
  placed: PlacedNode[]
  eraRadii: number[]     // 每层外径
  eraY: number[]         // 每层的 Y 坐标（近代层间距更厚，Y 不再等差）
  towerHeight: number
}

export function importanceScale(importance: number): number {
  // 规范 §3.4：1 = 基石 → 最大，5 = 长尾 → 最小。与面数（20→4）构成双通道编码
  return 1.9 - (importance - 1) * 0.35   // 1→1.9  2→1.55  3→1.2  4→0.85  5→0.5
}

// 各档形状的外接球半径：统一 1.5，仅基石（20 面）直径再放大 40% 以便在满屏小立体里一眼可辨。
// 层面积预算、同层最小间距、名称偏移都以本函数为准，改这里即可同步生效
const GEOM_RADIUS = 1.5
export function geomRadius(importance: number): number {
  return Math.round(importance) <= 1 ? GEOM_RADIUS * 1.4 : GEOM_RADIUS
}

/**
 * 开场/复位视距：按塔的包围球推导，使展宽或收窄后的取景比例保持一致。
 * 2.03 由旧版实测取景反推（旧库 maxR=76、H≈330 → 视距 368 = 2.03×√(76²+165²)）。
 *
 * 宽高比补偿：包围球推导隐含"水平方向足够宽"这个前提，而透视相机的垂直 fov 固定
 * （55°），水平 fov = 2·atan(tan(vfov/2)·aspect)，竖屏时水平视野被压窄，塔会左右溢出。
 * 这里按宽屏基准反比放大视距。上限 1.85 倍是为了不让塔被推得过小
 * （controls.maxDistance 另有上限，超出会被截断）。
 *
 * 本函数是 scene / controls / tour 三处取景的共同入口 —— 只有在函数内部补偿，
 * 才能保证三方算出的距离始终一致（tour 收尾要求落点与 resetView 完全对齐，否则会跳变）。
 */
export const VIEW_FIT = 2.03
const WIDE_ASPECT = 1.45          // 视为"足够宽"的基准宽高比
const MAX_ASPECT_BOOST = 1.85

export function startViewDistance(eraRadii: number[], towerHeight: number): number {
  const maxR = Math.max(...eraRadii)
  const fit = VIEW_FIT * Math.hypot(maxR, towerHeight / 2)
  if (typeof window === 'undefined') return fit
  const aspect = window.innerWidth / Math.max(window.innerHeight, 1)
  if (aspect >= WIDE_ASPECT) return fit
  return fit * Math.min(WIDE_ASPECT / Math.max(aspect, 0.45), MAX_ASPECT_BOOST)
}

// mulberry32
function mulberry32(seed: number) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function layoutTower(nodes: TechNode[]): TowerLayout {
  const rand = mulberry32(9917)

  // 每层节点数与外径
  const counts = new Array(ERA_COUNT).fill(0)
  nodes.forEach(n => counts[n.era]++)
  const avgCount = nodes.length / ERA_COUNT

  // 按 (era, category) 分桶——必须先于半径计算，因为拥挤度由最挤的扇区决定
  const buckets = new Map<string, TechNode[]>()
  nodes.forEach(n => {
    const key = `${n.era}:${n.category}`
    const arr = buckets.get(key)
    if (arr) arr.push(n)
    else buckets.set(key, [n])
  })
  // 每个扇区占整圈的角度比例 = 该领域在本时代的节点占比（空领域比例为 0，不设下限）
  const sectorSlices: number[][] = []
  for (let era = 0; era < ERA_COUNT; era++) {
    const slice = new Array(CATEGORY_COUNT).fill(0)
    for (let cat = 0; cat < CATEGORY_COUNT; cat++) {
      slice[cat] = counts[era] ? (buckets.get(`${era}:${cat}`)?.length ?? 0) / counts[era] : 0
    }
    sectorSlices.push(slice)
  }
  // 拥挤度 = 需求面积 / 该扇区可用角度，取最大的扇区决定层半径
  const eraRadii = counts.map((c, era) => {
    let peak = 0
    for (let cat = 0; cat < CATEGORY_COUNT; cat++) {
      const slice = sectorSlices[era][cat]
      if (slice <= 0) continue
      let demand = 0
      for (const n of buckets.get(`${era}:${cat}`) ?? []) {
        const r = geomRadius(n.importance) * importanceScale(n.importance)
        demand += Math.PI * (r * 1.15) ** 2
      }
      peak = Math.max(peak, demand / (slice * SECTOR_FILL))
    }
    return Math.max(
      BASE_RADIUS * Math.pow(c / avgCount, RADIUS_EXPONENT),
      Math.sqrt(peak / (SECTOR_UNIT_AREA * SECTOR_FILL_TARGET))
    )
  })

  // 层间距：节点多的时代层更厚（近代拉开垂直距离）
  const eraGaps = counts.map(c => Math.min(42, 22 + c * 0.08))
  const eraY: number[] = []
  let acc = 0
  for (let e = 0; e < ERA_COUNT; e++) {
    eraY.push(acc)
    acc += eraGaps[e]
  }
  const towerHeight = eraY[ERA_COUNT - 1]

  const placed: PlacedNode[] = []
  const layerNodes: PlacedNode[][] = Array.from({ length: ERA_COUNT }, () => [])

  for (let era = 0; era < ERA_COUNT; era++) {
    const outerR = eraRadii[era]
    const innerR = Math.max(outerR * INNER_RATIO, 5)
    const y = eraY[era]
    // 节点最小间距随层节点数放宽（近代更疏朗）
    const spread = 1 + counts[era] / 500

    let cum = 0 // 已累计的角度比例：扇区次序固定为领域索引，只改变宽度
    for (let cat = 0; cat < CATEGORY_COUNT; cat++) {
      const list = buckets.get(`${era}:${cat}`) ?? []
      const slice = sectorSlices[era][cat] * Math.PI * 2
      const sectorStart = cum + slice * 0.08
      const sectorWidth = slice * SECTOR_FILL
      cum += slice

      for (const n of list) {
        // sqrt 分布的半径 + 扇区内随机角度
        const r = innerR + (outerR - innerR) * Math.sqrt(rand())
        const theta = sectorStart + sectorWidth * rand()
        const scale = importanceScale(n.importance)
        const p = new PlacedNodeImpl(
          n, new THREE.Vector3(Math.cos(theta) * r, y, Math.sin(theta) * r),
          scale,
          new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).normalize(),
          0.08 + rand() * 0.22,
          rand() * Math.PI * 2
        )
        placed.push(p)
        layerNodes[era].push(p)
      }
    }
  }

  // 同层最小间距修正（松弛迭代；相切需 ra+rb，这里再留可见间隙）
  for (let era = 0; era < ERA_COUNT; era++) {
    const arr = layerNodes[era]
    const spread = 1 + counts[era] / 500
    for (let iter = 0; iter < 16; iter++) {
      for (let i = 0; i < arr.length; i++) {
        for (let j = i + 1; j < arr.length; j++) {
          const a = arr[i], b = arr[j]
          const dx = b.position.x - a.position.x
          const dz = b.position.z - a.position.z
          const dist = Math.hypot(dx, dz)
          const minDist = ((geomRadius(a.node.importance) * a.scale
                          + geomRadius(b.node.importance) * b.scale) * 1.15 + 0.4) * spread
          if (dist < minDist && dist > 1e-4) {
            const push = (minDist - dist) / 2
            const nx = dx / dist, nz = dz / dist
            a.position.x -= nx * push; a.position.z -= nz * push
            b.position.x += nx * push; b.position.z += nz * push
          } else if (dist <= 1e-4) {
            a.position.x += (rand() - 0.5) * 0.5
            a.position.z += (rand() - 0.5) * 0.5
          }
        }
      }
    }
  }

  return { placed, eraRadii, eraY, towerHeight }
}

class PlacedNodeImpl implements PlacedNode {
  constructor(
    public node: TechNode,
    public position: THREE.Vector3,
    public scale: number,
    public spinAxis: THREE.Vector3,
    public spinSpeed: number,
    public phase: number
  ) {}
}
