# -*- coding: utf-8 -*-
"""
desc 原创性全量闸：把 `jev_desc_calib.py` 校准出的**子句级**判据用到全量新条目上。

背景：许可证决定要求发布前 desc 是改写而非逐句翻译（旧语料实测整句翻译 10%、含片段 28%）。
上一轮的校准结论是——整句级判据概率上限只有 0.37 且会误伤，**子句级 ≥0.40 是零误伤的
重写队列**（50 条人工标注集上验证）。本轮净增 ~470 条中文 desc 是各批次代理写的，
只抽查过 24 条，没有全量过闸；库已公开，这条义务更紧迫。

判据与校准脚本完全一致（直接 import `jev_desc_calib` 的问法与调用），差别只在：
  ① 对象是 `data/research/3*-*.json` 里的全部新条目（不是 50 条样本）；
  ② 不打 AUC（无人工标注），只按阈值出重写队列；
  ③ 结果写 `data/desc-originality-audit.json`（派生物，不入库）。

用法: python scripts/scan_desc_originality.py [--limit N] [--threshold 0.40]
      JEV_CONCURRENCY=8 python scripts/scan_desc_originality.py
"""
import glob
import io
import json
import os
import sys
from concurrent import futures as cf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_desc_calib as J  # noqa: E402  复用同一套问法，避免判据漂移

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(D, "desc-originality-audit.json")
TECHS = json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))
BY_ID = {t["id"]: t for t in TECHS}


def new_items():
    ids = []
    for f in sorted(glob.glob(os.path.join(D, "research", "3*-*.json"))):
        for r in json.load(io.open(f, encoding="utf-8")):
            if isinstance(r, dict) and r.get("id") in BY_ID and r["id"] not in ids:
                ids.append(r["id"])
    return [BY_ID[i] for i in ids]


def _uniq_of(a):
    """Choice 的答案形态在不同版本里是 P / probabilities / choices 三种键名，逐个试。"""
    if not isinstance(a, dict):
        return 0.0
    for k in ("P", "probabilities", "choices", "options"):
        v = a.get(k)
        if isinstance(v, dict):
            return float(v.get("unique") or 0.0)
    return 0.0


def score_one(t, key, leads):
    lead = (leads.get(t.get("wikiEn") or "") or "")[:1200]
    state = {"zh_summary": t["desc"], "en_lead": lead}
    qs = J.build_questions(t["desc"])
    resp, ms, err = J.call(state, qs, key)
    if not resp:
        print(f"  ! {t['id']} 判定失败：{err}")
        return None
    def p_true(a):
        # noul 类答案的概率键名是 "noul"（choice 类才用 probabilities/confidence）
        if not isinstance(a, dict):
            return None
        return a.get("noul") if a.get("noul") is not None else a.get("p_true")
    entry = p_true(resp.get("entry") or {})
    cl = [i for i in range(8) if f"c{i}" in resp]
    cmax = max([p_true(resp[f"c{i}"]) or 0.0 for i in cl], default=0.0)
    uniq = max([_uniq_of(resp[f"f{i}"]) for i in range(8) if f"f{i}" in resp], default=0.0)
    return {"id": t["id"], "name": t["name"], "category": t["category"],
            "desc": t["desc"], "entry": entry, "clause_max": cmax, "p_unique": uniq}


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    thr = float(sys.argv[sys.argv.index("--threshold") + 1]) if "--threshold" in sys.argv else 0.40
    key = J.read_key()
    items = new_items()
    if limit:
        items = items[:limit]
    leads = J.load_leads([t.get("wikiEn") or "" for t in items])
    print(f"待过闸 {len(items)} 条（净增批次），阈值 {thr}，并发 {J.CONC}")

    rows = []
    with cf.ThreadPoolExecutor(max_workers=J.CONC) as ex:
        futs = {ex.submit(score_one, t, key, leads): t["id"] for t in items}
        for n, fu in enumerate(cf.as_completed(futs), 1):
            r = fu.result()
            if r:
                rows.append(r)
            if n % 50 == 0:
                print(f"  …{n}/{len(items)}")
    rows.sort(key=lambda r: -max(r["clause_max"], r["entry"] or 0.0))
    queue = [r for r in rows if max(r["clause_max"], r["entry"] or 0.0) >= thr]
    print(f"有效判定 {len(rows)} 条，进入重写队列 {len(queue)} 条（子句级或整句级 ≥{thr}）")
    for r in queue[:25]:
        print(f"  {r['id']:<32} cmax={r['clause_max']:.2f} entry={r['entry'] if r['entry'] is None else round(r['entry'],2)} "
              f"uniq={r['p_unique']:.2f} {r['desc'][:26]}")
    json.dump({"threshold": thr, "scored": len(rows), "queue": queue, "rows": rows},
              io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"明细 → {OUT}")


if __name__ == "__main__":
    main()
