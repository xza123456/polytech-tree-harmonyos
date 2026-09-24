# -*- coding: utf-8 -*-
"""
diff_candidates.py — 穷尽式收集流水线第 2 步：候选池与现有数据做差集。

读取：
  data/research/_candidates/<branch>.json（fetch_wikidata_concepts.py 产物）
  data/techs.json + data/research/*.json（已收录条目，01-29）
去重键：规范化英文标题（复用 merge_research.norm_title）+ wikiEn。
输出：
  data/research/_candidates/<branch>.missing.json —— 尚未收录的候选，
  供子代理小批量填空（中文名/year/desc/importance/prereqs）。

数量全部以实际统计输出为准。
"""
import json
import os
import glob
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_research import norm_title  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND_DIR = os.path.join(ROOT, "data", "research", "_candidates")
TECHS = os.path.join(ROOT, "data", "techs.json")
RESEARCH = os.path.join(ROOT, "data", "research")


def load_existing_keys():
    """汇总 techs.json 与所有 research 包已占用的规范标题键 / wikiEn 键。"""
    keys = set()
    wiki_keys = set()

    def eat(rec):
        for f in ("nameEn", "name", "id"):
            v = rec.get(f, "")
            if f != "id" and v:
                keys.add(norm_title(v))
        w = rec.get("wikiEn", "")
        if w:
            wiki_keys.add(norm_title(w))

    with open(TECHS, encoding="utf-8") as f:
        for r in json.load(f):
            eat(r)
    for p in glob.glob(os.path.join(RESEARCH, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                arr = json.load(f)
            if isinstance(arr, list):
                for r in arr:
                    eat(r)
        except Exception:  # noqa: BLE001 - 个别非数组文件跳过
            pass
    return keys, wiki_keys


def diff_branch(branch):
    cand_path = os.path.join(CAND_DIR, branch + ".json")
    with open(cand_path, encoding="utf-8") as f:
        cands = json.load(f)
    keys, wiki_keys = load_existing_keys()

    missing = []
    already = 0
    for c in cands:
        t = norm_title(c.get("nameEn", ""))
        w = norm_title(c.get("wikiEn", ""))
        if (t and t in keys) or (w and w in wiki_keys):
            already += 1
            continue
        missing.append(c)

    out = os.path.join(CAND_DIR, branch + ".missing.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(missing, f, ensure_ascii=False, indent=2)

    nzh = sum(1 for r in missing if r.get("name"))
    print("{:<20} 候选={:>5} 已收录={:>5} 缺失={:>5}（其中有中文名={}）-> {}".format(
        branch, len(cands), already, len(missing), nzh,
        os.path.basename(out)))
    return len(cands), already, len(missing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    files = sorted(os.path.basename(p)[:-5]
                   for p in glob.glob(os.path.join(CAND_DIR, "*.json"))
                   if not p.endswith(".missing.json"))
    targets = files if args.all else ([args.branch] if args.branch else files)
    tc = ta = tm = 0
    for b in targets:
        c, a, m = diff_branch(b)
        tc += c
        ta += a
        tm += m
    print("-" * 70)
    print("合计 {} 分支：候选={} 已收录={} 缺失={}".format(len(targets), tc, ta, tm))


if __name__ == "__main__":
    main()
