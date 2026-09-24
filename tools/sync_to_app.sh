#!/bin/sh
# 重新生成科技树站点并同步进鸿蒙应用的 rawfile，最后跑工程自检。
#
#   node build.mjs        上游 TS 源码 -> dist/（ESM，用于浏览器调试）
#   bundle_single.py      dist/ -> dist-single/index.html（单文件，给 ArkWeb 用）
#   cp -> rawfile         resource:// 下不能加载 module 脚本，必须用自包含单文件
#
# 用法：sh sync_to_app.sh
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
RAW="$ROOT/app/entry/src/main/resources/rawfile"

cd "$HERE"

echo "[1/4] tsc 编译站点 -> dist/"
node build.mjs

echo "[2/4] 打包自包含单文件 -> dist-single/index.html"
python3 bundle_single.py

echo "[3/4] 同步进 rawfile"
rm -rf "$RAW"
mkdir -p "$RAW"
cp "$ROOT/build/dist-single/index.html" "$RAW/index.html"
ls -lh "$RAW/index.html" | awk '{print "      " $5, $NF}'

echo "[4/4] 工程自检"
python3 "$HERE/validate_project.py"

echo ""
echo "完成。在 DevEco Studio 里重新 Run 即可看到新内容。"
