# -*- coding: utf-8 -*-
"""
N-02 边的承载器：读 data/edge-patches/*.json，校验后把跨群边打进 techs.json。

为什么要有这一步：techs.json 是流水线产物，任何直接改图的边都会在下次重建时消失。
调研/接线类工作必须落成**可重放的输入文件**，由本步统一应用并校验。

补丁格式（每个文件一个数组）：
  [{"id":"euclidean_algorithm","add_prereqs":["positional_numeral"],
    "add_related":["cryptography_rsa"],"reason":"辗转相除依赖位值记数的除法运算；后用于 RSA"}]

校验规则（不满足就丢弃该条边并计数，绝不静默改写）：
  1) 端点 id 必须存在于当前库；2) 不自环；3) prereqs/related 各 ≤4（规范 §3.5）；
  4) prereq 必须早于本条（时间上不可能晚于自己）；5) 去重。

用法: python scripts/apply_edge_patches.py            # 干跑
      python scripts/apply_edge_patches.py --apply
"""
import glob
import io
import atomic
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
PATCH_DIR = os.path.join(D, "edge-patches")
MAX_EDGES = 4


def main():
    apply_changes = "--apply" in sys.argv
    files = sorted(glob.glob(os.path.join(PATCH_DIR, "*.json")))
    if not files:
        print("无 edge-patches 输入，跳过")
        return
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.load(io.open(TECHS, encoding="utf-8"))
    by = {t["id"]: t for t in techs}
    drops = Counter()
    applied = 0
    for f in files:
        try:
            patches = json.load(io.open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! 跳过无法解析 {os.path.basename(f)}：{e!r}")
            continue
        for p in patches:
            t = by.get(p.get("id"))
            if not t:
                drops["引用了不存在的主体 id"] += 1
                continue
            for key in ("add_prereqs", "add_related"):
                for tgt in p.get(key) or []:
                    o = by.get(tgt)
                    if not o or tgt == t["id"]:
                        drops["目标不存在或自环"] += 1
                        continue
                    cur = list(t.get(key[4:]) or [])
                    if tgt in cur:
                        continue
                    if len(cur) >= MAX_EDGES:
                        drops[f"{key[4:]} 已满 4 条"] += 1
                        continue
                    if key == "add_prereqs" and o["year"] > t["year"]:
                        drops["prereq 年份晚于本条，拒收"] += 1
                        continue
                    applied += 1
                    if apply_changes:
                        t[key[4:]] = sorted(cur + [tgt])
    print(f"edge-patches：{len(files)} 个文件，落边 {applied} 条，拒收 {dict(drops)}")
    if not apply_changes:
        print("（干跑。--apply 写入。）")
        return
    atomic.write_atomic(TECHS, 
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    print(f"已写入 {TECHS}")


if __name__ == "__main__":
    main()
