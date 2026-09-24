# -*- coding: utf-8 -*-
"""
Von 时代归类测试：100 条科技，11 选 1 时代。

与 scripts/von_classify_test.py（领域 8 选 1）的区别：时代金标由年份区间客观定义
（全库仅 11/2759 条年份越界），"自定义分类法歧义"这一变量基本被排除，
且存在一个平凡 oracle 基线：year → 区间查表，99.6% 准确。

条件:
  F1 中文状态(名称+释义+年份) + 中文选项(含年份区间)
  F2 英文状态(nameEn+wikiEn+Year) + 英文选项(含区间)
  F3 中文状态但去掉年份（只看语义能否定时代）
  F4 空状态对照（只看选项先验塌缩到哪）
  F5 只给年份（隔离"能否读数字并映射到区间"）

用法: python scripts/von_era_test.py
环境变量: VON_DEVICE=cuda|cpu, VON_CONDITIONS=F1,F2,...
"""
import json
import os
import random
import time

import torch
from von.engine import VonEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 20260921


def load():
    techs = json.load(open(os.path.join(ROOT, "data", "techs.json"), encoding="utf-8"))
    eras = sorted(json.load(open(os.path.join(ROOT, "data", "eras.json"), encoding="utf-8")),
                  key=lambda e: e["order"])
    return techs, eras


def sample_by_era(techs, eras, n=100, rng=random.Random(SEED)):
    """11 个时代均匀分层：每层 base 条，余数给规模大的层。"""
    by = {}
    for t in techs:
        by.setdefault(t["era"], []).append(t)
    k = len(eras)
    base = n // k
    quota = {e["id"]: base for e in eras}
    rem = n - base * k
    for e in sorted(eras, key=lambda x: -len(by[x["id"]]))[:rem]:
        quota[e["id"]] += 1
    items = []
    for e in eras:
        pool = by[e["id"]]
        take = min(quota[e["id"]], len(pool))
        items.extend(rng.sample(pool, take))
    return items


def criteria(eras, lang, with_range=True):
    out = {}
    for e in eras:
        if lang == "zh":
            label = e["name"]
            rng = f"约 {e['yearStart']} 至 {e['yearEnd']} 年" if with_range else ""
        else:
            label = e["nameEn"]
            rng = f"roughly {e['yearStart']} to {e['yearEnd']}" if with_range else ""
        out[e["id"]] = f"{label}（{rng}）" if (lang == "zh" and with_range) else (
            f"{label} ({rng})" if with_range else label)
    return out


def build(item, cond, eras):
    zh = cond in ("F1", "F3", "F4", "F5")
    if cond == "F4":
        state = "（空状态，无任何条目信息）" if zh else "(empty state)"
        crit = criteria(eras, "zh")
        inst = "这项科技属于哪个时代？"
    elif cond == "F5":
        y = item["year"]
        state = f"年份：{y}" if zh else f"Year: {y}"
        crit = criteria(eras, "zh")
        inst = "这项科技属于哪个时代？"
    elif cond == "F3":
        state = (f"名称：{item['name'] or item['nameEn']}\n释义：{item.get('desc', '')}")
        crit = criteria(eras, "zh")
        inst = "这项科技属于哪个时代？"
    elif cond == "F6":  # 与 F2 只差年份一项： Von 无法用数字，去掉它对准确率的影响可忽略
        state = (f"Name: {item['nameEn']}\n"
                 f"Wikipedia article title: {item.get('wikiEn', '')}")
        crit = criteria(eras, "en")
        inst = "Which era does this technology belong to?"
    elif cond == "F1":
        state = (f"名称：{item['name'] or item['nameEn']}\n"
                 f"释义：{item.get('desc', '')}\n年份：{item['year']}")
        crit = criteria(eras, "zh")
        inst = "这项科技属于哪个时代？"
    else:  # F2
        state = (f"Name: {item['nameEn']}\n"
                 f"Wikipedia article title: {item.get('wikiEn', '')}\nYear: {item['year']}")
        crit = criteria(eras, "en")
        inst = "Which era does this technology belong to?"
    return state, {"field": {"type": "choice", "instructions": inst, "criteria": crit}}


def oracle(item, eras):
    for e in eras:
        if e["yearStart"] <= item["year"] <= e["yearEnd"]:
            return e["id"]
    best = min(eras, key=lambda e: min(abs(item["year"] - e["yearStart"]), abs(item["year"] - e["yearEnd"])))
    return best["id"]


def summarize(rows, eras, label):
    idx = {e["id"]: i for i, e in enumerate(eras)}
    n = len(rows)
    ok = sum(r["correct"] for r in rows)
    print(f"\n=== 条件 {label} ===")
    print(f"总体准确率: {ok}/{n} = {ok/n*100:.1f}%   (随机基线 {100/len(eras):.1f}%)")
    off1 = sum(1 for r in rows if abs(idx[r["pred"]] - idx[r["gold"]]) <= 1)
    far = [r for r in rows if abs(idx[r["pred"]] - idx[r["gold"]]) > 1]
    mae = sum(abs(idx[r["pred"]] - idx[r["gold"]]) for r in rows) / n
    print(f"命中或相邻一档: {off1}/{n} = {off1/n*100:.1f}%   平均错 {mae:.2f} 档   跨档(>1) {len(far)} 条")
    print(f"{'时代':<20}{'准确':<10}{'均置信':<8}{'p_gold'}")
    for e in eras:
        sub = [r for r in rows if r["gold"] == e["id"]]
        if not sub:
            continue
        good = sum(r["correct"] for r in sub)
        print(f"{e['id']:<20}{f'{good}/{len(sub)}':<10}"
              f"{sum(r['confidence'] for r in sub)/len(sub):<8.3f}"
              f"{sum(r['p_gold'] for r in sub)/len(sub):.3f}")
    ms = sorted(r["ms"] for r in rows)
    print(f"延迟 ms: p50={ms[len(ms)//2]:.1f} mean={sum(ms)/len(ms):.1f}")
    print("错例: " + ", ".join(f"{r['id']}(金{r['gold']}→{r['pred']},置信{r['confidence']:.2f})"
                              for r in rows if not r["correct"]))
    for thr in (0.4, 0.5, 0.6):
        sub = [r for r in rows if r["confidence"] >= thr]
        if sub:
            good = sum(r["correct"] for r in sub)
            print(f"  门控 confidence>={thr}: 覆盖 {len(sub)} 条，准确 {good}/{len(sub)} = {good/len(sub)*100:.1f}%")


if __name__ == "__main__":
    techs, eras = load()
    rng = random.Random(SEED)
    items = sample_by_era(techs, eras)
    rng.shuffle(items)
    print(f"抽样 {len(items)} 条（seed {SEED}，按 11 时代均匀分层，每层 9-10 条）")
    orc = sum(1 for t in items if oracle(t, eras) == t["era"])
    print(f"oracle 基线（纯年份查区间，无模型）: {orc}/{len(items)} = {orc/len(items)*100:.1f}%")

    eng = VonEngine(backend_name="von-1.0", device=os.environ.get("VON_DEVICE"))
    print("device:", getattr(eng.backend, "device", "unknown"))
    pool = [t for t in techs if t["id"] not in {i["id"] for i in items}]
    for w in rng.sample(pool, 8):
        st, q = build(w, "F1", eras)
        eng.evaluate(state=st, questions=q)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    out = {}
    path = os.path.join(ROOT, "data", "von-era-test.json")
    if os.path.exists(path):
        out = json.load(open(path, encoding="utf-8"))
    for cond in os.environ.get("VON_CONDITIONS", "F1,F2,F3,F4,F5").split(","):
        cond = cond.strip()
        rows = []
        for it in items:
            st, q = build(it, cond, eras)
            t0 = time.perf_counter()
            resp = eng.evaluate(state=st, questions=q)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            a = resp.answers["field"]
            probs = a.probabilities or {}
            rows.append({"id": it["id"], "gold": it["era"], "pred": a.choice,
                         "correct": a.choice == it["era"],
                         "confidence": round(float(a.confidence), 4),
                         "p_gold": round(float(probs.get(it["era"], 0.0)), 4),
                         "ms": round((time.perf_counter() - t0) * 1000, 2)})
        summarize(rows, eras, cond)
        out[cond] = rows
    json.dump(out, open(os.path.join(ROOT, "data", "von-era-test.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n明细已写入 data/von-era-test.json")
