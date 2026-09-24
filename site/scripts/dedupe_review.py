# -*- coding: utf-8 -*-
"""
生成"去重复核队列"：把历史上按 wikiEn 主键做的跨 id 自动合并逐对摊开比较。

被吞条目的原始记录仍留在 data/research/*.json，保留条目以 data/techs.json 为准，
因此可以机械判定可疑度：era 不同 / category 不同 / 年份差 > 100 都视为"可能不该合并"
（规范 §3.7 说这类要算不同代际、应收两条并用 prereqs 相连）。

用法: python scripts/dedupe_review.py
输出: data/dedupe-review-queue.json + 控制台摘要
"""
import glob
import io
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")


def main():
    techs = {t["id"]: t for t in json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))}
    report = json.load(io.open(os.path.join(D, "merge-report.json"), encoding="utf-8"))
    src = {}
    for f in sorted(glob.glob(os.path.join(D, "research", "*.json"))):
        data = json.load(io.open(f, encoding="utf-8"))
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and x.get("id") and x["id"] not in src:
                    src[x["id"]] = x

    queue = []
    for m in report["autoMerges"]:
        if m["reason"] != "wikiEn" or m["into"] == m["from"]:
            continue
        gone = src.get(m["from"])
        kept = techs.get(m["into"])
        if not (gone and kept):
            continue
        flags = []
        if gone.get("era") != kept.get("era"):
            flags.append(f"era 不同({gone.get('era')}→{kept.get('era')})")
        if gone.get("category") != kept.get("category"):
            flags.append("category 不同")
        gy, ky = gone.get("year") or 0, kept.get("year") or 0
        if abs(gy - ky) > 100:
            flags.append(f"年份差 {abs(gy - ky)}")
        queue.append({
            "suspect": bool(flags), "flags": flags,
            "swallowed_id": m["from"], "swallowed_name": gone.get("name"),
            "swallowed_desc": gone.get("desc"), "swallowed_year": gy,
            "kept_id": m["into"], "kept_name": kept.get("name"),
            "kept_desc": kept.get("desc"), "kept_year": ky,
            "wikiEn": kept.get("wikiEn"), "batch": m.get("batch"),
        })

    queue.sort(key=lambda x: (-len(x["flags"]), x["kept_id"]))
    susp = [q for q in queue if q["suspect"]]
    print(f"跨 id 的 wikiEn 自动合并共 {len(queue)} 次，其中带可疑标记 {len(susp)} 次")
    print("\n可疑清单（被吞条目 vs 保留条目）")
    for q in susp:
        print(f"\n  [{', '.join(q['flags'])}]")
        print(f"    被吞: {q['swallowed_id']:<28} {q['swallowed_year']:>7} {q['swallowed_name']}｜{q['swallowed_desc'][:34]}")
        print(f"    保留: {q['kept_id']:<28} {q['kept_year']:>7} {q['kept_name']}｜{q['kept_desc'][:34]}")

    dups = defaultdict(list)
    for t in techs.values():
        if t.get("wikiEn"):
            dups[t["wikiEn"].lower()].append(t["id"])
    live = {k: v for k, v in dups.items() if len(v) > 1}
    print(f"\n现存库内 wikiEn 重复组 {len(live)} 组：{live}")
    json.dump({"cross_id_wikien_merges": queue, "suspect_count": len(susp),
               "live_duplicate_titles": live},
              io.open(os.path.join(D, "dedupe-review-queue.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("已写 data/dedupe-review-queue.json")


if __name__ == "__main__":
    main()
