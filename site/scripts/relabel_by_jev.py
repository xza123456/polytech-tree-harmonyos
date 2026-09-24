# -*- coding: utf-8 -*-
"""
F10 领域重标 · Jev 受限选择：只在"该记录旧域可达的 3~7 个新域"之间让 Jev 判，
比 22 选一容易得多（Jev 在 8 域上是 85~86%）。

结果增量写 data/domain-relabel-jev.json（幂等、可断点续跑）；
relabel_domains.py 之后以这份缓存为准、规则为回退，因此重建 techs.json 不需要再联网。

用法: python scripts/relabel_by_jev.py [最多处理条数]
环境变量: JEV_CONCURRENCY 默认 10
"""
import concurrent.futures as cf
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

import relabel_domains as R  # noqa: E402  复用候选集与规则回退

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(D, "domain-relabel-jev.json")
API = "https://api.typesafe.ai/v1/systemone"
CONC = int(os.environ.get("JEV_CONCURRENCY", "10"))

# 旧域 → 允许的新域候选（含 §3.3 群内邻居；窄集让 Jev 做判别式而非穷举）
CAND = {
    "math_logic": ["math_pure", "logic_foundations", "algorithms_cs", "computing_systems", "physics"],
    "information": ["info_media", "computing_systems", "algorithms_cs", "physics", "earth_space",
                    "life_medicine", "culture_media", "education_knowledge"],
    "physical_science": ["physics", "chemistry", "earth_space", "life_medicine", "math_pure",
                         "materials", "computing_systems"],
    "life_medicine": ["life_medicine", "agriculture_food", "chemistry", "daily_life", "materials",
                      "earth_space"],
    "materials": ["materials", "manufacturing", "chemistry", "construction", "military",
                  "energy_power", "agriculture_food", "info_media"],
    "energy_power": ["energy_power", "manufacturing", "chemistry", "military", "materials",
                     "construction"],
    "transport_exploration": ["transport", "space_exploration", "military", "construction",
                              "earth_space", "info_media"],
    "society": ["governance", "economy", "education_knowledge", "culture_media", "daily_life",
                "military", "info_media"],
}
_lock = threading.Lock()
_toks = [0, 0]


def key():
    for line in io.open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("缺 TYPESAFE_API_KEY")


def call(state, questions, k, tries=5):
    body = json.dumps({"model": "jev-latest", "state": state, "questions": questions}).encode()
    for i in range(tries):
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "Authorization": f"Bearer {k}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode())
            u = d.get("usage") or {}
            with _lock:
                _toks[0] += u.get("input_tokens") or 0
                _toks[1] += u.get("output_tokens") or 0
            return d.get("answers") or {}, None
        except urllib.error.HTTPError as e:
            code, txt = e.code, e.read().decode()[:150]
            if code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            return None, f"HTTP {code} {txt}"
        except Exception as e:  # noqa: BLE001
            if i < tries - 1:
                time.sleep(2 ** i)
                continue
            return None, repr(e)
    return None, "retries"


def main():
    lowconf = "--lowconf" in os.sys.argv
    args = [a for a in os.sys.argv[1:] if not a.startswith("--")]
    limit = int(args[0]) if args else 10**9
    cats = {c["id"]: c for c in json.load(io.open(os.path.join(D, "categories.json"), encoding="utf-8"))}
    techs = json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))
    done = {}
    if os.path.exists(OUT):
        done = json.load(io.open(OUT, encoding="utf-8"))
    if lowconf:
        # 第二轮：首轮置信度 <0.5 或失败的条目，放开到全部 22 域重问
        todo = [t for t in techs
                if t["id"] not in done or not done[t["id"]].get("domain")
                or (done[t["id"]].get("conf", 0) < 0.5 and not done[t["id"]].get("pass2"))]
        print(f"低置信第二轮：{len(todo)} 条放开到 22 域重问")
    else:
        todo = [t for t in techs if t["id"] not in done]
    print(f"共 {len(techs)} 条，已判 {len(done)}，本次待判 {min(limit, len(todo))}")
    crit = {cid: f"{c['name']}：{'、'.join(c['subcategories'])}" for c in cats.values() for cid in [c['id']]}

    def work(t):
        cands = ALL_IDS if lowconf else CAND.get(t["category"], [t["category"]])
        state = f"名称：{t['name'] or t['nameEn']}\n释义：{t.get('desc', '')}"
        q = {"domain": {"type": "choice", "instructions": "这项科技最恰当归属哪个领域？",
                        "criteria": {c: crit[c] for c in cands}}}
        ans, err = call(state, q, KEY)
        if err or not ans:
            return t["id"], None, err or "empty"
        a = ans["domain"]
        prev = done.get(t["id"], {})
        val = {"domain": a.get("choice"), "conf": round(float(a.get("confidence") or 0), 3),
               "rule": R.decide(t)[0], "cands": len(cands)}
        if lowconf:
            val["pass2"] = True
            if prev:
                val["pass1"] = {k: prev.get(k) for k in ("domain", "conf", "cands")}
        return t["id"], val, None

    ALL_IDS = list(cats.keys())
    KEY = key()
    t0 = time.perf_counter()
    n = 0
    with cf.ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = [ex.submit(work, t) for t in todo[:limit]]
        for f in cf.as_completed(futs):
            tid, val, err = f.result()
            if val:
                done[tid] = val
            else:
                done[tid] = {"domain": None, "error": err}
            n += 1
            if n % 200 == 0:
                json.dump(done, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                el = time.perf_counter() - t0
                agree = sum(1 for v in done.values() if v.get("rule") and v.get("domain") == v["rule"])
                judged = sum(1 for v in done.values() if v.get("domain"))
                print(f"  {judged}/{len(techs)} 用时 {el/60:.1f} 分  与规则一致率 "
                      f"{agree/max(judged,1)*100:.0f}%  token in={_toks[0]:,}")
    json.dump(done, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    ok = [v for v in done.values() if v.get("domain")]
    agree = sum(1 for v in ok if v.get("rule") == v["domain"])
    fail = [k for k, v in done.items() if not v.get("domain")]
    print(f"\n完成：判定 {len(ok)} / 失败 {len(fail)}，用时 {(time.perf_counter()-t0)/60:.1f} 分，"
          f"token in={_toks[0]:,} out={_toks[1]:,}")
    print(f"Jev 与关键词规则一致率: {agree/len(ok)*100:.1f}%（分歧 {len(ok)-agree} 条）")
    print("各新域条数:", Counter(v["domain"] for v in ok).most_common(8))


if __name__ == "__main__":
    main()
