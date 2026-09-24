import './style.css'
import * as THREE from 'three'
import { TECHS, TECH_BY_ID, ERA_INFO, ERA_COUNT, CATEGORY_NAMES, CATEGORY_COUNT, CATEGORY_HEX, CATEGORY_GROUPS, GROUP_NAMES, YEAR_BASIS_LABEL } from './data'
import type { TechNode } from './data'
import { layoutTower } from './layout'
import { createScene } from './scene'
import { PolyhedraField, facesOf } from './polyhedra'
import { buildEdges, buildEraRings } from './edges'
import { buildNameLabels, buildEraLabels, updateLabelFocal, setLabelMinPxAll } from './labels'
import { CameraRig } from './controls'
import { TourPlan, BLEND } from './tour'
import { applyMobileLayout, watchBreakpoint } from './mobile'

// ───── 数据与布局 ─────
const { placed, eraRadii, eraY, towerHeight } = layoutTower(TECHS)

// 统计行随数据变化，避免写死后再也数不清
document.getElementById('statLine')!.textContent =
  `${TECHS.length} 项科技 · ${ERA_COUNT} 个时代 · ${CATEGORY_COUNT} 大领域`

// ───── 场景 ─────
const { scene, camera, renderer } = createScene(towerHeight, eraRadii)

const field = new PolyhedraField(
  placed,
  CATEGORY_HEX.map(h => new THREE.Color(h))
)
field.meshes.forEach(m => scene.add(m))

const { rings } = buildEraRings(eraRadii, eraY)
rings.forEach(r => scene.add(r))

const nameLabels = buildNameLabels(placed)
nameLabels.meshes.forEach(m => scene.add(m))

// 时代名标签：每个时代名拆成单字，沿该层圆环外沿固定方位弧形排布
const eraLabels = buildEraLabels(eraRadii, eraY)
eraLabels.meshes.forEach(m => scene.add(m))

// ───── 相机与漫游排期 ─────
const plan = new TourPlan(placed, eraRadii, eraY)
const rig = new CameraRig(camera, renderer.domElement, eraRadii, towerHeight, plan)

// 连线要在漫游中按显现时刻生长，故依赖 plan 的 revealAt
const edges = buildEdges(placed, plan.revealAt)
scene.add(edges.lines)

// ───── UI：图例 + 名称显示上限 ─────
const legend = document.getElementById('legend')!
legend.innerHTML = `
  <div class="lg-head"><div class="lg-title">领域图例</div>
    <button class="lg-toggle" id="legendToggle" title="折叠/展开图例">▾</button></div>
  <div class="lg-body">
  ${['A', 'B', 'C', 'D'].map(g => `
    <div class="lg-group">${GROUP_NAMES[g]}</div>
    ${CATEGORY_NAMES.map((name, i) => CATEGORY_GROUPS[i] === g ? `
      <div class="lg-item">
        <span class="lg-dot" style="background:${CATEGORY_HEX[i]};color:${CATEGORY_HEX[i]}"></span>${name}
      </div>` : '').join('')}`).join('')}
  <div class="lg-sep"></div>
  <div class="lg-title">形状 = 重要度（面数）</div>
  <div class="lg-item">20 面 基石</div>
  <div class="lg-item">12 面 领域支柱</div>
  <div class="lg-item">8 面 领域内重要</div>
  <div class="lg-item">6 面 改良与细分</div>
  <div class="lg-item">4 面 长尾补充</div>
  <div class="lg-sep"></div>
  <div class="lg-title">名称显示上限</div>
  <div class="lg-limit">
    <input type="range" id="labelLimitRange" min="0" max="${TECHS.length}" step="1" value="100">
    <span id="labelLimitValue">100</span>
  </div>
  <div class="lg-hint">按到相机距离显示最近的名称</div>
  <div class="lg-sep"></div>
  <div class="lg-title">副轴 kind（规范 §3：筛选与文案）</div>
  <div class="lg-kinds" id="kindFilter"></div>
  <div class="lg-hint">点选即筛选：只压暗与让出名称名额，不动节点位置</div>
  </div>
`
// 图例折叠：只留标题行，把画面让给塔身
const legendToggle = document.getElementById('legendToggle') as HTMLButtonElement
legendToggle.addEventListener('click', () => {
  const collapsed = legend.classList.toggle('collapsed')
  legendToggle.textContent = collapsed ? '▸' : '▾'
})

// ───── `kind` 副轴筛选（§3；只改颜色与名称名额，不改布局） ─────
const kindFilter = document.getElementById('kindFilter')!
const KINDS = ['原理', '工艺', '器物', '制度', '媒介'] as const
const kindCount = KINDS.map(k => placed.filter(p => p.node.kind === k).length)
const activeKinds = new Set<string>()
kindFilter.innerHTML = KINDS.map((k, i) =>
  `<button class="lg-kind" data-kind="${k}">${k}<b>${kindCount[i]}</b></button>`).join('')
function applyKindFilter() {
  const keep = activeKinds.size
    ? (idx: number) => activeKinds.has(placed[idx].node.kind)
    : null
  field.setFilter(keep)
  nameLabels.setFilter(keep)
  kindFilter.querySelectorAll('.lg-kind').forEach(el =>
    el.classList.toggle('on', activeKinds.has((el as HTMLElement).dataset.kind!)))
}
kindFilter.addEventListener('click', e => {
  const k = (e.target as HTMLElement)?.dataset?.kind
  if (!k) return
  activeKinds.has(k) ? activeKinds.delete(k) : activeKinds.add(k)
  applyKindFilter()
})

let labelLimit = 100
const limitRange = document.getElementById('labelLimitRange') as HTMLInputElement
const limitValue = document.getElementById('labelLimitValue')!
limitRange.addEventListener('input', () => {
  labelLimit = Number(limitRange.value)
  limitValue.textContent = String(labelLimit)
})

// ───── 手机窄屏适配 ─────
// 窄屏默认收起图例、把名称上限收到 36、按输入方式改写操作提示；
// 取景的宽高比补偿在 layout.ts 的 startViewDistance() 里。
const hint = document.getElementById('hint')!
applyMobileLayout({ legend, hint })

// ───── UI：字幕 ─────
const caption = document.getElementById('eraCaption')!
let captionTimer = 0
rig.onEraChange = era => {
  const info = ERA_INFO[era]
  const win = plan.windows[era]
  caption.innerHTML = `${info.name}<span class="sub">${info.range} · ${win.count} 项</span>`
  caption.classList.add('show')
  clearTimeout(captionTimer)
  // 只停留到本时代窗口过半，把画面让给正在显现的科技名
  captionTimer = window.setTimeout(() => caption.classList.remove('show'), win.dur * 450)
}

// ───── UI：工具栏 ─────
const btnTour = document.getElementById('btnTour') as HTMLButtonElement
const btnReset = document.getElementById('btnReset') as HTMLButtonElement

// 漫游期间只保留时代名与科技名：其余界面与悬停让位，连线改为按显现时刻生长
const BASE_FOV = camera.fov
const fog = scene.fog as THREE.Fog
const FOG_BASE = { near: fog.near, far: fog.far }
let shownEra = -2
let shownFov = BASE_FOV

// 视场随"要看的圆盘"渐变；标签的像素换算依赖焦距，改 fov 必须同步
function applyFov(fov: number) {
  if (Math.abs(fov - shownFov) < 0.05) return
  shownFov = fov
  camera.fov = fov
  camera.updateProjectionMatrix()
  updateLabelFocal(innerHeight, fov)
}

// 未到达时代的圆盘与时代名不显示：俯视时它们是画面上方那片空白里唯一的杂物
function showEraStage(era: number) {
  if (era === shownEra) return
  shownEra = era
  rings.forEach((r, i) => (r.visible = i <= era))
  eraLabels.setVisibleThrough(era)
}

function setTouring(on: boolean) {
  document.body.classList.toggle('touring', on)
  if (!on) applyFov(BASE_FOV) // 环绕模式恢复默认视场；漫游中由主循环逐帧驱动
  setLabelMinPxAll(on ? 18 : 0) // 漫游中远处的名字也要读得清
  // 俯视会看到下方整棵已积累的树，把雾推远免得它糊成一片背景
  fog.near = on ? 420 : FOG_BASE.near
  fog.far = on ? 2200 : FOG_BASE.far
  if (on) {
    hoverIdx = null
    shownEra = -2
    field.beginTour(plan.revealAt, 0)
    edges.beginTour()
  } else {
    tooltip.classList.remove('show')
    renderer.domElement.style.cursor = ''
    field.endTour()
    field.highlight(null)
    edges.fillAll()
    nameLabels.invalidate()
    showEraStage(ERA_COUNT - 1)
  }
}

btnTour.addEventListener('click', () => {
  if (rig.mode === 'tour') {
    rig.stopTour()
  } else {
    rig.startTour()
    setTouring(true)
    btnTour.textContent = '⏹ 停止漫游'
    btnTour.classList.add('active')
  }
})
btnReset.addEventListener('click', () => rig.resetView())
rig.onTourEnd = () => {
  clearTimeout(captionTimer)
  caption.classList.remove('show')
  setTouring(false)
  btnTour.textContent = '▶ 漫游动画'
  btnTour.classList.remove('active')
}

// ───── 悬停信息 ─────
const tooltip = document.getElementById('tooltip')!
const raycaster = new THREE.Raycaster()
const ndc = new THREE.Vector2()
let hoverIdx: number | null = null

// 规范 §6：tooltip 同时显示"精确数值"与"真实精度"，避免把约定值读成确证
function yearText(n: TechNode): string {
  const b = YEAR_BASIS_LABEL[n.yearBasis] ?? { mark: '', approx: false }
  const abs = Math.abs(n.year)
  const core = n.year >= 0
    ? `${n.year} 年`
    : abs >= 10000 ? `前 ${(abs / 10000).toFixed(abs % 10000 === 0 ? 0 : 1)} 万年` : `公元前 ${abs} 年`
  return `${b.approx ? '约' : ''}${core}${b.mark ? `（${b.mark}）` : ''}`
}

renderer.domElement.addEventListener('pointermove', e => {
  if (rig.mode === 'tour') return // 漫游中相机在动，悬停无意义
  const rect = renderer.domElement.getBoundingClientRect()
  ndc.set(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1
  )
  raycaster.setFromCamera(ndc, camera)
  const hits = raycaster.intersectObjects(field.meshes, false)

  if (hits.length > 0) {
    const h = hits[0]
    const idx = field.nodeIndexAt(h.object, h.instanceId!)
    if (idx !== null) {
      hoverIdx = idx
      const n = placed[idx].node
      // 前置科技：显示名称（最多 4 个，避免溢出）
      const prereqNames = n.prereqs
        .map(id => TECH_BY_ID.get(id)?.name ?? '')
        .filter(Boolean)
        .slice(0, 4)
        .join('、')
      tooltip.innerHTML = `
        <div class="tt-name">${n.name}</div>
        <div class="tt-dim">${n.nameEn !== n.name ? n.nameEn + ' · ' : ''}${yearText(n)}</div>
        <div class="tt-dim">${ERA_INFO[n.era].name} · ${CATEGORY_NAMES[n.category]}${n.kind ? ' · ' + n.kind : ''}</div>
        <div class="tt-dim">重要度 ${'★'.repeat(6 - n.importance)}${'☆'.repeat(n.importance - 1)}　${facesOf(n.importance)} 面</div>
        ${prereqNames ? `<div class="tt-dim">前置：${prereqNames}</div>` : ''}
        ${n.desc ? `<div class="tt-desc">${n.desc}</div>` : ''}
        ${n.wikiEn
          ? `<div class="tt-src">摘要参考英文维基百科条目
              <a href="https://en.wikipedia.org/wiki/${encodeURIComponent(n.wikiEn)}" target="_blank" rel="noopener">${n.wikiEn}</a>
              （CC BY-SA 4.0）</div>`
          : ''}
      `
      tooltip.style.left = `${e.clientX + 16}px`
      tooltip.style.top = `${e.clientY + 12}px`
      tooltip.classList.add('show')
      renderer.domElement.style.cursor = 'pointer'
      return
    }
  }
  hoverIdx = null
  tooltip.classList.remove('show')
  renderer.domElement.style.cursor = ''
})

// ───── 自适应窗口 ─────
function refreshView() {
  camera.aspect = innerWidth / innerHeight
  camera.updateProjectionMatrix()
  renderer.setSize(innerWidth, innerHeight)
  updateLabelFocal(innerHeight, camera.fov) // 标签屏幕最小像素换算依赖焦距
}
refreshView()
window.addEventListener('resize', refreshView)

// 折叠屏开合、手机横竖切换会跨过窄屏断点。视距是按宽高比算出来的，
// 不重新取景就会留着上一套宽高比的结果：塔要么满出画面，要么缩成一小团。
watchBreakpoint(() => {
  rig.resetView()
  applyMobileLayout({ legend, hint })
})

// ───── 主循环 ─────
const clock = new THREE.Clock()
const nameIdx = new Int32Array(placed.length)
const nameAlpha = new Float32Array(placed.length)

function loop() {
  requestAnimationFrame(loop)
  const dt = Math.min(clock.getDelta(), 0.1)
  const time = clock.elapsedTime

  rig.update(dt)
  if (rig.mode === 'tour') {
    const t = rig.tourT - BLEND
    applyFov(plan.fovAt(t))
    field.setTourTime(t)
    field.update(time)
    edges.update(t)
    showEraStage(plan.eraOf(t))
    nameLabels.setTourNames(Math.max(0, plan.collectNames(t, nameIdx, nameAlpha)), nameIdx, nameAlpha)
  } else {
    field.update(time)
    field.highlight(hoverIdx)
    // 名称：仅完整在屏内的，按距离保留最近 limit 个
    nameLabels.update(camera, labelLimit, innerWidth, innerHeight)
  }
  eraLabels.update() // 时代名位置固定，无需每帧更新（保留接口兼容）

  renderer.render(scene, camera)
}
loop()
