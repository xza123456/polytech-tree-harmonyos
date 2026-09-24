# -*- coding: utf-8 -*-
"""
F7 局部修复（2026-09-21）：

 ① 时间倒挂的 prereqs → 降级为 related。前置依赖在时间上晚于本条不可能是依赖，
    但它们确实相关，删掉会丢信息，故移到 related。
 ② 同名不同代条目按规范 §3.2 加消歧后缀（这些重复是 §3.7 的四个去重键都没抓到的）。
 ③ 顺带把 `kind` 字段按 §3.1 补上：先给可机械判定的四类，其余留"工艺"由 F4 统一复核。

用法: python scripts/fix_edges_and_names.py            # 干跑
      python scripts/fix_edges_and_names.py --apply
"""
import io
import atomic
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")

# ② 消歧：id -> 新中文名（保留更"通称"的那条不改）
RENAMES = {
    "lacquer": "天然漆（大漆）",
    "jacquard_loom": "雅卡尔提花机",
    "hierapolis_sawmill": "希拉波利斯水力锯坊",
    "teletype_model_33": "电传终端 Model 33",
}
# ③ kind 副轴的机械判定（规范 §3.3）：命中即定档，未命中不猜
KIND_RULES = [
    ("制度", re.compile(r"制度|法则|律法|条约|章程|专利|许可|组织|考试|科举|学会|标准|协议|规范|市场|银行|保险|货币体系")),
    ("原理", re.compile(r"定律|定理|学说|原理|理论|方程|公理|猜想|判据|不等式|恒等式|法则|博弈论|代数$|几何$|分析$")),
    ("媒介", re.compile(r"文字|字母|书写|纸|印刷|书籍|报刊|图书馆|电报|电话|广播|电视|互联网|协议|编码")),
    ("器物", re.compile(r"机|器|车|船|船|钟|表|仪|具|装置|设备|炉|灶|轮|箭|炮|弹|电话|灯|管线|桥|坝|隧道|轨道|芯片|电路")),
]


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    by = {t["id"]: t for t in techs}

    moved = []
    for t in techs:
        keep, demote = [], []
        for p in t.get("prereqs") or []:
            o = by.get(p)
            if o and o["year"] > t["year"]:
                demote.append(p)
            else:
                keep.append(p)
        if demote:
            moved.append((t["id"], t["year"], demote))
            if apply_changes:
                t["prereqs"] = sorted(keep)
                t["related"] = sorted(set((t.get("related") or []) + demote) - {t["id"]})

    renamed = []
    for rid, new in RENAMES.items():
        t = by.get(rid)
        if not t:
            print(f"! 找不到 {rid}")
            continue
        renamed.append((rid, t["name"], new))
        if apply_changes:
            t["name"] = new

    kinds = {}
    if apply_changes:
        for t in techs:
            if t.get("kind") in {"原理", "工艺", "器物", "制度", "媒介"}:
                kinds[t["kind"] + "(沿用批次自填)"] = kinds.get(t["kind"] + "(沿用批次自填)", 0) + 1
                continue
            k = "工艺"
            for cand, rx in KIND_RULES:
                if any(rx.search(w) for w in [t.get("name") or "", t.get("desc") or ""]):
                    k = cand
                    break
            t["kind"] = k
            kinds[k] = kinds.get(k, 0) + 1

    print(f"① 时间倒挂 prereq → related：{len(moved)} 条")
    for rid, y, ds in moved:
        print(f"    {rid:<34} year={y:>6} 降级 {ds}")
    print(f"② 消歧改名：{len(renamed)} 条")
    for rid, old, new in renamed:
        print(f"    {rid:<24} {old} → {new}")
    if apply_changes:
        out = json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else "")
        atomic.write_atomic(TECHS, out)
        print(f"③ kind 字段已按规则赋值：{kinds}")
        print("已写入 data/techs.json")
    else:
        print("\n（干跑。--apply 写入。）")


if __name__ == "__main__":
    main()
