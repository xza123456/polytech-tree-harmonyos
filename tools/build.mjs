// 在无 esbuild/rollup 原生二进制的环境下（OpenHarmony arm64）本地运行 polytech-tree：
// tsc 编译 TS -> ESM JS，JSON 转成 JS 模块，three 走 import map，最后用静态服务器托管。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

// 一切相对本脚本定位，仓库 clone 到任何路径都能跑
const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '../site')          // 上游站点源码
const OUT = path.resolve(HERE, '../build/dist')     // 中间产物（已 gitignore）

const rm = p => fs.rmSync(p, { recursive: true, force: true })
const mk = p => fs.mkdirSync(p, { recursive: true })
const cp = (a, b) => { mk(path.dirname(b)); fs.copyFileSync(a, b) }

rm(OUT)
mk(OUT)

// ── 1. tsc 编译（tsconfig.build.json，纯 JS 实现，不需要原生二进制） ──
console.log('[1/5] tsc 编译 src/*.ts')
execFileSync(path.join(REPO, 'node_modules/.bin/tsc'), ['-p', 'tsconfig.build.json'], {
  cwd: HERE,
  stdio: 'inherit',
})

// ── 2. data/*.json -> data/*.js（浏览器 ESM 不能直接 import 裸 JSON） ──
console.log('[2/5] data/*.json -> data/*.js')
const jsonFiles = ['techs.json', 'eras.json', 'categories.json']
for (const f of jsonFiles) {
  const raw = fs.readFileSync(path.join(REPO, 'data', f), 'utf8')
  const js = `export default ${JSON.stringify(JSON.parse(raw))};\n`
  fs.writeFileSync(path.join(OUT, 'data', f.replace(/\.json$/, '.js')), js)
}
// tsc 的 resolveJsonModule 会把 src 引用到的 data/*.json 一并 emit 出来，
// 但运行时只加载上面生成的 .js 版本，留着重约 1.5MB 的无用副本。
for (const f of fs.readdirSync(path.join(OUT, 'data'))) {
  if (f.endsWith('.json')) fs.unlinkSync(path.join(OUT, 'data', f))
}

// ── 3. 改写 import 说明符，让它符合浏览器 ESM 规则 ──
console.log('[3/5] 修补 import 说明符')
const srcDir = path.join(OUT, 'src')
for (const f of fs.readdirSync(srcDir).filter(n => n.endsWith('.js'))) {
  const p = path.join(srcDir, f)
  let code = fs.readFileSync(p, 'utf8')
  code = code.replace(/^\s*import\s+(['"])\.\/style\.css\1;?\s*$/m, '')
  code = code.replace(/from\s+(['"])(\.[^'"]*)\1/g, (m, q, spec) => {
    const last = spec.split('/').pop()
    if (last.endsWith('.json')) return `from ${q}${spec.slice(0, -5)}.js${q}`
    return last.includes('.') ? m : `from ${q}${spec}.js${q}`
  })
  fs.writeFileSync(p, code)
}

// ── 4. three 与 OrbitControls 作为静态资源 ──
console.log('[4/5] 拷贝 three 运行时')
cp(path.join(REPO, 'node_modules/three/build/three.module.js'), path.join(OUT, 'vendor/three.module.js'))
cp(path.join(REPO, 'node_modules/three/examples/jsm/controls/OrbitControls.js'), path.join(OUT, 'vendor/jsm/controls/OrbitControls.js'))

// ── 5. index.html（加 import map + 独立 CSS）+ style.css + mobile.css ──
console.log('[5/5] 生成 index.html / style.css / mobile.css')
cp(path.join(REPO, 'src/style.css'), path.join(OUT, 'src/style.css'))
// 手机窄屏适配：独立一层，不混进上游 style.css 里，便于以后跟上游对账
const mobileCss = path.join(REPO, 'src/mobile.css')
const hasMobileCss = fs.existsSync(mobileCss)
if (hasMobileCss) cp(mobileCss, path.join(OUT, 'src/mobile.css'))
const cssLinks = hasMobileCss
  ? '  <link rel="stylesheet" href="./src/style.css" />\n  <link rel="stylesheet" href="./src/mobile.css" />'
  : '  <link rel="stylesheet" href="./src/style.css" />'
let html = fs.readFileSync(path.join(REPO, 'index.html'), 'utf8')
const head = `${cssLinks}
  <script type="importmap">
    {
      "imports": {
        "three": "./vendor/three.module.js",
        "three/examples/jsm/": "./vendor/jsm/"
      }
    }
  </script>`
if (!/<script type="module" src="\/src\/main\.ts">/.test(html)) throw new Error('未找到预期的入口 script 标签')
html = html.replace('</head>', `${head}\n</head>`)
html = html.replace('<script type="module" src="/src/main.ts"></script>', '<script type="module" src="./src/main.js"></script>')
fs.writeFileSync(path.join(OUT, 'index.html'), html)

// ── 静态校验：dist 里所有相对 import 都必须能落到真实文件 ──
const missing = []
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
  e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)])
for (const f of walk(OUT).filter(p => p.endsWith('.js'))) {
  const code = fs.readFileSync(f, 'utf8')
  for (const m of code.matchAll(/(?:from|import)\s*\(?\s*(['"])(\.[^'"]*)\1/g)) {
    const t = path.resolve(path.dirname(f), m[2])
    if (!fs.existsSync(t)) missing.push(`${path.relative(OUT, f)} -> ${m[2]}`)
  }
}
if (missing.length) {
  console.error('存在无法解析的相对 import：\n' + missing.join('\n'))
  process.exit(1)
}

const total = walk(OUT)
console.log(`\n完成：${total.length} 个文件 -> ${OUT}`)
for (const f of total.filter(p => /\.(js|css|html)$/.test(p))) {
  console.log(`  ${String(fs.statSync(f).size).padStart(9)}  ${path.relative(OUT, f)}`)
}
