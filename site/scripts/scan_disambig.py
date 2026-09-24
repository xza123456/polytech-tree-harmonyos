# -*- coding: utf-8 -*-
"""
维护扫描：`wikiEn` 解析到**消歧页**而非真实条目。

为什么单独立一个脚本：准入闸门 `verify_wikien.py` 的判据是"条目存在"（含重定向解析），
而消歧页（"X may refer to: …"）同样"存在"，于是 `Awl`、`Cradle`、`Seed cake`、`Legalism`、
`Clearing house`、`Micrometer`、`Foldable phone`、`Floating bridge` 这 8 条混了过去——
它们的溯源等于没有溯源。本脚本用 `prop=pageprops&ppprop=disambiguation` 批量把它们点出来。

用法: python scripts/scan_disambig.py            # 扫 data/techs.json
      python scripts/scan_disambig.py --research # 扫 research/ 输入（重建前就能拦住）
用法: python scripts/scan_disambig.py            # 扫 data/techs.json
      python scripts/scan_disambig.py --research # 扫 research/ 输入（重建前就能拦住）
输出: data/disambiguation-hits.json（标题清单；空数组即通过）
      data/disambiguation-cache.json（已判过的标题 → 是否消歧页，让每次重建不必重扫全库）
"""
import glob
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUT = os.path.join(D, "disambiguation-hits.json")
CACHE = os.environ.get("ALLTECH_DISAMBIG_CACHE") or os.path.join(D, "disambiguation-cache.json")
API = "https://en.wikipedia.org/w/api.php"
UA = "ALLTechTreeDataBot/1.0 (https://github.com/secwind7/polytech-tree; disambiguation scan) python-urllib"


def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def titles_of(mode):
    if mode == "--research":
        out = []
        for f in sorted(glob.glob(os.path.join(D, "research", "*.json"))):
            try:
                rows = json.load(io.open(f, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            out += [(f, r.get("id"), r.get("wikiEn")) for r in rows if isinstance(r, dict) and r.get("wikiEn")]
        return out
    techs = json.load(io.open(TECHS, encoding="utf-8"))
    return [(os.path.basename(TECHS), t["id"], t.get("wikiEn")) for t in techs if t.get("wikiEn")]


def main():
    mode = "--research" if "--research" in sys.argv else "--product"
    rows = titles_of(mode)
    by_title = {}
    for f, rid, w in rows:
        by_title.setdefault(w, []).append(rid)
    print(f"扫描 {len(by_title)} 个标题（{mode}）")
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(io.open(CACHE, encoding="utf-8"))
    todo = [k for k in by_title if k not in cache]
    print(f"缓存命中 {len(by_title) - len(todo)}，待查 {len(todo)}")
    hits = [{"title": t, "asked_as": t, "ids": by_title[t]} for t in by_title if cache.get(t)]
    for h in hits:
        print(f"  消歧页（缓存） {h['title']} ← {h['ids']}")
    keys = todo
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        try:
            d = get({"action": "query", "format": "json", "prop": "pageprops",
                     "ppprop": "disambiguation", "redirects": 1, "titles": "|".join(chunk)})
        except Exception as e:  # noqa: BLE001
            print(f"  ! 第 {i // 50 + 1} 批抓取失败：{e!r}")
            continue
        # redirects=1 会把请求标题解析成正则标题（如 BERT→Bert），命中集合要按请求标题回指
        canon = {r["to"]: r["from"] for r in d.get("query", {}).get("redirects", []) if isinstance(r.get("to"), str)}
        seen = set()
        for p in d.get("query", {}).get("pages", {}).values():
            dis = "disambiguation" in (p.get("pageprops") or {})
            t = p.get("title")
            asked = canon.get(t, t) if t in canon else None
            for name in [t, asked]:
                if name and name in by_title and name not in seen:
                    seen.add(name)
                    cache[name] = dis
            if dis:
                ids = by_title.get(asked or "") or by_title.get(t) or []
                hits.append({"title": t, "asked_as": asked or t, "ids": ids})
                print(f"  消歧页 {t}（请求名 {asked or t}）← {ids}")
        for k in chunk:
            cache.setdefault(k, False)
        json.dump(cache, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.3)

    json.dump(hits, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"命中 {len(hits)} 个消歧页标题；清单 → {OUT}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
