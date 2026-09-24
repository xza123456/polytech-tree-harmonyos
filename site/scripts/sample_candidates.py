# -*- coding: utf-8 -*-
"""
sample_candidates.py — 穷尽式收集流水线第 3 步：把庞大缺失候选按子分类配额
抽样成一个分包大小（默认约 120 条）的"待填空清单"。

确定性、可复现：
  - 每分支读取 _candidates/<branch>.missing.json（先跑 diff_candidates.py）；
  - 子分类配额来自本文件 QUOTA（可按实测分布调整）；
  - 类内排序：有中文名优先，其次标题短/基础（启发式），再按标题字母序，
    保证同输入同输出；
  - 跨分支去重（同一 wiki 标题只进一次）；
输出 _candidates/sample-<pack>.json，供子代理只做"填空"。

注意：这是"抽样送填"，不是丢弃。未抽中的候选仍保留在 .missing.json 中，
后续可提高配额做第二批。
"""
import json
import os
import glob
import re
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND_DIR = os.path.join(ROOT, "data", "research", "_candidates")

# 包 24：数论 + 代数。配额为"该子分类抽样上限"，按实测分布设；
# 未列出的子分类使用 DEFAULT_QUOTA。目标合计 115-130。
# 注：跨分支同名子分类（Polynomials / Linear algebra 等）共享一个配额键，
# 脚本按 title 全局去重，先到先得。
QUOTA_24 = {
    # ---- 数论（number_theory）合计 ~55 ----
    "Algebraic number theory": 7,
    "Analytic number theory": 6,
    "Theorems in number theory": 6,
    "Prime numbers": 5,
    "Modular forms": 4,
    "Modular arithmetic": 3,
    "Diophantine equations": 3,
    "Quadratic forms": 2,
    "Continued fractions": 2,
    "Arithmetic functions": 2,
    "Multiplicative functions": 2,
    "Langlands program": 2,
    "P-adic numbers": 2,
    "Geometry of numbers": 2,
    "Integer partitions": 2,
    "Arithmetic dynamics": 1,
    "Diophantine approximation": 2,
    "Computational number theory": 1,
    "Elementary number theory": 2,
    "Arithmetic geometry": 1,
    "Lattice points": 1,
    "Squares in number theory": 0,
    "Abc conjecture": 1,
    "Unsolved problems in number theory": 1,
    "Arithmetic": 1,
    "Integer sequences": 1,
    # ---- 代数（algebra / abstract / linear）合计 ~65 ----
    "(root)": 8,
    "Polynomials": 5,
    "Abstract algebra": 5,
    "Algebraic structures": 5,
    "Elementary algebra": 3,
    "Symmetric functions": 2,
    "Mathematical identities": 2,
    "Theorems in algebra": 2,
    "Theorems in abstract algebra": 2,
    "Computer algebra": 1,
    "Algebraic graph theory": 1,
    "Series expansions": 0,
    "Variables (mathematics)": 1,
    "Morphisms": 2,
    "Binary operations": 2,
    "Algebraic properties of elements": 2,
    "Ternary operations": 0,
    "Fields of abstract algebra": 1,
    "Vectors (mathematics and physics)": 1,
    "Matrices (mathematics)": 5,
    "Matrix theory": 4,
    "Determinants": 3,
    "Vector spaces": 3,
    "Linear operators": 3,
    "Spectral theory": 3,
    "Module theory": 3,
    "Multilinear algebra": 2,
    "Singular value decomposition": 2,
    "Numerical linear algebra": 2,
    "Topological vector spaces": 1,
    "Theorems in linear algebra": 2,
    "Invariant subspaces": 1,
    "Convex geometry": 1,
    "Geometric intersection": 0,
    "Super linear algebra": 0,
    "Process calculi": 0,
    "Scalars": 0,
}
DEFAULT_QUOTA = 1

# 标题层面再过滤一次漏网的非概念
DROP_TITLE_SUBSTR = (
    "conference", "symposium", "workshop", "congress", "prize", "award",
    "institute", "society", "association", "journal", "textbook",
)

# 纯数字 / 纯算式 / "整数(number)"条目 / 项目网站 / 单个符号 —— 维基分类里的噪声
RE_PURE_DIGITS = re.compile(r"^[\d,\s]+$")
RE_PURE_EXPR = re.compile(r"^[\d\s\+\-\u22ef\u2212\u00b7\.\,\u2218]+$")
RE_INTEGER_PAGE = re.compile(r"^\d[\d,]*\s*\((?:number|integer)\)$", re.IGNORECASE)


def is_noise_title(title: str) -> bool:
    tl = title.lower()
    if "@" in tl or tl.endswith(".org"):
        return True
    if (RE_PURE_DIGITS.match(title) or RE_PURE_EXPR.match(title)
            or RE_INTEGER_PAGE.match(title)):
        return True
    if len(title) <= 2 and not re.search(r"[A-Za-z]", title):
        return True
    return False


def sort_key(rec):
    # 有中文跨语言链接的通常是更主流的概念，优先；其余按标题字母序保证确定性。
    return (0 if rec.get("name") else 1, rec["nameEn"].lower())


def load_missing(branch):
    p = os.path.join(CAND_DIR, branch + ".missing.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def sample_pack(branches, quota, default_quota, target):
    seen_titles = set()
    picked = []
    # 先按分支、子分类分桶
    buckets = {}
    for b in branches:
        for rec in load_missing(b):
            t = rec["nameEn"]
            tl = t.lower()
            if (t in seen_titles or any(k in tl for k in DROP_TITLE_SUBSTR)
                    or is_noise_title(t)):
                continue
            seen_titles.add(t)
            sub = rec.get("subcat", "") or "(root)"
            bucket_key = ("*", "(root)") if sub == "(root)" else (b, sub)
            buckets.setdefault(bucket_key, []).append(rec)

    # 每个桶按确定性规则排序，按配额截取
    for (b, sub), recs in sorted(buckets.items()):
        q = quota.get(sub, default_quota)
        recs.sort(key=sort_key)
        for r in recs[:q]:
            picked.append(r)

    picked.sort(key=lambda r: (r["nameEn"].lower()))
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="24")
    ap.add_argument("--branches", default="number_theory,algebra,abstract_algebra,linear_algebra")
    ap.add_argument("--target", type=int, default=125)
    args = ap.parse_args()

    if args.pack == "24":
        quota, default_quota = QUOTA_24, DEFAULT_QUOTA
    else:
        quota, default_quota = {}, DEFAULT_QUOTA

    branches = [x.strip() for x in args.branches.split(",") if x.strip()]
    picked = sample_pack(branches, quota, default_quota, args.target)

    out = os.path.join(CAND_DIR, "sample-" + args.pack + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(picked, f, ensure_ascii=False, indent=2)

    nzh = sum(1 for r in picked if r.get("name"))
    print("包{} 抽样={} 有中文名={} -> {}".format(args.pack, len(picked), nzh, out))
    from collections import Counter
    for k, v in Counter(r.get("subcat", "(root)") for r in picked).most_common():
        print("  {:>3}  {}".format(v, k or "(root)"))


if __name__ == "__main__":
    main()
