import * as THREE from 'three'
import { geomRadius, type PlacedNode } from './layout'
import { ERA_INFO } from './data'

// 文字标签：Canvas 图集 + 实例化 billboard（始终正对摄像机）
// 图集支持变宽条目：每个条目有自己的 UV 矩形与宽高比（科技名称长短不一）
// 名称标签锚定多面体中心、沿视线向相机偏移 → 文字"贴在正对相机的那一面"
// 时代名标签拆成单字沿圆环外沿弧形排布（位置固定，不随相机移动）

export interface LabelData {
  position: THREE.Vector3
  uv: [number, number, number, number] // 条目 UV 矩形（u0, v0, du, dv）
  aspect: number                        // 条目宽高比（世界宽 = 高 × aspect）
  size: number                          // 世界单位高度
  always: boolean                       // 重要节点常显
  offset: number                        // 沿视线朝相机的偏移（避免被自身多面体遮挡）
}

interface AtlasPage {
  texture: THREE.Texture
  count: number // 本页条目数
}

const VERT = `
attribute vec3 aPos;
attribute vec4 aUv;
attribute float aAspect;
attribute float aSize;
attribute float aAlways;
attribute float aOffset;
attribute float aVisible;   // 0=隐藏；(0,1] 同时作为不透明度（漫游中名称淡出）
uniform float uFocal;   // 视频焦距（像素）：屏幕高 / (2·tan(fov/2))
uniform float uMinPx;   // 常显标签的屏幕最小像素高（远处不缩成点）
uniform float uMinAll;  // 漫游中所有名称的屏幕最小像素高（远处的名字也要能读）
uniform float uMaxPx;   // 标签的屏幕最大像素高（贴近相机也不放大）
uniform float uNear;    // 相机近裁剪面（锚点比它更近则隐藏）
varying vec2 vUv;
varying float vAlpha;
void main() {
  if (aVisible <= 0.001) {
    // 隐藏实例：挪到 NDC 视锥外，整三角形被裁剪
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vAlpha = 0.0;
    return;
  }
  // 锚点变换到视图空间
  vec4 mv = viewMatrix * vec4(aPos, 1.0);
  vec2 corner = position.xy; // quad -0.5..0.5
  // 相机在视图原点看向 -Z：锚点进入相机背后或比近裁剪面更近时，
  // billboard 强透视会把字放大到糊屏 → 直接裁剪掉
  if (mv.z > -uNear) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vAlpha = 0.0;
    return;
  }
  float dist = -mv.z; // 正前方向深度（不用 length，避免背后/侧向误算）
  // 世界尺寸 → 自然屏幕像素；钳制在 [uMinPx, uMaxPx]：
  // 常显标签远处不小于 uMinPx，所有标签贴近相机也不超过 uMaxPx
  float naturalPx = aSize * uFocal / dist;
  float minPx = max(aAlways > 0.5 ? uMinPx : 0.0, uMinAll);
  float pxSize = clamp(naturalPx, minPx, uMaxPx);
  float finalSize = pxSize * dist / uFocal;
  // 屏幕对齐 billboard：视图空间中相机永远看向 -Z，right=(1,0,0) up=(0,1,0)
  mv.xyz += vec3(corner.x * finalSize * aAspect, corner.y * finalSize, 0.0);
  mv.z += aOffset; // 沿视线朝相机偏移：文字浮在多面体正对面上
  // 偏移后若文字越过近裁剪面（贴到相机上），同样裁掉，避免最后一刻放大糊屏
  if (mv.z > -uNear) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vAlpha = 0.0;
    return;
  }
  gl_Position = projectionMatrix * mv;
  vUv = aUv.xy + vec2(corner.x + 0.5, 0.5 - corner.y) * aUv.zw;
  float fadeNear = mix(135.0, 430.0, aAlways);
  float fadeFar = mix(215.0, 650.0, aAlways);
  vAlpha = aVisible * (1.0 - smoothstep(fadeNear, fadeFar, dist));
}`

const FRAG = `
uniform sampler2D uMap;
varying vec2 vUv;
varying float vAlpha;
void main() {
  vec4 c = texture2D(uMap, vUv);
  if (c.a < 0.04) discard;
  gl_FragColor = vec4(c.rgb, c.a * vAlpha);
}`

// 已创建的标签材质（updateLabelFocal 时统一更新焦距）
const labelMaterials: THREE.ShaderMaterial[] = []

export function createBillboards(datas: LabelData[], pages: AtlasPage[]): THREE.Mesh[] {
  const meshes: THREE.Mesh[] = []
  const base = new THREE.PlaneGeometry(1, 1)

  let start = 0
  pages.forEach(page => {
    const slice = datas.slice(start, start + page.count)
    start += page.count
    if (slice.length === 0) return

    const geo = new THREE.InstancedBufferGeometry()
    geo.index = base.index
    geo.setAttribute('position', base.attributes.position)

    const pos = new Float32Array(slice.length * 3)
    const uv = new Float32Array(slice.length * 4)
    const aspect = new Float32Array(slice.length)
    const size = new Float32Array(slice.length)
    const always = new Float32Array(slice.length)
    const offset = new Float32Array(slice.length)
    const visible = new Float32Array(slice.length).fill(1)
    slice.forEach((d, i) => {
      pos[i * 3] = d.position.x; pos[i * 3 + 1] = d.position.y; pos[i * 3 + 2] = d.position.z
      uv[i * 4] = d.uv[0]; uv[i * 4 + 1] = d.uv[1]; uv[i * 4 + 2] = d.uv[2]; uv[i * 4 + 3] = d.uv[3]
      aspect[i] = d.aspect
      size[i] = d.size
      always[i] = d.always ? 1 : 0
      offset[i] = d.offset
    })
    geo.setAttribute('aPos', new THREE.InstancedBufferAttribute(pos, 3))
    geo.setAttribute('aUv', new THREE.InstancedBufferAttribute(uv, 4))
    geo.setAttribute('aAspect', new THREE.InstancedBufferAttribute(aspect, 1))
    geo.setAttribute('aSize', new THREE.InstancedBufferAttribute(size, 1))
    geo.setAttribute('aAlways', new THREE.InstancedBufferAttribute(always, 1))
    geo.setAttribute('aOffset', new THREE.InstancedBufferAttribute(offset, 1))
    geo.setAttribute('aVisible', new THREE.InstancedBufferAttribute(visible, 1))
    geo.instanceCount = slice.length

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uMap: { value: page.texture },
        uFocal: { value: 700 },
        uMinPx: { value: 16 },
        uMinAll: { value: 0 },
        uMaxPx: { value: 28 },
        uNear: { value: 0.1 },
      },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
    })
    labelMaterials.push(mat)
    const mesh = new THREE.Mesh(geo, mat)
    mesh.frustumCulled = false
    meshes.push(mesh)
  })
  return meshes
}

function makeCanvasTexture(canvas: HTMLCanvasElement): THREE.Texture {
  const tex = new THREE.CanvasTexture(canvas)
  tex.flipY = false
  tex.colorSpace = THREE.SRGBColorSpace
  tex.minFilter = THREE.LinearMipmapLinearFilter
  tex.generateMipmaps = true
  return tex
}

/** 视口/fov 变化时更新焦距（保证屏幕最小像素尺寸换算正确） */
export function updateLabelFocal(viewportHeight: number, fovDeg: number) {
  const focal = viewportHeight / (2 * Math.tan((fovDeg * Math.PI) / 360))
  labelMaterials.forEach(m => { m.uniforms.uFocal.value = focal })
}

/** 漫游时给所有名称垫一个可读字号（0 = 恢复常态的按距离缩放） */
export function setLabelMinPxAll(px: number) {
  labelMaterials.forEach(m => { m.uniforms.uMinAll.value = px })
}

// ───── 科技名称图集（shelf pack：行式排布，条目宽度随文字长度变化） ─────

const PAGE_W = 4096 // 图集页宽（像素）
const LINE_H = 112  // 行高（像素）
const FONT_PX = 88  // 字号（文字占行高 79%，避免 mipmap 后过细）
const PAD_X = 26    // 条目左右留白（像素）
const MAX_LINES = 32 // 每页最多行数（高度上限 3584px）

const NAME_FONT = `bold ${FONT_PX}px "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif`

interface NameSlot {
  page: number
  x: number     // 条目左上角像素 x
  y: number     // 条目左上角像素 y（行 × 行高）
  w: number     // 条目像素宽（含留白）
  pageH: number // 所在页总高（像素，用于归一化）
}

/** 名称打包进图集页：第一遍测量宽度并预排，第二遍逐页绘制 */
function buildNameAtlas(names: string[]): { pages: AtlasPage[]; slots: NameSlot[] } {
  // 第一遍：测量
  const measure = document.createElement('canvas').getContext('2d')!
  measure.font = NAME_FONT
  const widths = names.map(n => Math.ceil(measure.measureText(n).width) + PAD_X * 2)

  // 第二遍：预排（页 → 行 → 列）
  const slots: NameSlot[] = []
  const pageLineCounts: number[] = [1] // 每页已占用的行数
  let page = 0, x = 0, line = 0
  for (let i = 0; i < names.length; i++) {
    const w = widths[i]
    if (x + w > PAGE_W) { x = 0; line++ } // 当前行放不下 → 换行
    if (line >= MAX_LINES) { page++; line = 0; pageLineCounts.push(1); x = 0 }
    else if (line + 1 > pageLineCounts[page]) { pageLineCounts[page] = line + 1 }
    slots.push({ page, x, y: line * LINE_H, w, pageH: 0 })
    x += w
  }
  const pageCount = pageLineCounts.length
  slots.forEach(s => { s.pageH = pageLineCounts[s.page] * LINE_H })

  // 第三遍：逐页绘制
  const pages: AtlasPage[] = []
  for (let p = 0; p < pageCount; p++) {
    const canvas = document.createElement('canvas')
    canvas.width = PAGE_W
    canvas.height = pageLineCounts[p] * LINE_H
    const ctx = canvas.getContext('2d')!
    ctx.font = NAME_FONT
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    let count = 0
    for (let i = 0; i < names.length; i++) {
      const s = slots[i]
      if (s.page !== p) continue
      const cx = s.x + s.w / 2
      const cy = s.y + LINE_H / 2
      ctx.lineWidth = 12
      ctx.strokeStyle = 'rgba(0,0,0,0.92)'
      ctx.strokeText(names[i], cx, cy)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(names[i], cx, cy)
      count++
    }
    pages.push({ texture: makeCanvasTexture(canvas), count })
  }
  return { pages, slots }
}

/** 科技名称标签：名称打包进变宽图集，锚定多面体中心；
 *  update 按到相机距离只保留最近的 limit 个名称 */
export function buildNameLabels(placed: PlacedNode[]): {
  meshes: THREE.Mesh[]
  update: (camera: THREE.PerspectiveCamera, limit: number, viewportW: number, viewportH: number) => void
  /** 漫游：只点亮刚显现的科技名（带淡出 alpha） */
  setTourNames: (count: number, idx: Int32Array, alpha: Float32Array) => void
  /** 让下一次 update 无视静止缓存强制重算 */
  invalidate: () => void
  /** 名称筛选：非匹配条目直接不参与"屏内最近 N 个"的选取 */
  setFilter: (keep: ((nodeIdx: number) => boolean) | null) => void
} {
  const names = placed.map(p => p.node.name)
  const { pages, slots } = buildNameAtlas(names)

  const datas: LabelData[] = placed.map((p, i) => {
    const s = slots[i]
    return {
      // 锚定多面体中心 + 沿视线朝相机偏移 → 任何角度看文字都"贴"在多面体正面上
      position: p.position.clone(),
      uv: [s.x / PAGE_W, s.y / s.pageH, s.w / PAGE_W, LINE_H / s.pageH],
      aspect: s.w / LINE_H,
      size: 1.9 - p.node.importance * 0.2,
      always: p.node.importance <= 2,
      offset: geomRadius(p.node.importance) * p.scale + 0.8,
    }
  })

  const meshes = createBillboards(datas, pages)

  // 节点索引 → 所在页的 aVisible 属性 + 页内实例索引（页大小不一，需逐页累计）
  const visAttrs = meshes.map(m =>
    (m.geometry as THREE.InstancedBufferGeometry).getAttribute('aVisible') as THREE.InstancedBufferAttribute
  )
  const nodeLocal: { attr: THREE.InstancedBufferAttribute; local: number }[] = []
  const pageStarts: number[] = [] // 每页在 datas 中的起始偏移
  let acc = 0
  pages.forEach(p => { pageStarts.push(acc); acc += p.count })
  placed.forEach((_, i) => {
    const pg = slots[i].page
    nodeLocal.push({ attr: visAttrs[pg], local: i - pageStarts[pg] })
  })

  // 距离排序缓存（避免每帧分配）
  const dists = new Float32Array(placed.length)
  const order: number[] = []
  const lastCamPos = new THREE.Vector3(0, -1e9, 0) // 初始值保证首帧必更新
  let lastLimit = -1
  let lastW = 0, lastH = 0
  let keep: ((nodeIdx: number) => boolean) | null = null

  const _v = new THREE.Vector3()
  const _proj = new THREE.Vector3()

  // 与 shader 一致的像素尺寸钳制常量
  const MIN_PX = 16, MAX_PX = 28, MARGIN_PX = 8 // MARGIN：距屏幕边缘的安全留白

  const update = (
    camera: THREE.PerspectiveCamera,
    limit: number,
    viewportW: number,
    viewportH: number
  ) => {
    // 相机静止、上限/视口未变时跳过
    if (
      limit === lastLimit && viewportW === lastW && viewportH === lastH &&
      camera.position.distanceToSquared(lastCamPos) < 0.25
    ) return
    lastCamPos.copy(camera.position)
    lastLimit = limit; lastW = viewportW; lastH = viewportH

    const focal = viewportH / (2 * Math.tan((camera.fov * Math.PI) / 360))
    camera.updateMatrixWorld()

    // 只统计"文字能完整落在屏幕内"的节点：
    // 投影到 NDC，再按该标签的屏幕像素半宽/半高判定矩形是否整体在内
    order.length = 0
    for (let i = 0; i < placed.length; i++) {
      if (keep && !keep(i)) continue
      const p = placed[i]
      // 相机空间深度：在相机背后或比近裁剪面近的剔除
      _proj.copy(p.position).applyMatrix4(camera.matrixWorldInverse)
      const depth = -_proj.z
      if (depth < camera.near) continue

      // 投影到 NDC（裁剪空间归一化坐标）
      _v.copy(p.position).project(camera)

      // 复刻 shader 像素高度
      const naturalPx = datas[i].size * focal / depth
      const pxH = datas[i].always
        ? Math.min(Math.max(naturalPx, MIN_PX), MAX_PX)
        : Math.min(naturalPx, MAX_PX)
      const pxW = pxH * datas[i].aspect

      // 文字矩形相对屏幕中心的半尺寸（NDC 单位）
      const halfNdcW = (pxW / 2 + MARGIN_PX) / (viewportW / 2)
      const halfNdcH = (pxH / 2 + MARGIN_PX) / (viewportH / 2)

      // 整个矩形落在 NDC [-1,1] 内才算完整可见
      if (
        _v.x - halfNdcW >= -1 && _v.x + halfNdcW <= 1 &&
        _v.y - halfNdcH >= -1 && _v.y + halfNdcH <= 1
      ) {
        dists[i] = depth * depth
        order.push(i)
      }
    }
    order.sort((a, b) => dists[a] - dists[b])

    visAttrs.forEach(a => (a.array as Float32Array).fill(0))
    const n = Math.min(Math.max(limit, 0), order.length)
    for (let k = 0; k < n; k++) {
      const e = nodeLocal[order[k]]
      ;(e.attr.array as Float32Array)[e.local] = 1
    }
    visAttrs.forEach(a => { a.needsUpdate = true })
  }

  return {
    meshes,
    update,
    /** 漫游：只点亮"刚显现的少数名称"并带上淡出 alpha，跳过屏内最近 N 个的名额逻辑 */
    setTourNames: (count: number, idx: Int32Array, alpha: Float32Array) => {
      visAttrs.forEach(a => (a.array as Float32Array).fill(0))
      for (let k = 0; k < count; k++) {
        const e = nodeLocal[idx[k]]
        ;(e.attr.array as Float32Array)[e.local] = alpha[k]
      }
      visAttrs.forEach(a => { a.needsUpdate = true })
    },
    /** 迫使下一次 update 重算（退出漫游时名额集需要立刻恢复） */
    invalidate: () => { lastCamPos.set(0, -1e9, 0) },
    setFilter: (fn: ((nodeIdx: number) => boolean) | null) => {
      keep = fn
      lastCamPos.set(0, -1e9, 0) // 迫使下一帧重算可见集
    },
  }
}

// ───── 时代名标签：单字沿圆环外沿弧形排布（固定方位，双侧对称） ─────

/** 时代名标签：将每个时代名拆成单字，沿该层圆环外沿弧形排布，
 *  每个字符作为 billboard 始终正对相机 → 文字"刻"在环上，不遮挡中间节点 */
export function buildEraLabels(eraRadii: number[], eraY: number[]): {
  meshes: THREE.Mesh[]
  update: () => void
  /** 漫游：只显示已到达时代（含当前层）的时代名；传 -1 恢复全部 */
  setVisibleThrough: (era: number) => void
} {
  // 收集所有时代名的字符并去重，生成字符图集
  const uniqueChars: string[] = []
  const charSet = new Set<string>()
  for (let e = 0; e < eraRadii.length; e++) {
    for (const ch of ERA_INFO[e].name) {
      if (!charSet.has(ch)) { charSet.add(ch); uniqueChars.push(ch) }
    }
  }

  // 字符图集：8×8 格，每格 128×128，字号 96（文字占比高，清晰锐利）
  const cols = 8, rows = 8
  const cellW = 128, cellH = 128
  const canvas = document.createElement('canvas')
  canvas.width = cols * cellW
  canvas.height = rows * cellH
  const ctx = canvas.getContext('2d')!
  const charToCell = new Map<string, [number, number]>()
  uniqueChars.forEach((ch, i) => {
    const col = i % cols, row = Math.floor(i / cols)
    charToCell.set(ch, [col, row])
    const x = col * cellW + cellW / 2
    const y = row * cellH + cellH / 2
    ctx.font = 'bold 96px "Microsoft YaHei", "PingFang SC", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.shadowColor = 'rgba(80, 140, 255, 0.85)'
    ctx.shadowBlur = 18
    ctx.lineWidth = 10
    ctx.strokeStyle = 'rgba(0,0,0,0.85)'
    ctx.strokeText(ch, x, y)
    ctx.fillStyle = '#dce8ff'
    ctx.fillText(ch, x, y)
  })
  const tex = makeCanvasTexture(canvas)

  // 弧排参数
  const RING_OFFSET = 2.5   // 与 edges.ts 中时代环半径偏移一致
  const charMargin = 11     // 文字到环的外沿距离
  const charSize = 3.0      // 单字世界单位高度（≈ 单字宽度，汉字近正方形）
  // 相邻字符的弧长间距：略大于字宽，刚好不重叠即可（不随字数均摊，短名字不会被拉开）
  const charSpacing = 3.6
  const baseAngle = Math.PI * 0.25  // 第一层文字方位（45°，匹配初始相机视角）
  // 各层沿塔螺旋错开方位角：拉远后相邻层的时代名不会在屏幕上垂直堆叠
  // 每层递增约 33°，且用无理数比例避免周期性重合
  const perEraAngle = Math.PI * 0.367
  const sideCount = 2       // 在环的两侧（对称位置）各写一遍

  // 为每个时代的每个字符建立实例：两侧各一份
  interface CharInst { era: number; idx: number; total: number; cell: [number, number]; side: number }
  const insts: CharInst[] = []
  for (let e = 0; e < eraRadii.length; e++) {
    const name = ERA_INFO[e].name
    const total = name.length
    for (let side = 0; side < sideCount; side++) {
      for (let i = 0; i < total; i++) {
        insts.push({ era: e, idx: i, total, cell: charToCell.get(name[i])!, side })
      }
    }
  }

  const datas: LabelData[] = insts.map(ci => {
    const total = ci.total
    const R = eraRadii[ci.era] + RING_OFFSET + charMargin
    // 固定字符弧间距（与字数无关）：角步长 = 弧距 / 半径
    const step = charSpacing / R
    // 本层基准方位（沿塔螺旋错开）+ 两侧相隔 π（圆柱对称）
    const centerAngle = baseAngle + ci.era * perEraAngle + ci.side * Math.PI
    // i=0 放在弧的左端（角度最大处），i 增大角度递减 → 屏幕从左到右正序
    const startAngle = centerAngle + ((total - 1) / 2) * step
    const a = startAngle - ci.idx * step
    return {
      position: new THREE.Vector3(Math.cos(a) * R, eraY[ci.era], Math.sin(a) * R),
      uv: [ci.cell[0] / cols, ci.cell[1] / rows, 1 / cols, 1 / rows],
      aspect: 1,
      size: charSize,
      always: true,
      offset: 0,
    }
  })
  const meshes = createBillboards(datas, [{ texture: tex, count: insts.length }])

  // 文字位置固定在环上，不随相机移动；旋转相机时文字会绕到柱子后方
  const update = () => {}

  // 每个字符实例属于哪个时代（单页图集 → 一个 mesh，实例顺序与 insts 一致）
  const eraOfInst = insts.map(ci => ci.era)
  const visAttr = (meshes[0].geometry as THREE.InstancedBufferGeometry)
    .getAttribute('aVisible') as THREE.InstancedBufferAttribute

  return {
    meshes,
    update,
    setVisibleThrough: (era: number) => {
      const a = visAttr.array as Float32Array
      for (let i = 0; i < a.length; i++) a[i] = era < 0 || eraOfInst[i] <= era ? 1 : 0
      visAttr.needsUpdate = true
    },
  }
}
