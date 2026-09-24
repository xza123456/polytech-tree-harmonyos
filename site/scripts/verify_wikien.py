# -*- coding: utf-8 -*-
"""
verify_wikien.py — 把规范 §3.7 的收录门槛机械化：
每条记录的 wikiEn 必须解析到**真实存在的英文维基条目**（含重定向解析），否则不合格。

这是净增批次（N-01…N-08）的前置闸门：模型生成的"看着像科技史条目"的概念，
绝大多数编不出一个真实存在的英文条目名，这一步就是用来把它们挡在库外的。

结果缓存 data/wikien-verify-cache.json（键=规范化标题），重建与复跑都不重复联网。
旧文件 wikien-verify-cache.json 是"并发 12 被限流、且把 429 当成条目不存在"的产物，已弃用不读。

用法:
  python scripts/verify_wikien.py                      # 校验现有 research/ 全部记录，打印不合格清单
  python scripts/verify_wikien.py data/research/30-*.json   # 只校验指定文件
  python scripts/verify_wikien.py --check-current      # 校验 data/techs.json（门禁模式，非零退出）
"""
import concurrent.futures as cf
import glob
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
CACHE = os.path.join(D, "wikien-batch-cache.json")
API = "https://en.wikipedia.org/w/api.php"
UA = ("ALLTechTreeDataBot/1.0 (https://github.com/secwind7/polytech-tree; "
      "dataset admission check; contact: repo owner)")  # 维基 UA 政策：无 URL 的 UA 会被 429


def norm_title(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[‐-―\-_/(),.:;!?'\"&]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_cache():
    if os.path.exists(CACHE):
        return json.load(io.open(CACHE, encoding="utf-8"))
    return {}


def batch_check(titles, cache):
    """一次查 50 个标题（prop=info 判存在性即可，无需解析重定向）。
    限流下的请求数从 2846 次降到 ~57 次，是本文件唯一可行的规模。"""
    todo = [t for t in dict.fromkeys(titles) if t not in cache]
    if not todo:
        return 0
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "prop": "info", "redirects": 1,
                                    "titles": "|".join(chunk), "format": "json"})
        req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read().decode())
                break
            except Exception as e:  # noqa: BLE001
                code = getattr(e, "code", None)
                if attempt == 4:
                    print(f"  批次 {i//50+1} 放弃：{code or type(e).__name__}（记为未判定，不写死结论）")
                    d = None
                    break
                time.sleep((6.0 if code == 429 else 2.0) * (2 ** attempt))
        if d is None:                      # 限流/网络失败：整批留待下次重试，绝不判"不存在"
            continue
        # 关键：prop=info 必须带 redirects=1，否则 "pH"/"fMRI"/"k-means clustering" 这类
        # 重定向标题会被当成"条目不存在"（假阴性）。判据取"明确 missing 的标题"集合。
        missing = set()
        for pid, p_ in (d.get("query", {}) or {}).get("pages", {}).items():
            if pid == "-1" or "missing" in p_:
                missing.add(p_.get("title", ""))
        for t in chunk:
            cache[t] = {"ok": t not in missing, "canon": "" if t in missing else t}
        time.sleep(1.2)
        if (i // 50) % 5 == 0:
            json.dump(cache, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"  批次 {i//50+1}/{(len(todo)+49)//50} 已核验")
    return len(todo)


def resolve(title, cache):
    k = norm_title(title)
    if k in cache:
        return cache[k]
    q = urllib.parse.urlencode({"action": "query", "titles": title, "redirects": 1, "format": "json"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            pages = d.get("query", {}).get("pages", {})
            canon, ok = "", False
            for pid, p in pages.items():
                if pid != "-1" and "missing" not in p:
                    ok, canon = True, p.get("title", title)
                    break
            cache[k] = {"ok": ok, "canon": canon}
            return cache[k]
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", None)
            if i == 3:
                # 关键：限流/网络失败 ≠ "条目不存在"，必须记成 unknown，否则会误杀合格条目
                cache[k] = {"ok": None, "canon": "", "error": f"api:{code or type(e).__name__}"}
                return cache[k]
            time.sleep((5.0 if code == 429 else 1.5) * (2 ** i))
    return {"ok": False, "canon": ""}


def records_from(paths):
    for f in paths:
        data = json.load(io.open(f, encoding="utf-8"))
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and x.get("id"):
                    yield f, x


def main():
    gate = "--check-current" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = args or sorted(glob.glob(os.path.join(D, "research", "*.json")))
    if gate:
        paths = [os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")]
    cache = load_cache()
    rows = list(records_from(paths))
    empty, bad, unknown = [], [], []
    checked = len(rows)
    todo = []
    for f, rec in rows:
        w = (rec.get("wikiEn") or "").strip()
        if not w:
            empty.append((os.path.basename(f), rec["id"], rec.get("name") or rec.get("nameEn")))
        elif w not in cache or cache[w].get("ok") is None:
            todo.append((f, rec, w))
        elif cache[w].get("ok") is False:
            bad.append((os.path.basename(f), rec["id"], rec.get("name") or rec.get("nameEn"), w))
    good = len(rows) - len(empty) - len(bad) - len(todo)
    print(f"待联网核验 {len(todo)} 个标题（缓存命中 {len(rows)-len(empty)-len(todo)-len(bad)}），批量 50/请求")
    if batch_check([w for _, _, w in todo], cache):
        for f, rec, w in todo:
            r = cache.get(w, {})
            if r.get("ok"):
                good += 1
            elif r.get("ok") is None:
                unknown.append((os.path.basename(f), rec["id"], w))
            else:
                bad.append((os.path.basename(f), rec["id"], rec.get("name") or rec.get("nameEn"), w))
    json.dump(cache, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"校验 {checked} 条：条目存在 {good} | 确认查不到 {len(bad)} | 因限流未判定 {len(unknown)} | wikiEn 为空 {len(empty)}")
    patched = {"wire_recorder", "niobium_tin", "auger_tlp", "von_neumann_quantum_foundations", "li_yorke_chaos"}
    for x in bad[:25]:
        tag = "（源标题有误，已在合并阶段由 L3 裁决改挂/置空）" if x[1] in patched else ""
        print(f"  不合格 {x[0]} {x[1]:<30} wikiEn={x[3]!r} （{x[2]}）{tag}")
    if len(bad) > 25:
        print(f"  …其余 {len(bad)-25} 条见缓存 data/wikien-verify-cache.json")
    print("\nwikiEn 为空的条目（§3.1 允许冷门古发明留空，但需人工确认确无条目）:")
    for x in empty[:12]:
        print(f"  {x[0]:<38} {x[1]:<28} {x[2]}")
    if len(empty) > 12:
        print(f"  …共 {len(empty)} 条")
    if gate and (bad or unknown):
        sys.exit(1)


if __name__ == "__main__":
    main()
