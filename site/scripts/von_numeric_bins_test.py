# -*- coding: utf-8 -*-
"""
Von 数值区间判年份测试：选项不写"史前/青铜时代"这类时代词，只写"多少年到多少年"。

目的：排除上一轮 (scripts/von_era_test.py) 里"时代名语义模糊 → 塌缩到史前"这个混淆变量。
金标 = year → 区间查表（按构造 oracle = 100%），模型状态里不给年份。

条件:
  G1 中文状态(名称+释义) + 中文数值区间选项
  G2 英文状态(nameEn+wikiEn) + 英文数值区间选项   ← 与 G1 只差语言，金标/区间完全相同
  G3 中文状态只给名称（不给释义）
  G4 空状态对照（数值区间选项的先验塌缩点）
  S1/S2 同状态用 score（7 档有序），把概率加权档位插值回年份 → 直接测"能否估年份"

用法: python scripts/von_numeric_bins_test.py
"""
import json
import os
import random
import statistics
import time

import torch
from von.engine import VonEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 20260921

# (key, 年份下界含, 上界不含, 中文标签, 英文标签, 用于 score→年份 的档中值)
BINS = [
    ("b_bce", -10**9, 0, "公元前（早于公元 0 年）", "before year 0 (BCE)", -3000),
    ("b_0_500", 0, 500, "公元 0 年到 500 年", "year 0 to 500 CE", 250),
    ("b_500_1500", 500, 1500, "公元 500 年到 1500 年", "year 500 to 1500 CE", 1000),
    ("b_1500_1800", 1500, 1800, "公元 1500 年到 1800 年", "year 1500 to 1800 CE", 1650),
    ("b_1800_1950", 1800, 1950, "公元 1800 年到 1950 年", "year 1800 to 1950 CE", 1875),
    ("b_1950_2000", 1950, 2000, "公元 1950 年到 2000 年", "year 1950 to 2000 CE", 1975),
    ("b_2000", 2000, 10**9, "公元 2000 年以后", "after year 2000 CE", 2012),
]
KEYS = [b[0] for b in BINS]
MID = {b[0]: b[5] for b in BINS}


def bin_of(year):
    for k, lo, hi, *_ in BINS:
        if lo <= year < hi:
            return k
    return KEYS[-1]


def label(k, lang):
    row = next(b for b in BINS if b[0] == k)
    return row[3] if lang == "zh" else row[4]


def sample(techs, n=100, rng=random.Random(SEED)):
    by = {}
    for t in techs:
        by.setdefault(bin_of(t["year"]), []).append(t)
    base, rem = n // len(BINS), n % len(BINS)
    quota = {k: base for k in KEYS}
    for k in sorted(KEYS, key=lambda x: -len(by[x]))[:rem]:
        quota[k] += 1
    items = []
    for k in KEYS:
        items.extend(rng.sample(by[k], min(quota[k], len(by[k]))))
    return items, {k: len(by[k]) for k in KEYS}


def build(item, cond):
    if cond == "G4":
        state, lang = "（空状态，无任何条目信息）", "zh"
    elif cond in ("G1", "S1"):
        state = (f"名称：{item['name'] or item['nameEn']}\n释义：{item.get('desc', '')}")
        lang = "zh"
    elif cond == "G3":
        state = f"名称：{item['name'] or item['nameEn']}"
        lang = "zh"
    else:  # G2 / S2
        state = (f"Name: {item['nameEn']}\n"
                 f"Wikipedia article title: {item.get('wikiEn', '')}")
        lang = "en"
    if cond.startswith("S"):
        q = {"type": "score",
             "instructions": "这项科技大致出现在哪个时间段？" if lang == "zh" else
                             "Roughly when was this technology introduced?",
             "criteria": [label(k, lang) for k in KEYS]}
        return state, {"when": q}
    q = {"type": "choice",
         "instructions": "这项科技出现在哪个时间段？" if lang == "zh" else
                         "Which time range was this technology introduced in?",
         "criteria": {k: label(k, lang) for k in KEYS}}
    return state, {"when": q}


def score_to_year(ans):
    """把 score 的概率加权档位插值到年份。实测 .score 是 legend 键（0 基档号）的期望值，
    即取值范围 0~len(levels)-1，不是 1~len(levels)。"""
    s = max(0.0, min(len(KEYS) - 1.0, float(ans.score)))
    i = int(s)
    j = min(len(KEYS) - 1, i + 1)
    f = s - i
    return round(MID[KEYS[i]] * (1 - f) + MID[KEYS[j]] * f)


def report(rows, label_):
    n = len(rows)
    print(f"\n=== {label_} ===")
    if "est" in rows[0]:
        sc = [r["score"] for r in rows]
        print(f"score 档位范围: {min(sc):.2f} ~ {max(sc):.2f}（档序 0~6）→ 年份 {min(r['est'] for r in rows)} ~ {max(r['est'] for r in rows)}")
        errs = [abs(r["est"] - r["gold_year"]) for r in rows]
        nz = [abs(r["est"] - r["gold_year"]) for r in rows if r["gold_year"] > -1000]
        print(f"年份估计误差: 中位 {statistics.median(errs):.0f} 年  平均 {sum(errs)/n:.0f} 年")
        print(f"  仅看公元后条目(n={len(nz)}): 中位 {statistics.median(nz):.0f} 年  平均 {sum(nz)/len(nz):.0f} 年")
        print(f"  |误差|<=250年 {sum(1 for e in nz if e<=250)}/{len(nz)}   <=1000年 {sum(1 for e in nz if e<=1000)}/{len(nz)}")
        bias = sum(r["est"] - r["gold_year"] for r in rows if r["gold_year"] > -1000) / len(nz)
        print(f"  公元后条目平均偏差: {bias:+.0f} 年（正=估晚，负=估早）")
        base = statistics.median([r["gold_year"] for r in rows])
        bc = [abs(base - r["gold_year"]) for r in rows]
        bz = [abs(base - r["gold_year"]) for r in rows if r["gold_year"] > -1000]
        print(f"  常数基线（全猜样本中位数 {base} 年）: 全体中位误差 {statistics.median(bc):.0f} 年，"
              f"公元后条目 {statistics.median(bz):.0f} 年")
        for thr in (0.4, 0.5):
            sub = [r for r in rows if r["confidence"] >= thr and r["gold_year"] > -1000]
            if sub:
                g = [abs(r["est"] - r["gold_year"]) for r in sub]
                print(f"  门控 conf>={thr}: 覆盖 {len(sub)}，中位误差 {statistics.median(g):.0f} 年")
        return
    ki = {k: i for i, k in enumerate(KEYS)}
    ok = sum(r["correct"] for r in rows)
    print(f"总体准确率: {ok}/{n} = {ok/n*100:.1f}%   (随机基线 {100/len(KEYS):.1f}%)")
    if "err_bins" in rows[0]:
        w1 = sum(1 for r in rows if r["err_bins"] <= 1)
        mae = sum(r["err_bins"] for r in rows) / n
        print(f"命中或相邻一档: {w1}/{n} = {w1/n*100:.1f}%   平均错 {mae:.2f} 档")
        early = sum(1 for r in rows if r["signed"] < 0)
        late = sum(1 for r in rows if r["signed"] > 0)
        print(f"方向: 偏早 {early} / 偏晚 {late} / 命中 {ok}")
        print(f"{'区间':<14}{'准确':<9}{'均置信':<8}{'p_gold'}")
        for k in KEYS:
            sub = [r for r in rows if r["gold"] == k]
            if sub:
                g = sum(r["correct"] for r in sub)
                print(f"{k:<14}{f'{g}/{len(sub)}':<9}"
                      f"{sum(r['confidence'] for r in sub)/len(sub):<8.3f}"
                      f"{sum(r['p_gold'] for r in sub)/len(sub):.3f}")
        pr = {}
        for r in rows:
            pr[r["pred"]] = pr.get(r["pred"], 0) + 1
        print("预测分布: " + "  ".join(f"{k}={pr.get(k,0)}" for k in KEYS))
        for thr in (0.4, 0.5):
            sub = [r for r in rows if r["confidence"] >= thr]
            if sub:
                g = sum(r["correct"] for r in sub)
                print(f"  门控 conf>={thr}: 覆盖 {len(sub)}，准确 {g}/{len(sub)} = {g/len(sub)*100:.1f}%")


if __name__ == "__main__":
    techs = json.load(open(os.path.join(ROOT, "data", "techs.json"), encoding="utf-8"))
    rng = random.Random(SEED)
    items, sizes = sample(techs)
    rng.shuffle(items)
    print(f"抽样 {len(items)} 条（seed {SEED}，按 7 个数值区间分层）全库区间规模 {sizes}")

    eng = VonEngine(backend_name="von-1.0", device=os.environ.get("VON_DEVICE"))
    print("device:", getattr(eng.backend, "device", "unknown"),
          "| oracle（年份查区间，无模型）: 100/100")
    pool = [t for t in techs if t["id"] not in {i["id"] for i in items}]
    for w in rng.sample(pool, 8):
        st, q = build(w, "G1")
        eng.evaluate(state=st, questions=q)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    out = {}
    for cond in os.environ.get("VON_CONDITIONS", "S1,S2").split(","):
        cond = cond.strip()
        rows = []
        for it in items:
            st, q = build(it, cond)
            t0 = time.perf_counter()
            resp = eng.evaluate(state=st, questions=q)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            a = resp.answers["when"]
            gold = bin_of(it["year"])
            if cond.startswith("S"):
                est = score_to_year(a)
                rows.append({"id": it["id"], "gold_bin": gold, "gold_year": it["year"],
                             "est": est, "score": round(float(a.score), 3),
                             "confidence": round(float(a.confidence), 4)})
            else:
                probs = a.probabilities or {}
                rows.append({"id": it["id"], "gold": gold, "pred": a.choice,
                             "correct": a.choice == gold,
                             "signed": KEYS.index(a.choice) - KEYS.index(gold) if a.choice in KEYS and gold in KEYS else 0,
                             "err_bins": abs(KEYS.index(a.choice) - KEYS.index(gold)) if a.choice in KEYS else 99,
                             "confidence": round(float(a.confidence), 4),
                             "p_gold": round(float(probs.get(gold, 0.0)), 4)})
        report(rows, cond)
        out[cond] = rows
    json.dump(out, open(os.path.join(ROOT, "data", "von-numeric-bins-test.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n明细已写入 data/von-numeric-bins-test.json")
