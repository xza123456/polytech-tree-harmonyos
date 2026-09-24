#!/usr/bin/env python3
"""HumanTechTree 鸿蒙工程自检

本机没有 DevEco SDK / hvigor，无法编译，所以用静态检查兜住低级错误：
  1. 所有 .json / .json5 能否解析
  2. 每个 $media: / $string: / $color: / $profile: 引用是否有对应资源
  3. main_pages.json 的页面列表与 EntryAbility.loadContent 是否一致
  4. 分层图标引用的 foreground / background 是否齐全
  5. ArkTS 文件里是否出现被 ArkTS 禁用的语法（any / as / 模板字符串 / 解构 等）
  6. rawfile 站点入口与相对路径是否自洽
退出码非 0 表示有错误。
"""
import json
import os
import re
import sys

# tools/validate_project.py -> 仓库根/app
PROJECT = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), 'app')

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load_json5(path):
    """宽松解析 json5：剥掉行/块注释与尾逗号后按 JSON 解析。"""
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'(^|\s)//[^\n]*', r'\1', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return json.loads(text)


# ───── 1. 配置文件可解析 ─────
print('== 1. 配置文件解析 ==')
configs = []
for base, _dirs, files in os.walk(PROJECT):
    if any(seg in base for seg in ('/build/', '/.hvigor/', '/node_modules/', '/oh_modules/')):
        continue
    for f in files:
        if f.endswith('.json') or f.endswith('.json5'):
            configs.append(os.path.join(base, f))
for c in sorted(configs):
    rel = os.path.relpath(c, PROJECT)
    try:
        load_json5(c)
        print('   ok  ' + rel)
    except Exception as e:
        err('配置解析失败 %s: %s' % (rel, e))

# ───── 2. 资源引用完整性 ─────
print('== 2. 资源引用 ==')


def collect_resource_names(module_dir, kind, element_name):
    """收集某模块下 element/<element_name>.json 里定义的 name 列表。"""
    names = set()
    el = os.path.join(module_dir, 'src/main/resources')
    for base, _dirs, files in os.walk(el):
        for f in files:
            if f == element_name + '.json':
                try:
                    data = load_json5(os.path.join(base, f))
                except Exception:
                    continue
                for item in data.get(kind, []):
                    names.add(item.get('name'))
    return names


def collect_media(module_dir):
    """media 资源：文件名（去掉扩展名）。分层图标的 .json 也算一类资源。"""
    names = set()
    media_dir = os.path.join(module_dir, 'src/main/resources/base/media')
    if os.path.isdir(media_dir):
        for f in os.listdir(media_dir):
            names.add(os.path.splitext(f)[0])
    return names


def collect_profiles(module_dir):
    names = set()
    pdir = os.path.join(module_dir, 'src/main/resources/base/profile')
    if os.path.isdir(pdir):
        for f in os.listdir(pdir):
            names.add(os.path.splitext(f)[0])
    return names


app_scope = os.path.join(PROJECT, 'AppScope')
entry = os.path.join(PROJECT, 'entry')

app_media = set()
for base, _dirs, files in os.walk(os.path.join(app_scope, 'resources')):
    for f in files:
        app_media.add(os.path.splitext(f)[0])
app_strings = set()
for base, _dirs, files in os.walk(os.path.join(app_scope, 'resources')):
    if os.path.basename(base) == 'element':
        for f in files:
            if f.endswith('.json'):
                try:
                    data = load_json5(os.path.join(base, f))
                except Exception:
                    continue
                for item in data.get('string', []):
                    app_strings.add(item.get('name'))

entry_media = collect_media(entry)
entry_strings = collect_resource_names(entry, 'string', 'string')
entry_colors = collect_resource_names(entry, 'color', 'color')
entry_profiles = collect_profiles(entry)

REF = re.compile(r'\$(media|string|color|profile|float):([A-Za-z0-9_]+)')
ref_sources = []
for c in configs:
    rel = os.path.relpath(c, PROJECT)
    try:
        text = open(c, 'r', encoding='utf-8').read()
    except Exception:
        continue
    for m in REF.finditer(text):
        ref_sources.append((rel, m.group(1), m.group(2)))
for rel, kind, name in sorted(set(ref_sources)):
    ok = False
    if kind == 'media':
        ok = name in app_media or name in entry_media
    elif kind == 'string':
        ok = name in app_strings or name in entry_strings
    elif kind == 'color':
        ok = name in entry_colors
    elif kind == 'profile':
        ok = name in entry_profiles
    elif kind == 'float':
        ok = name in collect_resource_names(entry, 'float', 'float')
    print(('   ok  ' if ok else '   !!  ') + '%s -> $%s:%s' % (rel, kind, name))
    if not ok:
        err('资源缺失：%s 引用了 $%s:%s' % (rel, kind, name))

# ───── 3. 入口页与 main_pages 一致 ─────
print('== 3. 入口页一致性 ==')
pages_path = os.path.join(entry, 'src/main/resources/base/profile/main_pages.json')
ability_path = os.path.join(entry, 'src/main/ets/entryability/EntryAbility.ets')
pages = load_json5(pages_path).get('src', [])
ability_src = open(ability_path, 'r', encoding='utf-8').read()
m = re.search(r"loadContent\(\s*'([^']+)'", ability_src)
first = m.group(1) if m else None
print('   main_pages.json = %s' % pages)
print('   loadContent     = %s' % first)
if not first:
    err('EntryAbility 里找不到 loadContent 调用')
elif first not in pages:
    err('loadContent(%s) 不在 main_pages.json 中，会白屏' % first)
for p in pages:
    f = os.path.join(entry, 'src/main/ets', p + '.ets')
    if not os.path.isfile(f):
        err('main_pages.json 声明了 %s，但文件不存在：%s' % (p, f))
    else:
        print('   ok  页面文件存在 %s.ets' % p)

# ───── 4. 分层图标 ─────
print('== 4. 分层图标 ==')
for mod, media in (('AppScope', app_media), ('entry', entry_media)):
    li = os.path.join(PROJECT, mod, 'resources/base/media/layered_image.json')
    if not os.path.isfile(li):
        # entry 的路径是 src/main/resources
        li = os.path.join(PROJECT, mod, 'src/main/resources/base/media/layered_image.json')
    if not os.path.isfile(li):
        warn('%s 没有 layered_image.json' % mod)
        continue
    data = load_json5(li).get('layered-image', {})
    for role in ('background', 'foreground'):
        val = data.get(role, '')
        name = val.split(':')[-1]
        if name in media:
            print('   ok  %s %s -> %s' % (mod, role, name))
        else:
            err('%s 分层图标的 %s 指向 $media:%s，但 media 下没有该资源' % (mod, role, name))

for need in ('startIcon',):
    if need in entry_media:
        print('   ok  entry %s' % need)
    else:
        err('entry 缺少 %s' % need)

# ───── 5. ArkTS 禁用语法扫描 ─────
print('== 5. ArkTS 语法扫描 ==')
BANNED = [
    (re.compile(r':\s*any\b'), 'any 类型'),
    (re.compile(r'\bas\s+[A-Z][A-Za-z0-9_.<>]*'), 'as 类型断言'),
    (re.compile(r'`'), '模板字符串'),
    (re.compile(r'\bconst\s*\{'), '对象解构'),
    (re.compile(r'\bfunction\s*\('), '函数表达式'),
    (re.compile(r'\bfor\s*\(\s*(?:const|let|var)\s+\w+\s+in\b'), 'for...in'),
]
ets_files = []
for base, _dirs, files in os.walk(os.path.join(entry, 'src/main/ets')):
    for f in files:
        if f.endswith('.ets') or f.endswith('.ts'):
            ets_files.append(os.path.join(base, f))
for f in sorted(ets_files):
    rel = os.path.relpath(f, PROJECT)
    text = open(f, 'r', encoding='utf-8').read()
    hits = []
    for rx, label in BANNED:
        for line_no, line in enumerate(text.split('\n'), 1):
            if line.strip().startswith('*') or line.strip().startswith('//'):
                continue
            if rx.search(line):
                hits.append('%s:%d %s' % (rel, line_no, label))
    if hits:
        for h in hits:
            warn('ArkTS 可疑语法 ' + h)
    else:
        print('   ok  ' + rel)

# ───── 6. rawfile 站点 ─────
print('== 6. rawfile 站点 ==')
raw = os.path.join(entry, 'src/main/resources/rawfile')
if not os.path.isdir(raw):
    err('rawfile 目录不存在：%s' % raw)
else:
    index = os.path.join(raw, 'index.html')
    if not os.path.isfile(index):
        err('rawfile 里没有 index.html')
    else:
        html = open(index, 'r', encoding='utf-8').read()
        # resource:// 下页面 origin 为 null，Chromium 会以 CORS 模式去取 module 脚本，
        # 而允许跨域的 scheme 白名单里没有 resource://，所以只要出现 module 脚本就白屏。
        if re.search(r'<script[^>]*type="module"', html):
            err('index.html 含 type="module" 脚本：resource:// 下会被 CORS 拦截导致白屏')
        else:
            print('   ok  无 module 脚本（绕开了 resource:// 的 CORS 限制）')
        if 'importmap' in html:
            warn('index.html 里还有 import map，单文件方案下不需要')
        local_refs = [m for m in re.findall(r'(?:src|href)="([^"]+)"', html)
                      if not m.startswith(('http', 'data:', '#'))]
        if local_refs:
            err('index.html 仍有本地外部引用，resource:// 下取不到：%s' % local_refs)
        else:
            print('   ok  自包含：零本地外部引用')
        if html.count('<style>') < 1 or html.count('<script>') < 1:
            err('index.html 缺少内联的 style / script 块')
        else:
            print('   ok  内联样式与脚本就位')
        for marker, label in (('globalThis.THREE', 'three 运行时'),
                              ('__def(', '应用模块')):
            if marker in html:
                print('   ok  %s 已内联' % label)
            else:
                err('index.html 里找不到 %s，打包可能不完整' % marker)
    n_files = sum(len(fs) for _b, _d, fs in os.walk(raw))
    size = sum(os.path.getsize(os.path.join(b, f))
               for b, _d, fs in os.walk(raw) for f in fs)
    print('   rawfile: %d 个文件, %.1f MB' % (n_files, size / 1048576.0))

# ───── 汇总 ─────
print('')
print('== 结果 ==')
for w in warnings:
    print('警告: ' + w)
for e in errors:
    print('错误: ' + e)
if not errors:
    print('通过：%d 项检查无错误，%d 条警告' % (len(configs) + len(ets_files) + 4, len(warnings)))
sys.exit(1 if errors else 0)
