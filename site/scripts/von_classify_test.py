# -*- coding: utf-8 -*-
"""
Von 本地分类能力测试：用 data/techs.json 的科技条目，让 Von 做 8 选 1 领域归类。

用法:
  python scripts/von_classify_test.py [每类上限]
环境变量:
  VON_DEVICE=cuda|cpu   条件: VON_CONDITIONS=A,B
"""
import json
import os
import random
import sys
import time

import torch
from von.engine import VonEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 20260921
CAT_ORDER = ["materials", "energy_power", "information", "life_medicine",
             "transport_exploration", "math_logic", "physical_science", "society"]

# 条件 A（中文）的 criteria 直接用 categories.json 的中文名 + 原样子类清单。
# 条件 B（英文）的子类清单为人工对译，脚本内固定，避免每次跑动漂移。
SUB_EN = {
    "materials": "stone tools, metallurgy, chemical engineering, textile machinery, semiconductor process, manufacturing process",
    "energy_power": "fire, steam, electricity, nuclear power, engines, new energy",
    "information": "writing, printing, telecommunications, computers, artificial intelligence, scientific instruments, software and networks, algorithms",
    "life_medicine": "agriculture and husbandry, food, medicine, vaccines, genetics and biology, medical imaging",
    "transport_exploration": "wheels, ships, land vehicles, aviation, spaceflight, navigation",
    "math_logic": "number theory and algebra, geometry and topology, analysis, probability and statistics, discrete and combinatorics, mathematical logic, applied and computational mathematics",
    "physical_science": "mechanics, electromagnetism and optics, thermodynamics and statistics, modern physics, chemical theory, astronomy, earth science",
    "society": "economics and finance, law and public institutions, management and organization, psychology linguistics and sociology, culture and sports, daily life",
}


def stratified_sample(techs, n=100, rng=random.Random(SEED)):
    """按类目规模比例抽样，每类下限 8、上限 20。"""
    by_cat = {}
    for t in techs:
        by_cat.setdefault(t["category"], []).append(t)
    total = len(techs)
    quota = {}
    for c in CAT_ORDER:
        size = len(by_cat[c])
        quota[c] = max(8, min(20, round(size / total * n)))
    while sum(quota.values()) > n:
        c = max(quota, key=lambda k: quota[k])
        quota[c] -= 1
    sample = []
    for c in CAT_ORDER:
        pool = by_cat[c]
        take = min(quota[c], len(pool))
        sample.extend(rng.sample(pool, take))
        quota[c] = take
    return sample, quota


def _state(item, s_lang):
    if s_lang == "zh":
        return (f"名称：{item['name'] or item['nameEn']}\n"
                f"释义：{item.get('desc', '')}\n"
                f"年份：{item['year']}")
    return (f"Name: {item['nameEn']}\n"
            f"Wikipedia article title: {item.get('wikiEn', '')}\n"
            f"Year: {item['year']}")


def _criteria(c_lang):
    if c_lang == "zh":
        return {c: f"{CAT_ZH[c]}：{'、'.join(CAT_SUB[c])}" for c in CAT_ORDER}
    return {c: f"{CAT_EN[c]}: covering {SUB_EN[c]}" for c in CAT_ORDER}


# 条件 A/B 是"状态语言与选项语言一致"的两个角；C/D 是错配的两个角，
# 用来区分"读不进中文释义"和"中文选项措辞不利"。
COND = {"A": ("zh", "zh"), "B": ("en", "en"), "C": ("en", "zh"), "D": ("zh", "en")}


def build_request(item, cond):
    if cond == "CTRL":
        # 空状态对照：只给 criteria，不给条目信息。
        # 若条件 A 的准确率与对照组接近，说明 A 的预测来自 criteria 先验而非条目内容。
        return {"state": "（空状态，无任何条目信息）",
                "questions": {"field": {"type": "choice",
                                        "instructions": "这项科技属于哪个领域？",
                                        "criteria": _criteria("zh")}}}
    if cond == "NULLB":
        return {"state": "(empty state, no item information)",
                "questions": {"field": {"type": "choice",
                                        "instructions": "Which field does this technology belong to?",
                                        "criteria": _criteria("en")}}}
    s_lang, c_lang = COND[cond]
    q = {"type": "choice",
         "instructions": "这项科技属于哪个领域？" if c_lang == "zh" else "Which field does this technology belong to?",
         "criteria": _criteria(c_lang)}
    return {"state": _state(item, s_lang), "questions": {"field": q}}


def run(eng, items, cond):
    rows = []
    for it in items:
        req = build_request(it, cond)
        t0 = time.perf_counter()
        resp = eng.evaluate(state=req["state"], questions=req["questions"])
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        a = resp.answers["field"]
        probs = a.probabilities or {}
        top = sorted(probs.items(), key=lambda kv: -kv[1])
        gold = it["category"]
        rows.append({
            "id": it["id"], "gold": gold, "pred": a.choice,
            "correct": a.choice == gold,
            "confidence": round(float(a.confidence), 4),
            "p_gold": round(float(probs.get(gold, 0.0)), 4),
            "top": [[k, round(float(v), 4)] for k, v in top[:3]],
            "ms": round(ms, 2),
        })
    return rows


def pct(x, n):
    return f"{x}/{n} = {x / n * 100:.1f}%"


def summarize(rows, label):
    n = len(rows)
    ok = sum(r["correct"] for r in rows)
    print(f"\n=== 条件 {label} ===")
    print(f"总体准确率: {pct(ok, n)}")
    print(f"{'领域':<24}{'准确':<12}{'均置信':<9}{'p_gold':<8}")
    for c in CAT_ORDER:
        sub = [r for r in rows if r["gold"] == c]
        if not sub:
            continue
        good = sum(r["correct"] for r in sub)
        mc = sum(r["confidence"] for r in sub) / len(sub)
        mg = sum(r["p_gold"] for r in sub) / len(sub)
        print(f"{c:<24}{pct(good, len(sub)):<12}{mc:<9.3f}{mg:<8.3f}")
    bands = [(0.0, 0.2), (0.2, 0.5), (0.5, 1.01)]
    print("置信度分档 (confidence = top1-top2 差值):")
    for lo, hi in bands:
        sub = [r for r in rows if lo <= r["confidence"] < hi]
        if sub:
            good = sum(r["correct"] for r in sub)
            print(f"  [{lo:.1f},{hi:.1f}) n={len(sub):<4}准确 {pct(good, len(sub))}")
    ms = sorted(r["ms"] for r in rows)
    print(f"延迟 ms: p50={ms[len(ms)//2]:.1f} mean={sum(ms)/len(ms):.1f} max={ms[-1]:.1f}")
    pred = {}
    for r in rows:
        pred[r["pred"]] = pred.get(r["pred"], 0) + 1
    print("预测分布: " + "  ".join(f"{c}={pred.get(c,0)}(金标{sum(1 for x in rows if x['gold']==c)})" for c in CAT_ORDER))
    for thr in (0.4, 0.5, 0.6):
        sub = [r for r in rows if r["confidence"] >= thr]
        if sub:
            good = sum(r["correct"] for r in sub)
            print(f"  门控 confidence>={thr}: 覆盖 {len(sub)} 条，准确 {pct(good, len(sub))}")
    wrong = [r for r in rows if not r["correct"]]
    print(f"错例 {len(wrong)} 条: " + ", ".join(f"{r['id']}({r['gold']}→{r['pred']})" for r in wrong))
    return rows, wrong


if __name__ == "__main__":
    techs = json.load(open(os.path.join(ROOT, "data", "techs.json"), encoding="utf-8"))
    cats = json.load(open(os.path.join(ROOT, "data", "categories.json"), encoding="utf-8"))
    CAT_ZH = {c["id"]: c["name"] for c in cats}
    CAT_EN = {c["id"]: c["nameEn"] for c in cats}
    CAT_SUB = {c["id"]: c["subcategories"] for c in cats}

    items, quota = stratified_sample(techs)
    rng = random.Random(SEED)
    rng.shuffle(items)
    print(f"抽样 {len(items)} 条（种子 {SEED}，分层配额 {quota}）")

    eng = VonEngine(backend_name="von-1.0", device=os.environ.get("VON_DEVICE"))
    print("device:", getattr(eng.backend, "device", "unknown"))

    pool = [t for t in techs if t["id"] not in {i["id"] for i in items}]
    for w in rng.sample(pool, 8):
        req = build_request(w, "A")
        eng.evaluate(state=req["state"], questions=req["questions"])
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    print("warmup 完成（8 次，测试集外条目）")

    conds = os.environ.get("VON_CONDITIONS", "A,B").split(",")
    out = {}
    for cond in conds:
        cond = cond.strip()
        rows = run(eng, items, cond)
        summarize(rows, cond)
        out[cond] = rows
    json.dump(out, open(os.path.join(ROOT, "data", "von-classify-test.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n明细已写入 data/von-classify-test.json")
