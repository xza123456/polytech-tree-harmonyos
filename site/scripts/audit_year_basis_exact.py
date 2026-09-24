# -*- coding: utf-8 -*-
"""
F4 的诚实边界：`year_basis=exact` 目前只代表"批次给了一个确切年份"，不等于逐条文献核对。
本脚本抽样核对：取 N 条 exact 条目，抓英文维基导语纯文本，看那个年份是否真的出现在文里。

命中 = 导语里出现了同一个年份（公元后用 "1879"，公元前用 "1250 BC"）。
未命中不代表年份一定错（导语可能只写世纪），但代表"exact"这个标签**没有可核验的出处支撑**，
应降为 circa 或补 year_note。产出 data/year-basis-exact-audit.json 供逐条复核。

用法: python scripts/audit_year_basis_exact.py [--n 120] [--seed 20260921]
"""
import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUT = os.path.join(D, "year-basis-exact-audit.json")
API = "https://en.wikipedia.org/w/api.php"
UA = "ALLTechTreeDataBot/1.0 (https://github.com/secwind7/polytech-tree; data provenance check) python-urllib"


def leads(titles):
    """一次最多 20 个标题，返回 {title: 导语纯文本}。"""
    q = {
        "action": "query", "format": "json", "prop": "extracts", "explaintext": "1",
        "exintro": "1", "redirects": "1", "titles": "|".join(titles),
    }
    url = API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    pages = data.get("query", {}).get("pages", {})
    norm = {d["from"]: d["to"] for d in data.get("query", {}).get("normalized", [])}
    out = {}
    for p in pages.values():
        t = p.get("title")
        if not t:
            continue
        out[t] = p.get("extract") or ""
    # redirects 在未指定 formatversion=2 时是 {n, from, to} 三个字符串，取 from/to 要用字符串
    redir = {d["from"]: d["to"] for d in data.get("query", {}).get("redirects", [])
             if isinstance(d.get("from"), str) and isinstance(d.get("to"), str)}
    for src, dst in list(norm.items()) + list(redir.items()):
        if dst in out and src not in out:
            out[src] = out[dst]
    return out


def lead_wikitext(title):
    """第 0 节的源文（含 infobox）——纯文本导语会丢掉信息框里的年份，不能据此判"无出处"。"""
    q = {"action": "parse", "format": "json", "prop": "wikitext", "section": "0", "page": title}
    url = API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        wt = (json.load(r).get("parse", {}) or {}).get("wikitext")
    # 未指定 formatversion=2 时文本值包在 {"*": "..."} 里
    return wt.get("*", "") if isinstance(wt, dict) else (wt or "")


def hit(text, year):
    if not text:
        return None          # 取不到文本 = 未核验，不算不命中
    if year < 0:
        return bool(re.search(rf"\b{abs(year)}\s*(BC|BCE)", text, re.I))
    return bool(re.search(rf"\b{year}\b", text))


def main():
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 120
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 20260921
    techs = json.load(io.open(TECHS, encoding="utf-8"))
    pool = [t for t in techs if t.get("year_basis") == "exact" and (t.get("wikiEn") or "").strip()]
    random.seed(seed)
    sample = random.sample(pool, min(n, len(pool)))
    print(f"exact 总数 {len(pool)} / 全库 {len(techs)}，抽样 {len(sample)} 条（seed={seed}）")

    rows = []
    for i in range(0, len(sample), 20):
        chunk = sample[i:i + 20]
        try:
            texts = leads([t["wikiEn"] for t in chunk])
        except Exception as e:  # noqa: BLE001
            print(f"  ! 第 {i // 20 + 1} 批抓取失败：{e!r}（该批记为未核验）")
            texts = {}
        for t in chunk:
            txt = texts.get(t["wikiEn"])
            h = hit(txt, t["year"]) if txt is not None else None
            rows.append({"id": t["id"], "year": t["year"], "wikiEn": t["wikiEn"],
                         "checked": h is not None, "lead_has_year": bool(h) if h is not None else None,
                         "lead_chars": len(txt or "")})
        time.sleep(1.0)

    checked = [r for r in rows if r["checked"]]
    ok = [r for r in checked if r["lead_has_year"]]
    miss = [r for r in checked if not r["lead_has_year"]]
    print(f"可核验 {len(checked)}/{len(rows)}，纯文本导语含该年份 {len(ok)}（{len(ok) / max(len(checked), 1):.0%}），未提及 {len(miss)}")

    # 二查：导语纯文本会丢信息框，未提及的用第 0 节源文（含 infobox）再判一次
    for r in miss:
        try:
            wt = lead_wikitext(r["wikiEn"])
        except Exception as e:  # noqa: BLE001
            print(f"  ! {r['id']} 源文抓取失败：{e!r}")
            continue
        r["section0_has_year"] = bool(hit(wt, r["year"])) if wt else None
        time.sleep(0.4)
    ok2 = [r for r in miss if r.get("section0_has_year")]
    still = [r for r in miss if not r.get("section0_has_year")]
    print(f"源文（含 infobox）补命中 {len(ok2)} → 合计 {len(ok) + len(ok2)}/{len(checked)} = "
          f"{(len(ok) + len(ok2)) / max(len(checked), 1):.0%}；两查皆无 {len(still)} 条")
    for r in still[:40]:
        print(f"  待核 {r['id']:<30} {r['year']:>6}  {r['wikiEn']}")
    json.dump({"n": len(rows), "seed": seed, "checked": len(checked), "hit": len(ok),
               "hit_via_section0": len(ok2), "unexplained": still, "miss": miss, "rows": rows},
              io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"明细 → {OUT}")


if __name__ == "__main__":
    main()
