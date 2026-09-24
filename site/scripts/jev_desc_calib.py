# -*- coding: utf-8 -*-
"""
jev_desc_calib.py — 用 50 条已人工标注的样本，对比两种判定粒度能否识别"desc 译自英文导语"。

背景：2026-09-21 分层随机抽样（种子 20260921）人工三分类为 T（整句近似翻译）/
T-lite（含明显翻译片段）/ O（独立概括），结果 5 / 9 / 36。
整句级校准的结论是 AUC 0.921 但概率上限只有 0.37，且"误伤"条目经复核其实是
子句级翻译 —— 于是本轮把粒度作为唯一变量做 A/B：

  entry  —— 一次判断整条 desc（上一轮的问法）
  c0..c3 —— 按标点切出的每个子句单独判断，条目分数取子句最大值

两种问法放进同一个请求、同一份 state，因此并行执行且互相看不见答案。
英文导语由 scripts/fetch_leads.py 预先抓入 data/jev-desc-leads.json（本脚本只读缓存）。

只读 data/techs.json，不修改任何事实源。输出 data/jev-desc-calib.json（gitignore 内）。

用法:
  python scripts/jev_desc_calib.py
  JEV_CONCURRENCY=8 python scripts/jev_desc_calib.py
"""
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from concurrent import futures as cf
import statistics
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "jev-desc-calib.json")
LEADS = os.path.join(DATA, "jev-desc-leads.json")

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
CONC = int(os.environ.get("JEV_CONCURRENCY", "4"))

# 人工标签（判定者：本次审计的单评分者，非盲评 —— 这是本实验已知的偏差来源）
GOLD = {
    "T": {"bolas", "koch_postulates", "python_language", "arithmetic_function",
          "cauchy_residue_theorem"},
    "T-lite": {"wind_tunnel", "bakelite", "prontosil", "flash", "skinner_operant_conditioning",
               "euler_product_zeta", "shulba_sutras", "irda", "tversky_kahneman_heuristics"},
}
SEED_FILE = os.path.join(DATA, "jev-desc-sample50.json")

_lock = threading.Lock()
_tok = {"in": 0, "out": 0}


def gold_of(tid):
    return "T" if tid in GOLD["T"] else ("T-lite" if tid in GOLD["T-lite"] else "O")


def read_key():
    p = os.path.join(ROOT, ".env")
    for line in open(p, encoding="utf-8"):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("TYPESAFE_API_KEY 不在 .env")


def load_leads(titles):
    """导语只读缓存，不在此处抓网络（抓取见 scripts/fetch_leads.py）。"""
    if not os.path.exists(LEADS):
        raise SystemExit("缺少 data/jev-desc-leads.json，先运行 python scripts/fetch_leads.py")
    cache = json.load(open(LEADS, encoding="utf-8"))
    return {t: cache.get(t, "") for t in titles}


CLAUSE_SPLIT = "，。；！？、"


def clauses_of(desc):
    """按中文标点切子句，丢掉过短的碎片，最多取 4 个（控制请求体积）。"""
    parts, buf = [], ""
    for ch in desc:
        if ch in CLAUSE_SPLIT:
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if len(p) >= 5][:4]


def build_questions(desc):
    """三个正交判断，同一请求内并行、互相看不见彼此答案：
       entry —— 整句级对应度（上一轮的问法，留作对照）
       cN    —— 子句级"能否由英文对应译出"
       fN    —— 子句级写法归类（Choice 四选一，读 P(unique) 作为 merger 维度）
                上一版这里用 Noul 问"是否受表达限制"，102 个子句全部落在 0.12–0.37、
                无一条 ≥0.5，维度塌成常数；改用互斥选项逼出分布。

       注意：cN 的判据里刻意不再提"标准术语"，那个维度全部交给 fN。
       上一版把它写在 cN 的 no_when 里，两个维度被缠在同一个问题上。
    """
    q = {
        "entry": {
            "type": "noul",
            "instructions": "把 state.zh_summary 视为 state.en_lead 的中文翻译或逐句转述，这一假设成立吗？"
                            "判的是行文结构：中文句子里信息出现的顺序与取舍，能否被英文导语的句子顺序逐一解释。",
            "criteria": {
                "yes_when": [
                    "中文与英文的意群顺序基本一一对应，读起来像照原文翻出来的",
                    "中文沿用了英文导语里带个人风格的比喻或固定说法（如把 batteries-included 译成「电池自备」）",
                ],
                "no_when": [
                    "中文按自己的逻辑重排，先讲作用或后果，再讲名称或定义",
                    "中文只是与英文共享了同一批技术术语，组织方式与英文无关",
                ],
            },
        }
    }
    for i, c in enumerate(clauses_of(desc)):
        q[f"c{i}"] = {
            "type": "noul",
            "instructions": f"中文片段「{c}」摘自 state.zh_summary。该片段能否由 state.en_lead 中的"
                            "某一句逐术语、逐意群对应译出？只判这一个片段，不管整条摘要的其他部分，"
                            "也不考虑这个片段是否属于标准术语。",
            "criteria": {
                "yes_when": [
                    "片段里的每个成分都能在英文某句中找到对应词或对应短语",
                    "片段的表述是英文原句的直译或近义改写，换成别的来源不会正好长成这样",
                ],
                "no_when": [
                    "片段说的是英文导语未涉及的具体年份、人名、后果或地位判断",
                    "片段与英文只有零散词面重合，句内组织方式无关",
                ],
            },
        }
        q[f"f{i}"] = {
            "type": "choice",
            "instructions": f"中文片段「{c}」的写法属于以下哪一种？只判这一个片段。",
            "criteria": {
                "unique": "几乎唯一合理写法：学科定义、标准术语名、固定命名或客观量值，"
                          "表述同一概念时换任何语言都只能基本这样写，不存在第二种自然说法",
                "multiple": "有多种合理写法，但本次的选词与意群顺序跟英文导语高度一致，"
                            "像是照着英文排出来的",
                "authorial": "带有原文特有的比喻、评价或修辞选择（例如把 batteries-included "
                             "写成「电池自备」、把 powerful tool 写成「利器」）",
                "unrelated": "与英文导语无关的自写内容：新增的年份、人名、后果或地位判断",
            },
        }
    return q




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
                _tok["in"] += u.get("input_tokens") or 0
                _tok["out"] += u.get("output_tokens") or 0
            return data.get("answers") or {}, ms, None
        except urllib.error.HTTPError as e:
            code, txt = e.code, e.read().decode()[:160]
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


def auc(pos, neg, key):
    """P(正例分数 > 负例分数)，并列算半分。"""
    win = tie = 0
    for a in pos:
        for b in neg:
            if a[key] > b[key]:
                win += 1
            elif a[key] == b[key]:
                tie += 1
    n = len(pos) * len(neg)
    return (win + tie / 2) / n if n else float("nan")


def sweep(rows, key, label):
    pos = [r for r in rows if r["gold"] != "O"]
    neg = [r for r in rows if r["gold"] == "O"]
    print(f"\n=== {label} ===")
    print(f"AUC(疑似翻译 vs 独立概括) = {auc(pos, neg, key):.3f}   "
          f"上限 {max(r[key] for r in rows):.2f}   "
          f"中位 T {_med([r[key] for r in rows if r['gold']=='T'])}  "
          f"T-lite {_med([r[key] for r in rows if r['gold']=='T-lite'])}  "
          f"O {_med([r[key] for r in rows if r['gold']=='O'])}")
    for th in (0.5, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15):
        hit = [r for r in rows if r[key] >= th]
        tp = len([r for r in hit if r["gold"] != "O"])
        if not hit:
            print(f"  >={th:<5} 队列 0")
            continue
        print(f"  >={th:<5} 队列 {len(hit):>2}/{len(rows)}  召回 {tp}/{len(pos)} "
              f"({100*tp/len(pos):.0f}%)  误伤 {len(hit)-tp}/{len(neg)} "
              f"({100*(len(hit)-tp)/len(neg):.0f}%)  精确率 {100*tp/len(hit):.0f}%")


def _med(xs):
    return f"{statistics.median(xs):.2f}" if xs else "—"


def main():
    sample = json.load(open(SEED_FILE, encoding="utf-8"))
    techs = {t["id"]: t for t in json.load(open(os.path.join(DATA, "techs.json"), encoding="utf-8"))}
    leads = load_leads(sorted({t["wikiEn"] for t in sample}))
    nolead = [t["id"] for t in sample if not leads.get(t["wikiEn"], "").strip()]
    print(f"样本 {len(sample)} 条  导语缺失 {len(nolead)} 条 {nolead}")

    key = read_key()
    jobs = []
    for t in sample:
        x = techs[t["id"]]
        desc = x.get("desc") or ""
        state = {"name_en": x.get("nameEn") or "", "year": x.get("year"),
                 "category": x.get("category"), "zh_summary": desc,
                 "en_lead": leads.get(t["wikiEn"], "")}
        jobs.append({"tag": t["id"], "wikiEn": t["wikiEn"], "state": state,
                     "clauses": clauses_of(desc), "questions": build_questions(desc)})

    nq = sum(len(j["questions"]) for j in jobs)
    print(f"调用 {MODEL}：{len(jobs)} 个请求 / {nq} 个问题（整句 1 + 每子句 c/f 两个），并发 {CONC}")
    wall0 = time.perf_counter()
    res = {}
    with cf.ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = {ex.submit(call, j["state"], j["questions"], key): j["tag"] for j in jobs}
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()
    wall = time.perf_counter() - wall0

    rows = []
    for j in jobs:
        ans, ms, err = res.get(j["tag"], ({}, 0.0, "未执行"))
        cl = []
        for i, txt in enumerate(j["clauses"]):
            c = ans.get(f"c{i}", {}).get("noul")
            fa = ans.get(f"f{i}", {}) or {}
            probs = fa.get("probabilities") or {}
            fu = probs.get("unique")
            if c is None or fu is None:
                continue
            cl.append({"clause": txt, "c": c, "f": fu, "f_pick": fa.get("choice"),
                       "probs": probs, "risk": c * (1 - fu)})
        rows.append({"id": j["tag"], "wikiEn": j["wikiEn"], "gold": gold_of(j["tag"]),
                     "entry": ans.get("entry", {}).get("noul"),
                     "c_max": max([x["c"] for x in cl], default=None),
                     "risk_max": max([x["risk"] for x in cl], default=None),
                     "clauses": cl, "ms": ms, "err": err,
                     "zh": j["state"]["zh_summary"], "en": j["state"]["en_lead"]})

    ok = [r for r in rows if not r["err"] and r["entry"] is not None and r["c_max"] is not None]
    print(f"\n成功 {len(ok)}/{len(rows)}  总耗时 {wall:.1f}s  吞吐 {len(ok)/wall:.2f} 条/s"
          f"（并发 {CONC}）  延迟 p50={statistics.median([r['ms'] for r in ok]):.0f}ms"
          f"  tokens in={_tok['in']:,} out={_tok['out']:,}")

    sweep(ok, "entry", "整句级对应度（上一轮问法）")
    sweep(ok, "c_max", "子句级对应度 c（取子句最大值）")
    sweep(ok, "risk_max", "子句级风险分 risk = c × (1 − f)")

    allcl = [x for r in ok for x in r["clauses"]]
    print(f"\n=== Choice 四选一分布（全部 {len(allcl)} 个子句）===")
    picks = Counter(x["f_pick"] for x in allcl)
    for k, v in picks.most_common():
        print(f"  {k:<10} {v:>3}  ({100*v/len(allcl):.0f}%)   "
              f"P(unique) 中位 {_med([x['f'] for x in allcl if x['f_pick']==k])}")
    print(f"  P(unique): min {min(x['f'] for x in allcl):.2f} 中位 {_med([x['f'] for x in allcl])} "
          f"max {max(x['f'] for x in allcl):.2f}  ≥0.5 的有 {sum(1 for x in allcl if x['f']>=0.5)} 条")

    print("\n=== 所有 c>=0.30 的子句：对应度 vs P(几乎唯一写法) ===")
    flat = [(r, x) for r in ok for x in r["clauses"] if x["c"] >= 0.30]
    for r, x in sorted(flat, key=lambda t: -t[1]["risk"]):
        print(f"  c={x['c']:.2f} P(unique)={x['f']:.2f} risk={x['risk']:.2f} "
              f"pick={x['f_pick']:<9} {r['gold']:<7}{r['id']}")
        print(f"        「{x['clause']}」")

    print("\n=== merger 维度能否把「强制定义」与「带修辞的翻译」分开 ===")
    forced = [(r["id"], x) for r, x in flat if r["id"] in ("arithmetic_function", "koch_postulates",
              "bolas", "shulba_sutras")]
    rhet = [(r["id"], x) for r, x in flat if r["id"] in ("python_language", "cauchy_residue_theorem")]
    for tid, x in forced:
        print(f"  强制定义侧  P(unique)={x['f']:.2f} pick={x['f_pick']:<9}{tid} 「{x['clause']}」")
    for tid, x in rhet:
        print(f"  含修辞侧    P(unique)={x['f']:.2f} pick={x['f_pick']:<9}{tid} 「{x['clause']}」")



    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"model": MODEL, "conc": CONC, "wall_s": round(wall, 1),
                   "tokens": dict(_tok), "rows": rows}, f, ensure_ascii=False, indent=1)
    print("\n明细: data/jev-desc-calib.json")
    return 1 if len(ok) < len(rows) else 0



if __name__ == "__main__":
    raise SystemExit(main())
