# -*- coding: utf-8 -*-
"""
决策③的收尾：`kind` 副轴在知识域里被规则误标成"工艺"。

§3 定义：`原理`=理论、定律｜`工艺`=方法、流程。实测 knowledge 域里
`math_pure` 206/611、`physics` 75/216、`chemistry` 50/75、`earth_space` 79/132、
`logic_foundations` 8/36 标着"工艺"，其中概率论、希尔伯特空间、勒贝格积分、
康托尔集合论、狭义相对论、近代原子论这类公认理论全在"工艺"桶里——
这是 `fix_edges_and_names.py` 早期按关键词补 kind 留下的误标，也正是决策③
（"科学类条目用 kind=原理"）没做完的部分。

规则（先方法词、后理论词，两个都不命中就不动）：
  ① 名字或 desc 命中"方法/仪器/流程"词 → 保持/改为 工艺
  ② 否则命中"理论/定律/结构"词 → 改为 原理
  ③ MANUAL 名单优先于两条规则（人判过的个案）
只动 knowledge 域（A 群数学与逻辑 + B 群理化地 + 生命科学），不碰器物与制度域。

用法: python scripts/fix_kind.py            # 干跑，打印每一条改动与依据
      python scripts/fix_kind.py --apply
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUTDIR = os.environ.get("ALLTECH_OUT") or D
AUDIT = OUTDIR if OUTDIR.endswith(".json") else os.path.join(OUTDIR, "kind-fix-audit.json")

KNOWLEDGE = {"math_pure", "logic_foundations", "physics", "chemistry", "earth_space", "life_medicine"}
METHOD_WORDS = re.compile(
    r"法|术|测定|测量|测绘|谱|波谱|显微|镜|蒸馏|分馏|滴定|示踪|历法|纪时|时制|工艺|合成|冶炼|铸造|焊接|加工|提取|分离|"
    r"成像|扫描|测序|培养|接种|消毒|麻醉|缝合|造血|透析|过滤|锻造|烘焙|酿造|记账|检索|编目")
THEORY_WORDS = re.compile(
    r"论|学说|定律|定理|原理|假说|猜想|概念|定义|公理|公设|悖论|均衡|空间|流形|拓扑|几何|代数|群$|环$|域$|范畴|"
    r"方程|不等式|函数|映射|积分|微分|级数|算子|测度|基数|同余|全等|相似|记号|体系|模型|范式|分类学|演化|进化|机制|理论")

# 人工裁决优先：这些条目虽含方法词但实为理论（或反之）
MANUAL = {
    "probability_theory": "原理", "hilbert_space": "原理", "lebesgue_integration": "原理",
    "poincare_topology": "原理", "eulers_identity": "原理", "weierstrass_epsilon_delta": "原理",
    "nash_equilibrium": "原理", "hamilton_quaternions": "原理", "riemann_surface": "原理",
    "divisor": "原理", "compactness_concept": "原理", "congruence_relation": "原理",
    "cantor_set_theory": "原理", "aristotelian_logic": "原理", "boolean_algebra_structure": "原理",
    "absorption_law": "原理", "zeno_paradoxes": "原理", "panini_grammar": "原理",
    "ackermann_function": "原理", "proclus_parallel_postulate": "原理",
    "atomic_theory": "原理", "catalysis_concept": "原理", "lewis_covalent_octet": "原理",
    "special_relativity": "原理", "planck_quantum_hypothesis": "原理",
    "gibbs_statistical_ensembles": "原理", "becquerel_radioactivity": "原理",
    "heliocentric_model": "原理", "cuvier_paleontology_catastrophism": "原理",
    "numerical_weather_prediction": "原理", "cartography": "工艺", "surveying": "工艺",
    "triangulation_survey": "工艺", "radiometric_dating": "工艺", "astrolabe": "器物",
    "microscope": "器物", "electron_microscope": "器物", "radar": "器物",
    "barometer": "器物", "glasses": "器物", "vacuum_pump": "器物", "isotope_tracer": "工艺",
    # 名字里的「论」来自书名而非理论：这几条是典籍载体，不是原理
    "de_materia_medica": "媒介", "de_re_metallica": "媒介", "zhang_zhongjing": "媒介",
    "huangdi_neijing": "媒介", "huygens_de_ratiociniis": "媒介", "barrow_geometrical_lectures": "媒介",
    "alberico_prints": "媒介",
}


def classify(t):
    rid = t["id"]
    if rid in MANUAL:
        return MANUAL[rid], "人工裁决名单"
    # 只用条目名判定：desc 里的"模型/机制/理论"等字常常在说下游用途，
    # 会把"浮雕地图""控制变量法"这类方法条目误升成原理（实测如此）。
    text = t.get("name") or ""
    if METHOD_WORDS.search(text):
        return None, ""
    m = THEORY_WORDS.search(text)
    if m:
        return "原理", f"理论词「{m.group(0)}」"
    return None, ""


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    flips = []
    for t in techs:
        if t.get("category") not in KNOWLEDGE or t.get("kind") != "工艺":
            continue
        new, why = classify(t)
        if new and new != t["kind"]:
            flips.append({"id": t["id"], "category": t["category"], "from": "工艺", "to": new,
                          "why": why, "name": t["name"], "importance": t["importance"]})
            t["kind"] = new
    import collections
    print(f"改动 {len(flips)} 条：", dict(collections.Counter(f["to"] for f in flips)))
    for f in flips[:40]:
        print(f"  {f['id']:<30} {f['from']}→{f['to']}  依据 {f['why']}")
    if len(flips) > 40:
        print(f"  …另 {len(flips) - 40} 条见 audit")
    audit = {"flipped": len(flips), "rows": flips,
             "kind_by_domain": {c: dict(collections.Counter(x["kind"] for x in techs if x["category"] == c))
                                for c in sorted(KNOWLEDGE)}}
    json.dump(audit, io.open(AUDIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"audit → {AUDIT}")
    if not apply_changes:
        print("（干跑，未写库）")
        return
    io.open(TECHS, "w", encoding="utf-8").write(
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    print(f"已写入 {TECHS}")


if __name__ == "__main__":
    main()
