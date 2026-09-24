# -*- coding: utf-8 -*-
"""
F6：为缺 wikiEn 的条目取证补全——不猜标题，一律经 en.wikipedia API 验证。

候选来源：nameEn + 拉丁字母 aliases。判定分三档：
  verified        titles= 查询命中（含重定向解析）且页面存在 → 可自动写入规范标题
  needs_review    只有 search 命中、或与候选不完全同名 → 只进复核清单，不自动写
  no_article      API 确认无对应条目 → 承认"确无英文条目"（规范 §3.7 允许），写进审计

用法: python scripts/fill_wiki_en.py            # 干跑，打印三档结果
      python scripts/fill_wiki_en.py --apply    # 仅写入 verified
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
API = "https://en.wikipedia.org/w/api.php"
UA = "ALLTech-tree-data-maintenance/1.0 (research dataset curation; contact: repo owner)"


def api(params):
    q = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                print(f"  ! API 失败 {params}: {e!r}")
                return {}
            time.sleep(1.5 ** attempt)
    return {}


def exists(title):
    """返回 (是否页面存在, 解析后的规范标题, 是否重定向)"""
    d = api({"action": "query", "titles": title, "redirects": 1})
    pages = d.get("query", {}).get("pages", {})
    for pid, p in pages.items():
        if pid == "-1" or "missing" in p:
            continue
        return True, p.get("title", title), p.get("redirected") is not None or p.get("title") != title
    return False, title, False


def search(title):
    d = api({"action": "query", "list": "search", "srsearch": title, "srlimit": 5})
    return [h["title"] for h in d.get("query", {}).get("search", [])]


def candidates(t):
    out = [t["nameEn"]]
    out += [a for a in t.get("aliases") or [] if re.search(r"[A-Za-z]", a)]
    seen, res = set(), []
    for c in out:
        c = c.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            res.append(c)
    return res


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(os.path.join(D, "techs.json"), encoding="utf-8").read()
    techs = json.loads(raw)
    missing = [t for t in techs if not t.get("wikiEn")]
    print(f"待处理 {len(missing)} 条（全库 {len(techs)} 条）")

    verified, review, noart = [], [], []
    for t in missing:
        # 只有 nameEn 本身可以自动采用：别名里有"Natural gas""Porcelain"这类泛词，
        # 命中它们会把具体工艺错标成宽主题条目，故别名只作为建议进复核。
        ok, canon, redirected = exists(t["nameEn"])
        if ok:
            verified.append({"id": t["id"], "name": t["name"], "given": t["nameEn"],
                             "wikiEn": canon, "via": "redirect" if redirected else "exact"})
            continue
        s = search(t["nameEn"])
        alts = [(c, exists(c)[0]) for c in candidates(t)[1:]]
        review.append({"id": t["id"], "name": t["name"], "given": t["nameEn"],
                       "search_hits": s[:3],
                       "alias_pages_exist": [c for c, e in alts if e]})
        time.sleep(0.25)

    # 搜索与别名都无命中 → 视为"确无英文条目"（规范 §3.7 允许留空），否则进复核
    keep, noart = [], noart
    for r in review:
        (noart if not r["search_hits"] and not r["alias_pages_exist"] else keep).append(r)
    review = keep

    print(f"\n[verified] nameEn 经 API 确认存在页面、可自动采用：{len(verified)}")
    for v in verified:
        print(f"  {v['id']:<28} → \"{v['wikiEn']}\"  ({v['via']})")
    print(f"\n[needs_review] nameEn 无页面，但搜索/别名有线索：{len(review)}")
    for v in review:
        print(f"  {v['id']:<28} 给定={v['given']!r}\n      搜索={v['search_hits']}  别名成条={v['alias_pages_exist']}")
    print(f"\n[no_article] 搜索与别名均无命中，判为确无英文条目：{len(noart)}")
    for v in noart:
        print(f"  {v['id']:<28} 给定={v['given']!r}")

    json.dump({"verified": verified, "needs_review": review, "no_article": noart},
              io.open(os.path.join(D, "wiki-en-fill-audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n审计: data/wiki-en-fill-audit.json")
    if not apply_changes:
        print("（干跑。--apply 只写入 verified 档。）")
        return
    by_id = {t["id"]: t for t in techs}
    used = {}
    for t in techs:
        if t.get("wikiEn"):
            used.setdefault(t["wikiEn"].lower(), []).append(t["id"])
    safe, colliding = [], []
    for v in verified:
        (colliding if used.get(v["wikiEn"].lower()) else safe).append(v)
    for v in colliding:
        print(f"  跳过（会与 {used[v['wikiEn'].lower()]} 撞去重主键）: {v['id']} → {v['wikiEn']!r}")
    for v in safe:
        by_id[v["id"]]["wikiEn"] = v["wikiEn"]
    json.dump({"applied": safe, "skipped_title_collision": colliding},
              io.open(os.path.join(D, "wiki-en-applied.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    out = json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else "")
    io.open(os.path.join(D, "techs.json"), "w", encoding="utf-8").write(out)
    print(f"已写入 {len(safe)} 条 wikiEn；{len(colliding)} 条因主键碰撞转人工")


if __name__ == "__main__":
    main()
