# -*- coding: utf-8 -*-
"""
云端 Jev (api.typesafe.ai/v1/systemone) 复现 Von 的三组测试，样本/问题定义逐字一致，
这样准确率可直接对比。

  T1 领域 8 选 1 choice   条件 A(中文状态+中文选项) / B(英文状态+英文选项)   ← Von: 43% / 58%
  T2 时代 11 选 1 choice  条件 F1/F3(中文) F2/F6(英文)                      ← Von: 15%/11%/47%/7%
  T3 时代 是/否 noul      真断言 vs 相邻档假 vs 跨档假，看 AUC              ← Von AUC: 0.48 / 0.46

用法（项目根目录）:
  python scripts/jev_replicate_tests.py            # 全部三组
  set JEVSUITESTS=T1,T3 && python ...              # 只跑部分（Windows 请用 env 前缀或改代码）
  JEVCONCURRENCY=6                                 # 并发数，默认 6
需要 .env 里的 TYPESAFE_API_KEY（仅本地读取，不写盘不打印）。
"""
import concurrent.futures as cf
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import von_classify_test as VCT  # noqa: E402  复用同一份分层样本与选项文案
import von_era_test as VE       # noqa: E402
import von_era_yesno_test as VN  # noqa: E402

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
SEED = VCT.SEED
CONC = int(os.environ.get("JEV_CONCURRENCY", "6"))
_lock = threading.Lock()
_tok_in = [0]
_tok_out = [0]


def read_key():
    p = os.path.join(ROOT, ".env")
    for line in open(p, encoding="utf-8"):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("TYPESAFE_API_KEY 不在 .env")


def call(state, questions, key, retries=5):
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    for i in range(retries):
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode())
            ms = (time.perf_counter() - t0) * 1000
            u = data.get("usage") or {}
            with _lock:
                _tok_in[0] += u.get("input_tokens") or 0
                _tok_out[0] += u.get("output_tokens") or 0
            return data, ms, None
        except urllib.error.HTTPError as e:
            code, txt = e.code, e.read().decode()[:200]
            if code in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(1.5 ** i)
                continue
            return None, 0.0, f"HTTP {code} {txt}"
        except Exception as e:  # noqa: BLE001
            if i < retries - 1:
                time.sleep(1.5 ** i)
                continue
            return None, 0.0, repr(e)
    return None, 0.0, "retries exhausted"


def run_batch(jobs, key):
    """jobs: list of (tag, state, questions). Returns {tag: (answers, ms, err)}"""
    out = {}
    errs = []
    with cf.ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = {ex.submit(call, s, q, key): (tag, s, q) for tag, s, q in jobs}
        for f in cf.as_completed(futs):
            tag = futs[f][0]
            data, ms, err = f.result()
            if err:
                errs.append((tag, err))
                out[tag] = (None, ms, err)
            else:
                out[tag] = (data.get("answers") or {}, ms, None)
    if errs:
        print(f"  ! {len(errs)} 次调用失败，示例: {errs[0]}")
    return out


def acc_table(rows, cats, label, gold_key="gold", pred_key="pred"):
    n = len(rows)
    ok = sum(1 for r in rows if r[gold_key] == r[pred_key])
    print(f"\n=== {label} ===\n准确率: {ok}/{n} = {ok/n*100:.1f}%   (随机基线 {100/len(cats):.1f}%)")
    for c in cats:
        sub = [r for r in rows if r[gold_key] == c]
        if sub:
            g = sum(1 for r in sub if r[gold_key] == r[pred_key])
            conf = [r.get("confidence", 0) for r in sub]
            print(f"  {c:<22}{g}/{len(sub)}  均置信 {statistics.mean(conf):.3f}")
    ms = [r["ms"] for r in rows]
    print(f"  延迟 ms(含网络): p50={statistics.median(ms):.0f} mean={statistics.mean(ms):.0f} max={max(ms):.0f}")
    return ok, n


# ────────── T1 领域 8 选 1 ──────────
def t1(techs, key):
    cats = json.load(open(os.path.join(ROOT, "data", "categories.json"), encoding="utf-8"))
    VCT.CAT_ZH = {c["id"]: c["name"] for c in cats}
    VCT.CAT_EN = {c["id"]: c["nameEn"] for c in cats}
    VCT.CAT_SUB = {c["id"]: c["subcategories"] for c in cats}
    items, quota = VCT.stratified_sample(techs)
    random.Random(SEED).shuffle(items)
    print(f"T1 样本: 与 von_classify_test 相同的 {len(items)} 条（配额 {quota}）")
    for cond in ("A", "B"):
        reqs = [VCT.build_request(it, cond) for it in items]
        jobs = [(it["id"], r["state"], r["questions"]) for it, r in zip(items, reqs)]
        res = run_batch(jobs, key)
        rows = []
        for it in items:
            ans, ms, err = res[it["id"]]
            if not ans:
                continue
            a = ans["field"]
            rows.append({"id": it["id"], "gold": it["category"], "pred": a.get("choice"),
                         "confidence": float(a.get("confidence") or 0), "ms": ms,
                         "p_gold": float((a.get("probabilities") or {}).get(it["category"], 0))})
        acc_table(rows, VCT.CAT_ORDER, f"T1 领域 choice 条件 {cond}（Von 同条件: A=43% B=58%）")
        for thr in (0.3, 0.5, 0.7):
            sub = [r for r in rows if r["confidence"] >= thr]
            if sub:
                g = sum(r["gold"] == r["pred"] for r in sub)
                print(f"    门控 conf>={thr}: 覆盖 {len(sub)}/{len(rows)} 准确 {g}/{len(sub)} = {g/len(sub)*100:.1f}%")
        yield f"T1_{cond}", rows


# ────────── T2 时代 11 选 1 ──────────
def t2(techs, eras, key):
    eidx = {e["id"]: i for i, e in enumerate(eras)}
    items = VE.sample_by_era(techs, eras)
    random.Random(SEED).shuffle(items)
    print(f"\nT2 样本: 与 von_era_test 相同的 {len(items)} 条（oracle 年份查表 = 97-100%）")
    von_ref = {"F1": "15%", "F2": "47%", "F3": "11%", "F6": "7%"}
    for cond in ("F1", "F2", "F3", "F6"):
        jobs = []
        for it in items:
            st, q = VE.build(it, cond, eras)
            jobs.append((it["id"], st, q))
        res = run_batch(jobs, key)
        rows = []
        for it in items:
            ans, ms, err = res[it["id"]]
            if not ans:
                continue
            a = ans["field"]
            rows.append({"id": it["id"], "gold": it["era"], "pred": a.get("choice"),
                         "confidence": float(a.get("confidence") or 0), "ms": ms,
                         "err_bins": abs(eidx[a.get("choice", "")] - eidx[it["era"]]) if a.get("choice") in eidx else 99})
        lab = acc_table(rows, [e["id"] for e in eras],
                        f"T2 时代 choice {cond}（Von 同条件: {von_ref[cond]}）")
        w1 = sum(1 for r in rows if r["err_bins"] <= 1)
        print(f"  命中或相邻一档 {w1}/{len(rows)} = {w1/len(rows)*100:.1f}%   "
              f"平均错档 {statistics.mean(r['err_bins'] for r in rows):.2f}")
        yield f"T2_{cond}", rows


# ────────── T3 时代 是/否 AUC ──────────
def auc(pos, neg):
    s = 0.0
    for p in pos:
        for q in neg:
            s += 1.0 if p > q else (0.5 if p == q else 0.0)
    return s / (len(pos) * len(neg))


def t3(techs, eras, key):
    eidx = {e["id"]: i for i, e in enumerate(eras)}
    items = VE.sample_by_era(techs, eras)
    random.Random(SEED).shuffle(items)
    print(f"\nT3 样本: 同 {len(items)} 条，每条 3 个 noul（真/相邻假/跨档假）")
    for cond, sfn, lang in (("N1", lambda t: VN.zh_state(t), "zh"), ("N2", VN.en_state, "en")):
        pairs = []
        for it in items:
            gi = eidx[it["era"]]
            adj = eras[gi + 1 if gi + 1 < len(eras) else gi - 1]["id"]
            far = eras[(gi + 5) % len(eras)]["id"]
            if far in (it["era"], adj):
                far = eras[(gi + 7) % len(eras)]["id"]
            st = sfn(it)
            for kind, eid in (("true", it["era"]), ("adj", adj), ("far", far)):
                q = {"ok": {"type": "noul", "instructions": VN.assertion(eras[eidx[eid]], lang)}}
                pairs.append((f"{it['id']}|{kind}", st, q, it["id"], kind))
        jobs = [(t, s, q) for t, s, q, _, _ in pairs]
        res = run_batch(jobs, key)
        pv = {"true": [], "adj": [], "far": []}
        for t, s, q, _iid, kind in pairs:
            ans, ms, err = res[t]
            if ans:
                pv[kind].append(float(ans["ok"].get("noul") or 0))
        print(f"\n=== T3 是/否 {cond}（Von 同条件 AUC: N1 真vs相邻=0.483 真vs跨档=0.501 / N2 0.463 0.677）===")
        print(f"  p_yes 均值: 真 {statistics.mean(pv['true']):.3f} | 相邻假 {statistics.mean(pv['adj']):.3f} | 跨档假 {statistics.mean(pv['far']):.3f}")
        a1, a2 = auc(pv["true"], pv["adj"]), auc(pv["true"], pv["far"])
        print(f"  AUC 真vs相邻 = {a1:.3f}   AUC 真vs跨档 = {a2:.3f}")
        for k in ("adj", "far"):
            tpr = sum(1 for p in pv["true"] if p >= 0.5) / len(pv["true"])
            tnr = sum(1 for q in pv[k] if q < 0.5) / len(pv[k])
            print(f"    阈值0.5 vs {k}: 真断言接受 {tpr*100:.0f}% 假断言拒绝 {tnr*100:.0f}% 平衡 {(tpr+tnr)/2*100:.1f}%")
        yield f"T3_{cond}", pv


if __name__ == "__main__":
    key = read_key()
    techs, eras = VE.load()
    suites = os.environ.get("JEV_SUITES", "T1,T2,T3").split(",")
    t_all = time.perf_counter()
    all_rows = {}
    for suite in suites:
        s = suite.strip()
        gen = {"T1": lambda: t1(techs, key), "T2": lambda: t2(techs, eras, key),
               "T3": lambda: t3(techs, eras, key)}[s]()
        for name, rows in gen:
            all_rows[name] = rows
    ms_all = [r["ms"] for v in all_rows.values() if v and isinstance(v, list)
              for r in v if isinstance(r, dict) and "ms" in r]
    if ms_all:
        print(f"\n总计: 墙钟 {(time.perf_counter()-t_all)/60:.1f} 分钟，并发 {CONC}，"
              f"token in={_tok_in[0]:,} out={_tok_out[0]:,}，"
              f"单请求延迟 p50={statistics.median(ms_all):.0f}ms "
              f"p95={sorted(ms_all)[int(len(ms_all)*0.95)]:.0f}ms")
    path = os.path.join(ROOT, "data", "jev-replicate-tests.json")
    merged = {}
    if os.path.exists(path):
        merged = json.load(open(path, encoding="utf-8"))
    merged.update(all_rows)
    json.dump(merged, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("明细已写入 data/jev-replicate-tests.json")
