# -*- coding: utf-8 -*-
"""
fetch_wikidata_concepts.py — 穷尽式收集流水线第 1 步：拉取学科概念候选池。

数据通道（2026-09 实测）：
  Wikidata SPARQL(WDQS) 处于事故限流，且学科概念不直接 P31 指向学科根，
  召回与稳定性都差。改用 Wikimedia MediaWiki action API：
    - list=categorymembers 递归遍历维基分类树（不走 WDQS，无限流）；
    - 只取 ns=0 文章页，排除人物/期刊/奖项/stub/列表等噪声分类；
    - 用 langlink 批量补中文条目标题（name）；
    - wikiEn 即英文页标题，天然真实可核。

输出 data/research/_candidates/<branch>.json，字段：
  title(wikiEn=nameEn 同值候选) / name(中文，可空) / subcat(命中的子分类)。
年份/desc/importance/prereqs 不在本步骤生成，交由后续填空。
所有数量以脚本实际返回为准。

用法：
  python scripts/fetch_wikidata_concepts.py --branch number_theory
  python scripts/fetch_wikidata_concepts.py --all
"""
import json
import os
import sys
import time
import argparse
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "research", "_candidates")

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "ALLTech-Tree/1.0 (concept collection)"}

# 分支根分类（不含 "Category:" 前缀）。这些是人工整理的教科书级分类。
BRANCHES = {
    # 包 24 数论 + 代数
    "number_theory":     "Number theory",
    "algebra":           "Algebra",
    "abstract_algebra":  "Abstract algebra",
    "linear_algebra":    "Linear algebra",
    # 包 28 离散 / 逻辑 / 组合 / 图论 / 序
    "mathematical_logic": "Mathematical logic",
    "set_theory":         "Set theory",
    "combinatorics":      "Combinatorics",
    "graph_theory":       "Graph theory",
    "order_theory":       "Order theory",
}

# 递归到这些子分类时剪枝：非"概念"内容，避免噪声。
SUBCAT_DENY_KEYWORDS = [
    "number theorists", "mathematicians", "journals", "publications",
    "awards", "prizes", "prize", "stubs", "stub",
    "organizations", "conferences", "education", "textbooks",
    "history of", "timelines", "lists of", "competitions",
]

# 人物类子分类常见后缀/词（各学科的 xxx theorists / geometers / logicians）。
PERSON_SUBCAT_SUFFIX = (
    "theorists", "mathematicians", "logicians", "geometers", "algebraists",
    "statisticians", "topologists", "analysts", "arithmeticians",
    "number theorists", "computer scientists", "scientists", "scholars",
    "writers", "authors",
)

# 标题层面排除：列表/时间线/索引/消歧等非概念页。
TITLE_DENY_PREFIX = ("List of", "Lists of", "Timeline", "Index of",
                     "Outline of", "Glossary of", "Category:", "Wikipedia:")
TITLE_DENY_SUBSTR = ("stub", "template", "list of", "award", "prize")

MAX_DEPTH = 2          # 根分类向下 2 层子分类
PAGE_BATCH = 500       # 分类成员单次上限（API 最大 500）
PAUSE = 0.25           # 礼貌限速


def api(params):
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("API failed: {} :: {}".format(params.get("list"), last))


def denied_subcat(title: str) -> bool:
    t = title.lower()
    if any(k in t for k in SUBCAT_DENY_KEYWORDS):
        return True
    # 人物类：分类名去掉 "category:" 前缀后，按词尾判断（如 "Arithmetic geometers"）
    name = t.split(":", 1)[-1].strip()
    if name.endswith(PERSON_SUBCAT_SUFFIX):
        return True
    return False


def denied_title(title: str) -> bool:
    t = title.lower()
    if title.startswith(TITLE_DENY_PREFIX):
        return True
    return any(k in t for k in TITLE_DENY_SUBSTR)


def members(category, cmtype):
    """列某分类下的成员（page 或 subcat），自动翻页。"""
    out = []
    cont = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:" + category,
            "cmtype": cmtype,
            "cmlimit": PAGE_BATCH,
        }
        if cont:
            params.update(cont)
        d = api(params)
        out.extend(d.get("query", {}).get("categorymembers", []))
        if "continue" in d:
            cont = d["continue"]
            time.sleep(PAUSE)
        else:
            break
    return out


def crawl(root_cat, max_depth=MAX_DEPTH):
    """返回 {title: subcat_label}。"""
    found = {}

    def add_pages(cat, label, depth):
        pages = members(cat, "page")
        kept = 0
        for m in pages:
            if m.get("ns") == 0 and not denied_title(m["title"]):
                found.setdefault(m["title"], label)
                kept += 1
        print("    [d{}] {:<38} pages={:>4} kept={:>4}".format(
            depth, cat[:38], len(pages), kept), flush=True)

    # 根分类自身的文章
    add_pages(root_cat, root_cat, 0)

    # BFS 子分类
    frontier = [(root_cat, 0)]
    seen_subs = set()
    while frontier:
        cat, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        subs = members(cat, "subcat")
        for m in subs:
            sub = m["title"][len("Category:"):]
            if sub in seen_subs or denied_subcat(m["title"]):
                continue
            seen_subs.add(sub)
            add_pages(sub, sub, depth + 1)
            frontier.append((sub, depth + 1))
            time.sleep(PAUSE)
    return found


def add_zh(titles):
    """批量取跨语言中文标题。返回 {en_title: zh_title}。"""
    zh = {}
    items = sorted(titles)
    for i in range(0, len(items), 50):
        chunk = items[i:i + 50]
        d = api({
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "langlinks",
            "lllang": "zh",
            "lllimit": 50,
        })
        pages = d.get("query", {}).get("pages", {})
        for _, p in pages.items():
            lls = p.get("langlinks") or []
            if lls:
                zh[p["title"]] = lls[0]["*"]
        time.sleep(PAUSE)
    return zh


def fetch_branch(key):
    root = BRANCHES[key]
    print("分支 {}  root='{}'  depth={}".format(key, root, MAX_DEPTH))
    found = crawl(root, MAX_DEPTH)
    zh = add_zh(list(found.keys()))
    recs = []
    for title, sub in sorted(found.items()):
        recs.append({
            "nameEn": title,
            "wikiEn": title,
            "name": zh.get(title, ""),
            "subcat": sub if sub != root else "",
        })
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, key + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    nzh = sum(1 for r in recs if r["name"])
    print("  去重后={} 有中文名={} ({:.0f}%) -> {}".format(
        len(recs), nzh, 100.0 * nzh / max(1, len(recs)), out))
    return recs


def main():
    global MAX_DEPTH
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--depth", type=int, default=MAX_DEPTH)
    args = ap.parse_args()

    MAX_DEPTH = args.depth

    if args.list:
        for k, v in BRANCHES.items():
            print("{:<20} {}".format(k, v))
        return
    if args.all:
        total = 0
        for k in BRANCHES:
            total += len(fetch_branch(k))
        print("合计候选（未跨分支去重）={}".format(total))
    elif args.branch:
        if args.branch not in BRANCHES:
            print("未知分支；--list 查看")
            sys.exit(1)
        fetch_branch(args.branch)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
