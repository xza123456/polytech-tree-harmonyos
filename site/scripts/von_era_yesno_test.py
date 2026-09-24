# -*- coding: utf-8 -*-
"""
Von 是/否判定测试：给一条科技 + 我们项目的一个时代断言，只让 Von 回答"对还是错"(noul)。

两部分:
  Part 1 判别力：每条出 1 个真断言 + 1 个相邻档假断言 + 1 个跨档假断言，看 p_yes 能否分开
         （AUC、0.5 阈值的平衡准确率、均值差）。空状态对照给出"逢断言就答对"的先验。
  Part 2 不同读出：对 11 个时代逐个问 yes/no，取 p_yes 最大者为答案，与 choice 模式
         （von_era_test.py 的 F1 中文 15% / F2 英文 47%）直接对比。

条件（Part 1）:
  N1 中文状态(名称+释义) + 中文断言（只写时代名）
  N2 英文状态(nameEn+wikiEn) + 英文断言
  N3 中文状态额外给年份 + 中文断言（测"知道自己年份"能否救回判定）
  N5 中文状态 + 中文断言带年份区间（测区间文字有没有用）
  N4 空状态对照

用法: python scripts/von_era_yesno_test.py
"""
import json
import os
import random
import sys
import time

import torch
from von.engine import VonEngine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from von_era_test import load, sample_by_era, SEED  # noqa: E402  复用同一份 100 条样本

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def zh_state(t, with_year=False):
    s = f"名称：{t['name'] or t['nameEn']}\n释义：{t.get('desc', '')}"
    return s + f"\n年份：{t['year']}" if with_year else s


def en_state(t):
    return (f"Name: {t['nameEn']}\n"
            f"Wikipedia article title: {t.get('wikiEn', '')}")


def assertion(e, lang, with_range=False, mode="q"):
    """mode='q' 是问句式（这条断言是否为真）；mode='d' 是陈述式（直接给待判假设）。
    noul 的近零概率可能来自提问句式而非知识本身，所以两种都要测。"""
    if lang == "zh":
        lab = f"「{e['name']}」" + (f"（{e['yearStart']}–{e['yearEnd']}年）" if with_range else "")
        return (f"这条断言是否为真：该科技属于{lab}。" if mode == "q"
                else f"该科技属于{lab}。")
    lab = f"\"{e['nameEn']}\"" + (f" ({e['yearStart']}-{e['yearEnd']})" if with_range else "")
    return (f"Is this claim true: this technology belongs to the era {lab}." if mode == "q"
            else f"This technology belongs to the era {lab}.")


def ask(eng, state, qtext):
    resp = eng.evaluate(state=state, questions={"ok": {"type": "noul", "instructions": qtext}})
    return float(resp.answers["ok"].noul)


def ask_multi(eng, state, qt):
    """一次 evaluate 里放 N 个 noul 问题：N 次前向，但省掉 N 次 Python 往返。"""
    qs = {f"q{i}": {"type": "noul", "instructions": q} for i, q in enumerate(qt)}
    resp = eng.evaluate(state=state, questions=qs)
    return [float(resp.answers[f"q{i}"].noul) for i in range(len(qt))]


def auc(pos, neg):
    """Mann-Whitney：随机取一个真断言分数高于随机假断言分数的概率（并列算 0.5）。"""
    s = 0.0
    for p in pos:
        for q in neg:
            s += 1.0 if p > q else (0.5 if p == q else 0.0)
    return s / (len(pos) * len(neg))


def bal_acc(pos, neg, thr=0.5):
    tpr = sum(1 for p in pos if p >= thr) / len(pos)
    tnr = sum(1 for q in neg if q < thr) / len(neg)
    return tpr, tnr, (tpr + tnr) / 2


def part1(eng, items, eras, eidx):
    cond_plan = {  # cond -> (state_fn, lang, with_range, mode)
        "N1": (lambda t: zh_state(t), "zh", False, "q"),
        "N2": (en_state, "en", False, "q"),
        "N3": (lambda t: zh_state(t, True), "zh", False, "q"),
        "N5": (lambda t: zh_state(t), "zh", True, "q"),
        "N4": (lambda t: "（空状态，无任何条目信息）", "zh", False, "q"),
        "N1d": (lambda t: zh_state(t), "zh", False, "d"),
        "N2d": (en_state, "en", False, "d"),
        "N3d": (lambda t: zh_state(t, True), "zh", False, "d"),
    }
    keep = os.environ.get("VON_P1")
    if keep:
        cond_plan = {k: v for k, v in cond_plan.items() if k in keep.split(",")}
    out = {}
    for cond, (sfn, lang, wr, mode) in cond_plan.items():
        rows = []
        for it in items:
            gi = eidx[it["era"]]
            adj = eras[min(gi + 1, len(eras) - 1) if gi + 1 < len(eras) else gi - 1]["id"]
            far = eras[(gi + 5) % len(eras)]["id"]
            if far == it["era"] or far == adj:
                far = eras[(gi + 7) % len(eras)]["id"]
            st = sfn(it)
            t0 = time.perf_counter()
            p_true = ask(eng, st, assertion(eras[gi], lang, wr, mode))
            p_adj = ask(eng, st, assertion(eras[eidx[adj]], lang, wr, mode))
            p_far = ask(eng, st, assertion(eras[eidx[far]], lang, wr, mode))
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            rows.append({"id": it["id"], "gold": it["era"], "adj": adj, "far": far,
                         "p_true": round(p_true, 4), "p_adj": round(p_adj, 4),
                         "p_far": round(p_far, 4),
                         "ms": round((time.perf_counter() - t0) * 1000, 2)})
        pos = [r["p_true"] for r in rows]
        adjn = [r["p_adj"] for r in rows]
        farn = [r["p_far"] for r in rows]
        print(f"\n=== Part1 {cond} ===")
        print(f"p_yes 均值: 真断言 {sum(pos)/len(pos):.3f} | 相邻假 {sum(adjn)/len(adjn):.3f} | 跨档假 {sum(farn)/len(farn):.3f}")
        print(f"AUC(真 vs 相邻假) = {auc(pos, adjn):.3f}   AUC(真 vs 跨档假) = {auc(pos, farn):.3f}")
        for name, neg in (("相邻", adjn), ("跨档", farn)):
            tpr, tnr, ba = bal_acc(pos, neg)
            print(f"  阈值0.5 vs {name}: 真断言判对(接受) {tpr*100:.0f}%  假断言判对(拒绝) {tnr*100:.0f}%  平衡准确率 {ba*100:.1f}%")
        best = max(((bal_acc(pos, neg, t)[2], t, k) for k, neg in (("相邻", adjn), ("跨档", farn)) for t in [x / 20 for x in range(1, 20)]))
        print(f"  最优阈值(在此批上选, 偏乐观): 平衡准确率 {best[0]*100:.1f}% @ thr={best[1]:.2f}（{best[2]}）")
        print(f"  3 问/条 延迟: p50 {sorted(r['ms'] for r in rows)[len(rows)//2]:.0f}ms")
        out[cond] = rows
    return out


def part2(eng, items, eras, eidx):
    out = {}
    for cond, sfn, lang in (("P_zh", lambda t: zh_state(t), "zh"), ("P_en", en_state, "en")):
        rows = []
        for it in items:
            st = sfn(it)
            t0 = time.perf_counter()
            ps = dict(zip([e["id"] for e in eras],
                          ask_multi(eng, st, [assertion(e, lang, mode="d") for e in eras])))
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            gold = it["era"]
            ranked = sorted(ps, key=ps.get, reverse=True)
            pred = ranked[0]
            in_top3 = gold in ranked[:3]
            rows.append({"id": it["id"], "gold": gold, "pred": pred,
                         "correct": pred == gold, "in_top3": in_top3,
                         "p_max": round(ps[pred], 4), "p_gold": round(ps[gold], 4),
                         "gap_top1": round(ps[pred] - ps[ranked[1]], 4),
                         "gap_gold": round(ps[gold] - (ps[ranked[1]] if pred == gold else ps[pred]), 4),
                         "ms": round((time.perf_counter() - t0) * 1000, 2)})
        n = len(rows)
        ok = sum(r["correct"] for r in rows)
        t3 = sum(r["in_top3"] for r in rows)
        print(f"\n=== Part2 {cond}（陈述式，11 个 noul 一次调用，{11*n} 次前向）===")
        print(f"top1 准确率: {ok}/{n} = {ok/n*100:.1f}%   top3 命中率: {t3}/{n} = {t3/n*100:.1f}%"
              f"   （随机基线 top1 {100/11:.1f}% / top3 {300/11:.1f}%；choice 读出对照: 本状态无年份，"
              f"中文 F3=11% / 英文未测带年份外的组合，F1 中文含年份=15%、F2 英文含年份=47%）")
        ms = sorted(r["ms"] for r in rows)
        print(f"每条 11 问总延迟: p50={ms[n//2]:.0f}ms mean={sum(ms)/n:.0f}ms")
        print(f"p_yes 范围: {min(r['p_max'] for r in rows):.3f} ~ {max(r['p_max'] for r in rows):.3f}"
              f"（均值 {sum(r['p_max'] for r in rows)/n:.3f}）")
        for thr in (0.1, 0.2, 0.3, 0.5):
            sub = [r for r in rows if r["p_max"] >= thr]
            if sub:
                g = sum(r["correct"] for r in sub)
                print(f"  门控 p_max>={thr}: 覆盖 {len(sub)}/{n}，准确 {g}/{len(sub)} = {g/len(sub)*100:.1f}%")
        for thr in (0.1, 0.2):
            sub = [r for r in rows if r["gap_top1"] >= thr]
            if sub:
                g = sum(r["correct"] for r in sub)
                print(f"  门控 top1-top2 差>={thr}: 覆盖 {len(sub)}/{n}，准确 {g}/{len(sub)} = {g/len(sub)*100:.1f}%")
        out[cond] = rows
    return out


if __name__ == "__main__":
    techs, eras = load()
    eidx = {e["id"]: i for i, e in enumerate(eras)}
    rng = random.Random(SEED)
    items = sample_by_era(techs, eras)
    rng.shuffle(items)
    print(f"样本: 与 von_era_test.py 相同的 {len(items)} 条（seed {SEED}，按 11 时代分层）")
    eng = VonEngine(backend_name="von-1.0", device=os.environ.get("VON_DEVICE"))
    print("device:", getattr(eng.backend, "device", "unknown"))
    pool = [t for t in techs if t["id"] not in {i["id"] for i in items}]
    for w in rng.sample(pool, 8):
        ask(eng, zh_state(w), assertion(eras[0], "zh"))
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    path = os.path.join(ROOT, "data", "von-era-yesno.json")
    res = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    res["_meta"] = {"seed": SEED, "n": len(items)}
    if os.environ.get("VON_PART1", "1") == "1":
        res.setdefault("part1", {}).update(part1(eng, items, eras, eidx))
    if os.environ.get("VON_PART2", "1") == "1":
        res.setdefault("part2", {}).update(part2(eng, items, eras, eidx))
    json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n明细已写入 data/von-era-yesno.json")
