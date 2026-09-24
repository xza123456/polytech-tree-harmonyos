# -*- coding: utf-8 -*-
"""
为 F11 的"合并代际闸门"备料：把历史上按 wikiEn 做的跨 id 合并逐对摊开，
算出**合并当时就能拿到的特征**，供人工判定与阈值校准用。

特征（不含任何"事后才知道"的信息）：
  d_year        年份差绝对值
  d_era         era 序号差绝对值
  era_diff      era 是否不同
  cat_diff      category 是否不同
  name_same     中文名是否相同
  desc_jaccard  desc 的汉字 2-gram Jaccard 相似度
  proto_word    任一侧 desc/name 含"前身|雏形|早期|原型|首次提出|理论"等代际标志词
  imp_diff      重要度差
输出 data/gate-features.json（labels 字段留空，由人工填）
"""
import glob
import io
import json
import os
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
PROTO_WORDS = ["前身", "雏形", "早期", "原型", "理论", "学说", "首", "雏形", "尝试", "概念"]


def grams(s):
    s = "".join(ch for ch in (s or "") if "\u4e00" <= ch <= "\u9fff")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a, b):
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def main():
    eras = json.load(io.open(os.path.join(D, "eras.json"), encoding="utf-8"))
    eidx = {e["id"]: i for i, e in enumerate(eras)}
    techs = {t["id"]: t for t in json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))}
    rep = json.load(io.open(os.path.join(D, "merge-report.json"), encoding="utf-8"))
    src = OrderedDict()
    for f in sorted(glob.glob(os.path.join(D, "research", "*.json"))):
        data = json.load(io.open(f, encoding="utf-8"))
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and x.get("id") and x["id"] not in src:
                    src[x["id"]] = {**x, "_file": os.path.basename(f)}

    pairs = []
    for m in rep["autoMerges"]:
        if m["reason"] == "id" or m["into"] == m["from"]:
            continue  # 同 id 必须合并，不在闸门标定范围内
        a, b = src.get(m["into"]), src.get(m["from"])
        if not (a and b):
            continue
        kept = techs.get(m["into"], {})
        text_a = (a.get("name") or "") + (a.get("desc") or "")
        text_b = (b.get("name") or "") + (b.get("desc") or "")
        pairs.append({
            "kept_id": a["id"], "swallowed_id": b["id"], "reason": m["reason"],
            "wikiEn": (a.get("wikiEn") or b.get("wikiEn") or kept.get("wikiEn") or "").strip(),
            "a": {"name": a.get("name"), "year": a.get("year"), "era": a.get("era"),
                  "cat": a.get("category"), "imp": a.get("importance"),
                  "desc": a.get("desc"), "file": a["_file"]},
            "b": {"name": b.get("name"), "year": b.get("year"), "era": b.get("era"),
                  "cat": b.get("category"), "imp": b.get("importance"),
                  "desc": b.get("desc"), "file": b["_file"]},
            "live_desc": kept.get("desc"), "live_year": kept.get("year"),
            "features": {
                "d_year": abs((a.get("year") or 0) - (b.get("year") or 0)),
                "d_era": abs(eidx.get(a.get("era"), 0) - eidx.get(b.get("era"), 0)),
                "era_diff": a.get("era") != b.get("era"),
                "cat_diff": a.get("category") != b.get("category"),
                "name_same": a.get("name") == b.get("name"),
                "desc_jaccard": round(jaccard(a.get("desc"), b.get("desc")), 3),
                "proto_word": any(w in text_a or w in text_b for w in PROTO_WORDS),
                "imp_diff": abs((a.get("importance") or 3) - (b.get("importance") or 3)),
            },
            "label": None, "label_reason": None,
        })
    pairs.sort(key=lambda p: -p["features"]["d_year"])
    json.dump(pairs, io.open(os.path.join(D, "gate-features.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"共 {len(pairs)} 对，已写 data/gate-features.json（label 待人工填）\n")
    for p in pairs:
        f, a, b = p["features"], p["a"], p["b"]
        print(f"{p['kept_id']} ← {p['swallowed_id']}   wikiEn={p['wikiEn']!r}")
        print(f"   A {a['year']:>7} {a['era']:<18}{a['cat']:<20}imp{a['imp']} {a['name']}｜{a['desc']}")
        print(f"   B {b['year']:>7} {b['era']:<18}{b['cat']:<20}imp{b['imp']} {b['name']}｜{b['desc']}")
        print(f"   现库: year={p['live_year']} desc={(p['live_desc'] or '')[:30]}")
        print(f"   特征 Δy={f['d_year']} Δera={f['d_era']} era异={f['era_diff']} cat异={f['cat_diff']} "
              f"同名={f['name_same']} descJ={f['desc_jaccard']} 代际词={f['proto_word']} Δimp={f['imp_diff']}\n")


if __name__ == "__main__":
    main()
