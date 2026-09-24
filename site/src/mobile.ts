/**
 * 手机窄屏适配层（配合 mobile.css）
 *
 * 上游 UI 与取景都是按宽屏写的，窄屏下有三类问题，分别在这一层收掉：
 *   1. 面板全是 fixed 定位且尺寸写死 → 挤在一起          （由 mobile.css 重排）
 *   2. 图例默认展开、名称上限默认 100 → 小屏上糊成一团    （这里收紧）
 *   3. 操作提示写的是"滚轮缩放 / 右键平移" → 触摸设备上这些操作根本不存在（这里改写）
 *
 * 取景（相机视距）的宽高比补偿在 layout.ts 的 startViewDistance() 里，
 * 因为那个函数是 scene / controls / tour 三处取景的共同入口。
 */

const NARROW_MAX_W = 640

/** 窄屏默认名称上限：宽屏的 100 个名字在 390px 宽的画面里会互相压住 */
const NARROW_LABEL_LIMIT = 36

export interface MobileHooks {
  legend: HTMLElement
  hint: HTMLElement
}

export function isNarrowScreen(): boolean {
  return window.innerWidth < NARROW_MAX_W
}

/** 触摸优先设备：决定操作提示怎么写 */
function isTouchPrimary(): boolean {
  return navigator.maxTouchPoints > 0
}

let narrowApplied = false

/** 幂等：跨断点后可以重复调用 */
export function applyMobileLayout(hooks: MobileHooks): void {
  const narrow = isNarrowScreen()

  if (narrow && !narrowApplied) {
    narrowApplied = true

    hooks.legend.classList.add('collapsed')
    const toggle = document.getElementById('legendToggle')
    if (toggle) toggle.textContent = '▸'

    // 名称上限：走 input 事件而不是直接改，才能同步 main.ts 里的 labelLimit
    const range = document.getElementById('labelLimitRange') as HTMLInputElement | null
    const value = document.getElementById('labelLimitValue')
    if (range && Number(range.value) > NARROW_LABEL_LIMIT) {
      range.value = String(NARROW_LABEL_LIMIT)
      if (value) value.textContent = String(NARROW_LABEL_LIMIT)
      range.dispatchEvent(new Event('input'))
    }
  }

  if (isTouchPrimary()) {
    hooks.hint.textContent = '单指旋转 · 双指缩放 / 平移 · 拖动查看节点'
  } else if (narrow) {
    hooks.hint.textContent = '拖拽旋转 · 滚轮缩放 · 悬停查看节点'
  }
}

/**
 * 宽↔窄跨断点时回调。
 * 折叠屏开合、手机横竖切换都会跨过断点，此时需要重新取景，
 * 否则会留着上一套宽高比算出来的视距，塔要么满出画面要么缩成一小团。
 */
export function watchBreakpoint(onChange: (narrow: boolean) => void): void {
  let wasNarrow = isNarrowScreen()
  window.addEventListener('resize', () => {
    const nowNarrow = isNarrowScreen()
    if (nowNarrow !== wasNarrow) {
      wasNarrow = nowNarrow
      onChange(nowNarrow)
    }
  })
}
