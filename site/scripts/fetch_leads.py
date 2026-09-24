# -*- coding: utf-8 -*-
"""
fetch_leads.py — 为 data/techs.json 里每条 wikiEn 抓取英文维基导语首段，缓存到 data/jev-desc-leads.json。

关键坑：请求带 redirects=1 时，API 返回的页面键是**解析后的规范标题**，
用原始 wikiEn 去查会静默拿到空串。这里用 query.redirects 建 from→to 映射再查表。

只读，不修改任何事实源。走 Wikimedia 公开 action API，不需要 key。

用法:
  python scripts/fetch_leads.py            # 增量补全缓存
  python scripts/fetch_leads.py --force    # 全部重抓
"""
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "jev-desc-leads.json")
UA = "ALLTech-license-audit/1.0 (provenance check; one-off lead fetch)"
BATCH = 20


def norm(s):
    return (s or "").replace("_", " ").strip().lower()


def cut_lead(s):
    """取前两句或约 120 字符内的首句，上限 340 字符。"""
    s = " ".join((s or "").split())
    if not s:
        return ""
    cut, acc = 0, 0
    for i, ch in enumerate(s):
        if ch in ".!?":
            acc += 1
            if acc >= 2 or i > 120:
                cut = i + 1
                break
    first = s[:cut] if cut else s[:280]
    return first if len(first) <= 340 else first[:340] + "…"


def fetch_batch(titles, retries=6):
    """返回 {原始标题: 导语}，重定向与缺失都按原始标题回填。

    维基对连续请求会 429 限流；这里必须退避重试，否则整批标题会被静默漏掉
    （上一版直接 except 跳过，导致 79 个标题根本没进缓存，覆盖率被误报低）。
    """
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "extracts", "exintro": "1",
        "explaintext": "1", "exlimit": str(BATCH), "redirects": "1",
        "titles": "|".join(titles)})
    url = f"https://en.wikipedia.org/w/api.php?{q}"
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(3 * (i + 1))
                continue
            raise
    query = j.get("query") or {}
    # 按规范化标题（小写、下划线转空格）建表：
    #   redirects 只覆盖显式重定向，首字母大小写规范化（eBay → EBay）不在其中，
    #   用原始标题精确查表会把这些条目静默判成"无正文"。
    pages = {norm(pg.get("title", "")): ("" if pg.get("missing") is not None
                                         else cut_lead(pg.get("extract")))
             for pg in (query.get("pages") or {}).values()}
    redir = {norm(rd.get("from", "")): norm(rd.get("to", ""))
             for rd in (query.get("redirects") or [])}
    out = {}
    for t in titles:
        k = norm(t)
        out[t] = pages.get(k) if k in pages else pages.get(redir.get(k, ""), "")
    return out



def main():
    force = "--force" in sys.argv
    techs = json.load(io.open(os.path.join(DATA, "techs.json"), encoding="utf-8"))
    titles = sorted({(t.get("wikiEn") or "").strip() for t in techs if (t.get("wikiEn") or "").strip()})
    cache = {} if force else (json.load(io.open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {})
    # 空值按未抓处理：上一版脚本的重定向映射 bug 会留下假空串
    todo = [t for t in titles if not cache.get(t, "").strip()]
    print(f"条目 {len(techs)} 条；去重后需导语的标题 {len(titles)} 个；缓存已有 {len(cache)}，本次抓 {len(todo)}")

    failed = []
    for k in range(0, len(todo), BATCH):
        batch = todo[k:k + BATCH]
        try:
            cache.update(fetch_batch(batch))
        except Exception as e:  # noqa: BLE001
            failed.append((k, repr(e)))
            print(f"  ! 批次失败 {k}: {e!r}，跳过")
        done = min(k + BATCH, len(todo))
        if done % 200 < BATCH or done == len(todo):
            print(f"  {done}/{len(todo)}")
            with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)
        time.sleep(0.3)

    with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)

    absent = [t for t in titles if t not in cache]
    if absent:
        print(f"  ! 仍有 {len(absent)} 个标题未进缓存（重试后仍失败），示例: {absent[:5]}")
    if failed:
        print(f"  ! 失败批次 {len(failed)} 个")
    empty = sorted([t for t, v in cache.items() if not v.strip()])
    tech_no_lead = [t["id"] for t in techs
                    if not cache.get((t.get("wikiEn") or "").strip(), "").strip()]
    tech_no_wiki = [t["id"] for t in techs if not (t.get("wikiEn") or "").strip()]
    print(f"\n=== 导语覆盖 ===")
    print(f"缓存标题 {len(cache)} 个，其中空导语 {len(empty)} 个")
    print(f"条目 {len(techs)} 条：有导语 {len(techs) - len(tech_no_lead)}，无导语 {len(tech_no_lead)}")
    print(f"  其中 wikiEn 本身为空 {len(tech_no_wiki)} 条")
    if empty:
        print("空导语标题（前 30）:", ", ".join(empty[:30]))
    print(f"缓存文件: data/jev-desc-leads.json")


if __name__ == "__main__":
    main()
