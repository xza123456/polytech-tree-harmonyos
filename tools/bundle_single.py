#!/usr/bin/env python3
"""把 dist/ 的 ESM 站点打成单个自包含 HTML。

动机：ArkWeb 用 $rawfile 加载页面时走 resource:// 协议，页面 origin 为 null，
Chromium 对 <script type="module"> 一律按 CORS 模式取脚本，
而允许跨域的 scheme 白名单里没有 resource://，于是入口脚本 ERR_FAILED，
JS 一行都不执行（实测日志：Access to script at 'resource://rawfile/src/main.js'
from origin 'null' has been blocked by CORS policy）。

对策：不再依赖任何模块加载 —— three、OrbitControls、8 个应用模块和 3 个数据模块
全部拼进一个经典 <script>，HTML/CSS 一并内联，页面零外部请求，CORS 无从触发。

转换规则（针对 tsc 产出的、形式可控的 ESM）：
  import * as N from 'x'      -> const N = __req('x')
  import { a, b } from 'x'    -> const { a, b } = __req('x')
  import D from 'x'           -> const D = __req('x').default
  import { a } from 'x';      (多行也支持)
  export const/function/class -> 去掉 export，名字记入导出表
  export { a, b }             -> 删掉，名字记入导出表
  export default E            -> 模块返回 { default: E }
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, '..', 'build', 'dist')            # build.mjs 的产物
OUT_DIR = os.path.join(BASE, '..', 'build', 'dist-single')  # 中间产物（已 gitignore）
OUT_HTML = os.path.join(OUT_DIR, 'index.html')

warnings = []


def read(rel):
    with open(os.path.join(DIST, rel), 'r', encoding='utf-8') as f:
        return f.read()


def resolve(vpath, spec):
    """把导入说明符解析成虚拟路径（裸说明符原样保留）。"""
    if not spec.startswith('.'):
        return spec
    base_dir = os.path.dirname(vpath)
    return os.path.normpath(os.path.join('/', base_dir, spec)).lstrip('/')


RE_NAMED = re.compile(r"import\s*\{([\s\S]*?)\}\s*from\s*['\"]([^'\"]+)['\"]\s*;")
RE_NS = re.compile(r"import\s*\*\s*as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]\s*;")
RE_DEFAULT = re.compile(r"import\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]\s*;")
RE_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}\s*;?\s*$", re.M)
RE_EXPORT_DECL = re.compile(
    r"^export\s+(const|let|var|function|class|async\s+function)\s+(\w+)", re.M)


def transform_module(vpath, code):
    """ESM -> 模块函数体。返回 (deps, exports, body)。"""
    deps = []
    exports = []

    def named(m):
        names = ' '.join(m.group(1).split())
        target = resolve(vpath, m.group(2))
        deps.append(target)
        return 'const { %s } = __req(%s);' % (names, json.dumps(target))

    def namespace(m):
        target = resolve(vpath, m.group(2))
        deps.append(target)
        return 'const %s = __req(%s);' % (m.group(1), json.dumps(target))

    def default(m):
        target = resolve(vpath, m.group(2))
        deps.append(target)
        return 'const %s = __req(%s).default;' % (m.group(1), json.dumps(target))

    code = RE_NAMED.sub(named, code)
    code = RE_NS.sub(namespace, code)
    code = RE_DEFAULT.sub(default, code)

    def export_list(m):
        for n in m.group(1).split(','):
            n = n.strip()
            if n:
                exports.append(n)
        return ''

    code = RE_EXPORT_LIST.sub(export_list, code)

    def export_decl(m):
        exports.append(m.group(2))
        return '%s %s' % (m.group(1), m.group(2))

    code = RE_EXPORT_DECL.sub(export_decl, code)

    # 残留的 import/export 说明还有没覆盖到的形式，必须显式报错而不是悄悄放过
    leftover = [l for l in code.split('\n')
                if re.match(r'^\s*(import|export)\b', l)]
    if leftover:
        raise SystemExit('%s 还有未处理的 import/export：\n  %s'
                         % (vpath, '\n  '.join(leftover[:5])))

    return deps, exports, code


def module_js(vpath, code):
    deps, exports, body = transform_module(vpath, code)
    ret = ', '.join('%s: %s' % (n, n) for n in exports)
    return "/* ---- %s ---- */\n__def(%s, function () {\n%s\nreturn { %s };\n});\n" % (
        vpath, json.dumps(vpath), body, ret)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ───── 1. three：把末尾的 export {...} 改成挂到 globalThis ─────
    three = read('vendor/three.module.js')
    if re.search(r'^import\b', three, re.M):
        raise SystemExit('three.module.js 竟然含 import，需要人工处理')
    three_new, n_three = re.subn(r"^export\s*\{([\s\S]*?)\}\s*;\s*$",
                                 r"globalThis.THREE = {\1};", three, flags=re.M)
    if n_three != 1:
        raise SystemExit('three.module.js 的 export 语句定位失败（匹配 %d 次）' % n_three)
    three_bundle = '(function () {\n"use strict";\n%s\n})();\n' % three_new

    # ───── 2. OrbitControls：从全局取 THREE，把类挂到全局 ─────
    orbit = read('vendor/jsm/controls/OrbitControls.js')
    orbit, n_imp = re.subn(r"import\s*\{([\s\S]*?)\}\s*from\s*['\"]three['\"]\s*;",
                           r"const {\1} = globalThis.THREE;", orbit)
    if n_imp != 1:
        raise SystemExit('OrbitControls 的 import 定位失败（匹配 %d 次）' % n_imp)
    orbit, n_exp = re.subn(r"^export\s*\{\s*OrbitControls\s*\}\s*;?\s*$",
                           'globalThis.__ORBIT = OrbitControls;', orbit, flags=re.M)
    if n_exp != 1:
        raise SystemExit('OrbitControls 的 export 定位失败（匹配 %d 次）' % n_exp)
    orbit_bundle = '(function () {\n"use strict";\n%s\n})();\n' % orbit

    # ───── 3. 数据模块：export default E -> { default: E } ─────
    data_parts = []
    for name in ('techs', 'eras', 'categories'):
        src = read('data/%s.js' % name)
        prefix = 'export default '
        if not src.startswith(prefix):
            raise SystemExit('data/%s.js 不是预期的 export default 形式' % name)
        expr = src[len(prefix):].rstrip()
        if expr.endswith(';'):
            expr = expr[:-1]
        data_parts.append('__def("data/%s.js", function () { return { default: %s }; });'
                          % (name, expr))

    # ───── 4. 应用模块（自动发现：新增 .ts 后不用回来改这里。
    #           顺序无关 —— __def 只登记，__req 才求值） ─────
    src_dir = os.path.join(DIST, 'src')
    app_names = sorted(n[:-3] for n in os.listdir(src_dir) if n.endswith('.js'))
    app_parts = [module_js('src/%s.js' % n, read('src/%s.js' % n)) for n in app_names]

    # ───── 5. 运行时 + 顺序 ─────
    runtime = """
var __defs = {};
var __cache = {};
function __def(name, fn) { __defs[name] = fn; }
function __req(name) {
  if (Object.prototype.hasOwnProperty.call(__cache, name)) return __cache[name];
  var fn = __defs[name];
  if (!fn) throw new Error('模块未找到: ' + name);
  var exp = {};
  __cache[name] = exp;
  var r = fn();
  if (r) {
    for (var k in r) {
      if (Object.prototype.hasOwnProperty.call(r, k)) exp[k] = r[k];
    }
  }
  return exp;
}
__def('three', function () { return globalThis.THREE; });
__def('three/examples/jsm/controls/OrbitControls.js',
      function () { return { OrbitControls: globalThis.__ORBIT }; });
"""

    script = '\n'.join([
        three_bundle, orbit_bundle, runtime,
        '\n'.join(data_parts), '\n'.join(app_parts),
        '__req("src/main.js");',
    ])

    # ───── 6. 内联进 HTML ─────
    css = read('src/style.css')
    mobile_css_path = os.path.join(DIST, 'src/mobile.css')
    if os.path.isfile(mobile_css_path):
        css += '\n\n/* ===== 手机窄屏适配（独立层，见 src/mobile.css） ===== */\n' + read('src/mobile.css')
    html = read('index.html')
    html = html.replace('  <link rel="stylesheet" href="./src/style.css" />\n', '')
    html = html.replace('  <link rel="stylesheet" href="./src/mobile.css" />\n', '')
    html = re.sub(r'\s*<script type="importmap">[\s\S]*?</script>\n', '\n', html)
    html = html.replace('</head>', '  <style>\n%s\n  </style>\n</head>' % css)
    html = html.replace(
        '<script type="module" src="./src/main.js"></script>',
        '<script>\n%s\n</script>' % script)

    # 内联脚本里出现 </script 会提前结束脚本块；<!-- 会触发 HTML 注释规则
    if '</script' in script:
        warnings.append('脚本里含 </script 字面量，已转义')
        script_escaped = script.replace('</script', '<\\/script')
        html = html.replace('<script>\n%s\n</script>' % script,
                            '<script>\n%s\n</script>' % script_escaped)
    if '<!--' in script:
        warnings.append('脚本里含 <!-- 字面量，需留意 HTML 注释规则')

    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    # 顺带把脚本单独落一份，方便 node --check 做语法校验
    with open(os.path.join(OUT_DIR, 'bundle.js'), 'w', encoding='utf-8') as f:
        f.write(script)

    size = os.path.getsize(OUT_HTML)
    print('生成 %s' % OUT_HTML)
    print('  单文件 %.2f MB（内联脚本 %.2f MB）'
          % (size / 1048576.0, len(script.encode('utf-8')) / 1048576.0))
    print('  模块数: three + OrbitControls + 3 数据 + 9 应用')
    for w in warnings:
        print('  警告: ' + w)
    return 0


if __name__ == '__main__':
    sys.exit(main())
