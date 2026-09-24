# -*- coding: utf-8 -*-
"""
F4 的取证半程：把"批次给了个年份"升级成"词条正文支持这个年份"。

背景：`fill_year_basis.py` 对非整十/整百的年份只能给 `batch_asserted`（批次断言，未核对）。
抽样 200 条实测：30% 的确切年份出现在英文词条导语纯文本里，再查第 0 节源文（含 infobox）
又补 8.5pp。所以"有没有出处"是可以机械判定的，不该靠批次自报。

规则（幂等）：
  batch_asserted + 导语或第 0 节源文含该年份 → exact，并写 year_note 说明"正文/信息框可检"
  exact + （仅 --deep 时）导语与第 0 节源文都查不到该年份 → 降回 batch_asserted
  自报 exact 不作数：净增批次 177 条自标 exact，未经取证前一律按证据处理
  其余手工值（circa/century/decade/…）不动
产物：data/year-basis-promote-audit.json（升级数、未获证数、按批次的分布）

用法: 构建内 python scripts/promote_exact_year.py --apply            # 只做导语批量核验
      维护时  python scripts/promote_exact_year.py --deep --apply    # 再查第 0 节源文并降级自报 exact
"""
import glob
import io
import atomic
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
CACHE_PATH = os.environ.get("ALLTECH_YEAR_CACHE") or os.path.join(D, "year-basis-corroboration-cache.json")
OUT = os.environ.get("ALLTECH_OUT") or D
API = "https://en.wikipedia.org/w/api.php"
UA = "ALLTechTreeDataBot/1.0 (https://github.com/secwind7/polytech-tree; year provenance check) python-urllib"


RANK = {0: 0, False: 0, True: 1, 1: 2, 2: 1}   # 证据强度：正文命中 > 深查未命中 > 仅导语未命中


def norm_entry(v):
    return 1 if v is True or v == 1 else (2 if v == 2 else 0)


def save_cache(cache):
    """合并后再写：并发/迟到的旧写者不应把别人的取证结果抹掉。
    同一标题只保留证据更强的那条（命中 > 深查未命中 > 导语未命中）。"""
    merged = {}
    if os.path.exists(CACHE_PATH):
        try:
            for k, v in json.load(io.open(CACHE_PATH, encoding="utf-8")).items():
                merged[k] = norm_entry(v)
        except Exception:  # noqa: BLE001  半写缓存直接丢弃重建
            merged = {}
    for k, v in cache.items():
        nv = norm_entry(v)
        if k not in merged or RANK.get(nv, 0) > RANK.get(merged[k], 0):
            merged[k] = nv
    atomic.write_json(CACHE_PATH, merged, indent=None)
    return merged


def unwrap(v):
    return v.get("*", "") if isinstance(v, dict) else (v or "")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def batch_leads(titles):
    """一次 20 条导语纯文本；返回 {原标题: 文本}。"""
    q = {"action": "query", "format": "json", "prop": "extracts", "explaintext": "1",
         "exintro": "1", "redirects": "1", "titles": "|".join(titles)}
    data = get(API + "?" + urllib.parse.urlencode(q))
    pages = data.get("query", {}).get("pages", {})
    out = {p["title"]: unwrap(p.get("extract")) for p in pages.values() if p.get("title")}
    for d in data.get("query", {}).get("normalized", []) + data.get("query", {}).get("redirects", []):
        if isinstance(d.get("from"), str) and isinstance(d.get("to"), str) and d["to"] in out:
            out[d["from"]] = out[d["to"]]
    return out


def section0(title):
    q = {"action": "parse", "format": "json", "prop": "wikitext", "section": "0", "page": title}
    try:
        return unwrap((get(API + "?" + urllib.parse.urlencode(q)).get("parse") or {}).get("wikitext"))
    except Exception:  # noqa: BLE001
        return ""


def has_year(text, year):
    if not text:
        return False
    if year < 0:
        return bool(re.search(rf"\b{abs(year)}\s*(BC|BCE)", text, re.I))
    return bool(re.search(rf"(?<![\d.]){year}(?![\d.])", text))


def main():
    apply_changes = "--apply" in sys.argv
    deep = "--deep" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    cache = json.load(io.open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else {}
    # 缓存三态：1=正文/信息框检得；0=仅导语查过未命中；2=导语与第 0 节源文都未命中
    cache = {k: (1 if v is True else 0 if v is False else int(v)) for k, v in cache.items()}

    pool = [t for t in techs if t.get("year_basis") in ("batch_asserted", "exact")]
    if limit:
        pool = pool[:limit]
    print(f"待取证 {len(pool)} 条（全库 {len(techs)}），已有缓存 {len(cache)} 条")

    todo = [t for t in pool if t["id"] not in cache]
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        try:
            leads = batch_leads([t["wikiEn"] for t in chunk if t.get("wikiEn")])
        except Exception as e:  # noqa: BLE001
            print(f"  ! 第 {i // 20 + 1} 批抓取失败：{e!r}（留待下次）")
            continue
        for t in chunk:
            txt = leads.get(t.get("wikiEn") or "", "")
            cache[t["id"]] = 1 if has_year(txt, t["year"]) else 0
        if (i + 20) % 200 == 0:
            print(f"  …{i + 20}/{len(todo)}")
            save_cache(cache)
        time.sleep(0.3)

    if deep:
        misses = [t for t in pool if cache.get(t["id"]) == 0]
        print(f"导语未命中 {len(misses)} 条，二查第 0 节源文（含 infobox）")
        for n, t in enumerate(misses):
            cache[t["id"]] = 1 if has_year(section0(t["wikiEn"] or ""), t["year"]) else 2
            if (n + 1) % 200 == 0:
                print(f"  …{n + 1}/{len(misses)}")
                save_cache(cache)
            time.sleep(0.2)

    save_cache(cache)

    promoted = [t for t in pool if t.get("year_basis") == "batch_asserted" and cache.get(t["id"]) == 1]
    for t in promoted:
        t["year_basis"] = "exact"
        if not (t.get("year_note") or "").strip():
            t["year_note"] = "年份可在该词条正文/信息框检得（脚本取证）"
    demoted = []
    # 缓存值 2 = "导语与第 0 节源文都查过、都没有这个年份"，由维护跑（--deep）产生。
    # 降级判定本身不需要 --deep：缓存既然已判过，构建里就该照它降级，否则每次重建
    # 又把批次自报的 exact 放回去，降级永远落不了地。
    for t in pool:
        if t.get("year_basis") == "exact" and cache.get(t["id"]) == 2:
            t["year_basis"] = "batch_asserted"
            t["year_note"] = (t.get("year_note") or "") + "；词条导语与信息框均未检得该年份，降为批次断言"
            demoted.append(t["id"])
    print(f"升级为 exact：{len(promoted)} 条；降级为 batch_asserted：{len(demoted)} 条；"
          f"仍为 batch_asserted {sum(1 for t in pool if t.get('year_basis') == 'batch_asserted')} 条")
    audit = {"pool": len(pool), "promoted": len(promoted), "demoted": demoted,
             "uncorroborated": sorted(t["id"] for t in pool if cache.get(t["id"]) != 1)}
    atomic.write_json(os.path.join(OUT, "year-basis-promote-audit.json"), audit, indent=1)
    if not apply_changes:
        print("（干跑，未写 techs.json）")
        return
    atomic.write_atomic(TECHS, 
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    print(f"已写入 {TECHS}")


if __name__ == "__main__":
    main()
