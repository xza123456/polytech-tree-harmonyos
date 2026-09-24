# -*- coding: utf-8 -*-
"""
N-02：给"只在自己域内连线"的条目补跨群边——只承认有文本证据的边。

为什么不用模型选前置：link_isolated.py 的实测教训是，候选池里没有真前置时模型会硬凑
（tattoo←hat、lighthouse←canal），假依赖比没有依赖更糟。

本步的证据来源是**条目自己的 desc**：desc 里点名了另一条科技的中文名/别名，
就说明我们自己在描述里断言了这层关系，把它记成 `related`（不是 prereqs，避免伪造因果方向）。

约束：只连已存在的 id；不加自环；`related` 满 4 条就不加（规范 §3.5 上限）；
优先连到不同域群的条目（这正是本步要解决的问题）。

用法: python scripts/link_by_mention.py            # 干跑，打印将新增的边与样本
      python scripts/link_by_mention.py --apply
产物: data/mention-links.json（逐条边 + 命中文本，可审计可回退）
"""
import io
import atomic
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUT = os.path.join(D, "mention-links.json")
MAX_RELATED = 4
MIN_LEN = 3          # 短于此的中文名会大量误命中（"灯""桥"）


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.load(io.open(TECHS, encoding="utf-8"))
    cats = {c["id"]: c["group"] for c in json.load(io.open(os.path.join(D, "categories.json"), encoding="utf-8"))}
    by = {t["id"]: t for t in techs}

    # 名字 → id 索引（含别名）。歧义名（一个名字对应多条）直接放弃，宁缺毋滥。
    name_to_ids = defaultdict(set)
    for t in techs:
        for n in [t.get("name")] + (t.get("aliases") or []):
            n = (n or "").strip()
            if len(n) >= MIN_LEN and re.search(r"[一-鿿]", n):
                name_to_ids[n].add(t["id"])
    # 停用词：时代名与域名同时也是条目名（"旧石器"既是 stone_tools 的中文名也是 era 名），
    # desc 里出现它们是在说年代，不是在指向那条科技。
    stop = set()
    for e in json.load(io.open(os.path.join(D, "eras.json"), encoding="utf-8")):
        stop.add(e["name"])
    for c in json.load(io.open(os.path.join(D, "categories.json"), encoding="utf-8")):
        stop.add(c["name"])
    uniq = {n: i for n, i in ((n, next(iter(ids))) for n, ids in name_to_ids.items() if len(ids) == 1)
            if n not in stop}

    edges = []
    for t in techs:
        desc = t.get("desc") or ""
        if len(t.get("related") or []) >= MAX_RELATED:
            continue
        have = set(t.get("related") or []) | set(t.get("prereqs") or []) | {t["id"]}
        cands = []
        for n, tid in uniq.items():
            if tid in have or cats.get(by[tid]["category"]) == cats.get(t["category"]):
                continue
            if n in desc:
                cands.append((tid, n))
        for tid, n in sorted(cands, key=lambda x: -len(x[1]))[: MAX_RELATED - len(t.get("related") or [])]:
            edges.append({"from": t["id"], "to": tid, "evidence": n,
                          "from_cat": t["category"], "to_cat": by[tid]["category"]})
    # 同一对不重复；且只保留"互为提及"里最长证据的一条
    seen, final = set(), []
    for e in edges:
        k = (e["from"], e["to"])
        if k in seen:
            continue
        seen.add(k)
        final.append(e)

    by_from = defaultdict(list)
    for e in final:
        by_from[e["from"]].append(e)
    print(f"文本证据可支撑的跨群 related 边：{len(final)} 条，覆盖 {len(by_from)} 个条目")
    for e in final[:12]:
        print(f"  {e['from']:<30} --提及\"{e['evidence']}\"--> {e['to']:<28} ({e['from_cat']}→{e['to_cat']})")

    def cross_rate(items):
        tot = cross = 0
        for x in items:
            for r in (x.get("prereqs") or []) + (x.get("related") or []):
                o = by.get(r)
                if not o:
                    continue
                tot += 1
                if cats.get(o["category"]) != cats.get(x["category"]):
                    cross += 1
        return cross, tot, (cross / tot * 100 if tot else 0)

    grp = defaultdict(list)
    for t in techs:
        grp[cats[t["category"]]].append(t)
    print("\n改前各群跨群边率：")
    for g in "ABCD":
        c, tt, p = cross_rate(grp[g])
        print(f"  {g} 群: {c}/{tt} = {p:.1f}%")
    math = [t for t in techs if t["category"] == "math_pure"]
    c, tt, p = cross_rate(math)
    print(f"  math_pure: {c}/{tt} = {p:.1f}%")

    json.dump(final, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not apply_changes:
        print("\n（干跑。--apply 写入 related。明细 data/mention-links.json）")
        return
    for e in final:
        t = by[e["from"]]
        if len(t.get("related") or []) < MAX_RELATED:
            t["related"] = sorted(set((t.get("related") or []) + [e["to"]]))
    atomic.write_atomic(TECHS, 
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    grp2 = defaultdict(list)
    for t in techs:
        grp2[cats[t["category"]]].append(t)
    print("改后跨群边率：")
    for g in "ABCD":
        c, tt, p = cross_rate(grp2[g])
        print(f"  {g} 群: {c}/{tt} = {p:.1f}%")
    c, tt, p = cross_rate([t for t in techs if t["category"] == "math_pure"])
    print(f"  math_pure: {c}/{tt} = {p:.1f}%")


if __name__ == "__main__":
    main()
