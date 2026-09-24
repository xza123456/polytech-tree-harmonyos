# -*- coding: utf-8 -*-
"""
F7：给"无 prereqs 且无 related"的孤立点补边——不机械连"同域邻居"，而是
让 Jev 在同域同时代的候选里判断"哪一条是它的直接前置"，判不出就留空并记录。

候选来源：同 new-domain 同 era 的其他条目（按重要度与入度排序取前 8）；
若无同域同代条目，则放宽到相邻时代。每题返回 top-1 + 置信；conf < 0.5 视为"未判定"，
只写进复核清单不自动落库。

用法: python scripts/link_isolated.py            # 只生成复核队列（默认不写库）
产物: data/isolated-links.json（决策缓存，可断点续跑）

**为什么不 --apply**：2026-09-21 实跑 61 条，conf>=0.5 的 34 条里有明显硬凑的
（tattoo←hat、lighthouse←canal、camera_obscura←atomism）。同域同代候选池里往往根本没有
真前置，Jev 被题目逼着选一个，置信度还不低。故本脚本定位为"生成复核队列"，
补边必须由人定；--apply 保留但不应在未复核时使用。
"""
import concurrent.futures as cf
import io
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(D, "isolated-links.json")
API = "https://api.typesafe.ai/v1/systemone"
CONC = int(os.environ.get("JEV_CONCURRENCY", "6"))
MIN_CONF = 0.5
AUTO_APPLY = False   # 见模块说明：候选池内常无真前置，自动写边会造出假依赖


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
            return d.get("answers") or {}, None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            return None, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            if i < tries - 1:
                time.sleep(2 ** i)
                continue
            return None, repr(e)
    return None, "retries"


def main():
    apply_changes = "--apply" in os.sys.argv
    techs = json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))
    by = {t["id"]: t for t in techs}
    indeg = Counter()
    for t in techs:
        for p in t.get("prereqs") or []:
            indeg[p] += 1
    cells = defaultdict(list)
    for t in techs:
        cells[(t["category"], t["era"])].append(t)
    era_order = [e["id"] for e in sorted(json.load(io.open(os.path.join(D, "eras.json"), encoding="utf-8")),
                                         key=lambda x: x["order"])]
    iso = [t for t in techs if not (t.get("prereqs") or []) and not (t.get("related") or [])]
    print(f"孤立点 {len(iso)} 条")

    done = json.load(io.open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    jobs = []
    for t in iso:
        if t["id"] in done:
            continue
        ei = era_order.index(t["era"])
        pool = cells.get((t["category"], t["era"]), [])
        if len(pool) < 3 and ei > 0:
            pool += cells.get((t["category"], era_order[ei - 1]), [])
        cands = [c for c in pool if c["id"] != t["id"]]
        cands.sort(key=lambda c: (-indeg[c["id"]], c["importance"]))
        cands = cands[:8]
        if not cands:
            done[t["id"]] = {"domain": None, "reason": "无同域同代候选"}
            continue
        crit = {c["id"]: f"{c['name'] or c['nameEn']}：{(c.get('desc') or '')[:40]}" for c in cands}
        jobs.append((t, crit))

    def work(item):
        t, crit = item
        state = f"名称：{t['name'] or t['nameEn']}\n释义：{t.get('desc', '')}"
        q = {"pre": {"type": "choice",
                     "instructions": "要出现这项科技，必须先具备下列哪一项？若都不构成直接前置，选最接近的一条。",
                     "criteria": crit}}
        ans, err = call(state, q, KEY)
        if err or not ans:
            return t["id"], None, err
        a = ans["pre"]
        return t["id"], {"prereq": a.get("choice"), "conf": round(float(a.get("confidence") or 0), 3),
                         "n_cands": len(crit)}, None

    KEY = key()
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for n, f in enumerate(cf.as_completed(futs), 1):
            tid, val, err = f.result()
            done[tid] = val or {"prereq": None, "error": err}
            if n % 20 == 0:
                json.dump(done, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {n}/{len(jobs)} 用时 {time.perf_counter()-t0:.0f}s")
    json.dump(done, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

    accepted = {k: v for k, v in done.items() if v.get("prereq") and v.get("conf", 0) >= MIN_CONF}
    print(f"\n接受（conf>={MIN_CONF}）: {len(accepted)} / 判定 {len(done)}；"
          f"未达门槛转人工: {len(done)-len(accepted)}")
    for k, v in list(accepted.items())[:6]:
        print(f"  {k:<28} ← {v['prereq']:<28} conf={v['conf']}")
    if not apply_changes or not AUTO_APPLY:
        if apply_changes:
            print("（AUTO_APPLY=False：自动写边会产生假依赖，仅输出复核队列 data/isolated-links.json）")
        print("（干跑。--apply 写入 prereqs。）")
        return
    raw = io.open(os.path.join(D, "techs.json"), encoding="utf-8").read()
    for k, v in accepted.items():
        t = by[k]
        if v["prereq"] in by and v["prereq"] != k and by[v["prereq"]]["year"] <= t["year"]:
            t["prereqs"] = sorted(set((t.get("prereqs") or []) + [v["prereq"]]))
        else:
            t["related"] = sorted(set((t.get("related") or []) + [v["prereq"]]))
    io.open(os.path.join(D, "techs.json"), "w", encoding="utf-8").write(
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    still = sum(1 for t in techs if not (t.get("prereqs") or []) and not (t.get("related") or []))
    print(f"已写入；剩余孤立点 {still} 条")


if __name__ == "__main__":
    main()
