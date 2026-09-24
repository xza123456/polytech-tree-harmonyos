# -*- coding: utf-8 -*-
"""
§4.3 落地：用可计算信号复核 importance 标注（只升不降，降档交人工）。

为什么要这一步：布局与形状都按 importance 决定（面数 20/12/8/6/4、半径），
但初版 2759 条种子数据里的标注系统性偏低——扇入最高的 76 条"结构枢纽"里有
`probability_theory`、`maxwell_equations`、`germ_theory`、`periodic_table`、
`algorithm` 这类公认基石，却都标着 3（渲染成"改良与细分"的 6 面盒）。
指令②要求"最重要的一批必须先齐"，标注偏低与收录缺失同样会让它们在最矮的层级里看不见。

判据（全部可重放、可解释）：
  pf = 作为他人 prereqs 终点的次数（被依赖）；f = 被引用总数（prereqs+related）
  规则升 2：imp≥3 且 (f ≥ 12 或 pf ≥ 8)
  规则不自动升 1——升 1 只认下面显式写死的名单（历史判断，逐条给理由）
  降档不自动做：只写进 audit 的 demote_candidates（imp=1 却零引用），供人工裁决

用法: python scripts/recalibrate_importance.py            # 干跑
      python scripts/recalibrate_importance.py --apply
产物: data/importance-recalibration-audit.json
"""
import io
import atomic
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.path.join(D, "techs.json") if "ALLTECH_TECHS" not in os.environ else os.environ["ALLTECH_TECHS"]
AUDIT = os.path.join(D, "importance-recalibration-audit.json") if "ALLTECH_OUT" not in os.environ \
    else os.path.join(os.environ["ALLTECH_OUT"], "importance-recalibration-audit.json")

# 升为 1（领域基石）的显式名单：扇入信号只负责提名，是否算"基石"是历史判断
MANUAL_P1 = {
    "probability_theory": "随机现象的数学基础，被统计、量子、信息、金融共有 38 条引用",
    "atomic_theory": "近代化学的总前提",
    "maxwell_equations": "电磁学统一方程，光电与无线通信的理论前提",
    "germ_theory": "医学与公共卫生的范式转折",
    "evolution_natural_selection": "生物学的统一解释框架",
    "periodic_table": "元素性质规律的总纲",
    "algorithm": "计算概念的起点，整棵计算机分支的前置",
    "boolean_algebra": "逻辑代数即数字电路的代数",
    "water_wheel": "蒸汽之前的主要原动机，驱动前工业时代的机械作业",
    "printed_circuit_board": "所有现代电子系统的装配基座",
    # 第六轮补：按"该域基石层近乎空缺"的信号逐域复核后的判断（扇入只提名）
    "glassmaking": "玻璃是横跨光学、通信、容器与建筑的通用材料",
    "portland_cement": "现代混凝土的胶凝核心，人类用量最大的人工材料",
    "silicon_transistor": "半导体时代的起点，一切现代计算器件的原型",
    "arch": "拱券让砖石以受压方式跨越空间，是砌体结构的承重原理",
    "reinforced_concrete": "钢筋与混凝土协同受力，现代建筑与桥梁的骨架",
    "masonry": "砌体承重体系，金字塔到近代砖楼的共同前提",
    "cannon": "火炮终结了城堡与线列时代，重塑军事与攻城形态",
    "nuclear_weapon": "把战争与能源的物理上限推到足以终结文明的程度",
    "haber_process": "合成氨固定大气氮，养活了全球近一半人口",
}
PROMOTE2_FLOOR_F = 12
PROMOTE2_FLOOR_PF = 8

# N-09 提名 + 逐条判后确认的"领域支柱被埋"名单（原判 3/4，实为该域唯一代表或被大量依赖）
MANUAL_P2 = {
    "gas_turbine": "喷气/联合循环/船用动力的共同源头",
    "otto_engine": "四冲程循环的唯一代表",
    "cracking_refining": "炼油从分馏走向转化的转折",
    "gasoline": "内燃时代的燃料枢纽",
    "natural_gas_distribution": "燃气终端配送的唯一代表",
    "force_pump": "域内扇入最高的泵类原型",
    "electric_locomotive": "铁路电气化的唯一代表",
    "turbofan": "高涵道比涡扇的唯一代表",
    "inertial_navigation": "自主导航主干",
    "autopilot": "自动控制链的起点",
    "all_metal_aircraft": "应力蒙皮带来的结构转折",
    "wind_tunnel": "空气动力学试验装置的唯一代表",
    "marine_chronometer": "经度问题的唯一代表",
    "screw_propeller": "水上推进方式的转折",
    "canal_lock": "梯级过船闸室的原型",
    "motor_truck": "公路货运主力",
    "tokamak": "磁约束的主流技术路线",
    "rotary_drilling": "现代钻井的起点",
    "pumped_storage_hydro": "锂电之前唯一的电网级储能",
    "maritime_dock": "港口系统枢纽",
}


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    before = Counter(x["importance"] for x in techs)   # 必须在改动前取，否则"前后"是同一个分布
    pf, f = Counter(), Counter()
    for x in techs:
        for o in set(x.get("prereqs") or []):
            pf[o] += 1
        for o in set(x.get("prereqs") or []) | set(x.get("related") or []):
            f[o] += 1
    promoted, p1_done, demote = [], [], []
    for x in techs:
        rid = x["id"]
        if rid in MANUAL_P1 and x["importance"] > 1:
            demote_from = x["importance"]
            x["importance"] = 1
            p1_done.append({"id": rid, "from": demote_from, "to": 1, "reason": MANUAL_P1[rid],
                            "f": f[rid], "pf": pf[rid]})
            continue
        if rid in MANUAL_P2 and x["importance"] > 2:
            promoted.append({"id": rid, "category": x["category"], "f": f[rid], "pf": pf[rid],
                             "from": x["importance"], "rule": "N-09 提名经复核：" + MANUAL_P2[rid]})
            x["importance"] = 2
            continue
        if x["importance"] >= 3 and (f[rid] >= PROMOTE2_FLOOR_F or pf[rid] >= PROMOTE2_FLOOR_PF):
            x["importance"] = 2
            promoted.append({"id": rid, "category": x["category"], "f": f[rid], "pf": pf[rid],
                             "rule": f"扇入 f≥{PROMOTE2_FLOOR_F} 或 pf≥{PROMOTE2_FLOOR_PF}"})
        elif x["importance"] == 1 and f[rid] == 0 and pf[rid] == 0:
            # 只看 1 档：标成"基石"却没有任何条目依赖它，是要人工确认的标注
            demote.append({"id": rid, "category": x["category"], "importance": x["importance"],
                           "year": x["year"], "name": x["name"]})

    print(f"升 2（机械规则）：{len(promoted)} 条；升 1（显式名单命中）：{len(p1_done)} 条；"
          f"降档候选（仅报告，不动）：{len(demote)} 条")
    for r in p1_done:
        print(f"  →1 {r['id']:<28} 原 {r['from']} 引用{r['f']:>3}")
    for r in promoted[:12]:
        print(f"  →2 {r['id']:<28} {r['category']:<16} 引用{r['f']:>3} 被依赖{r['pf']:>3}")
    if len(promoted) > 12:
        print(f"  …另 {len(promoted) - 12} 条见 audit")
    if apply_changes:
        atomic.write_atomic(TECHS, 
            json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
        print(f"已写入 {TECHS}")
    json.dump({"promote2": promoted, "promote1": p1_done, "demote_candidates": demote,
               "distribution_after": dict(Counter(x["importance"] for x in techs))},
              io.open(AUDIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"audit → {AUDIT}；importance 分布 {dict(sorted(before.items()))} → "
          f"{dict(sorted(Counter(x['importance'] for x in techs).items()))}")


if __name__ == "__main__":
    main()
