# -*- coding: utf-8 -*-
"""
F11 合并闸门判据校准：以 35 次"按 wikiEn 的跨 id 自动合并"为标定集，
人工判定每一对（label 显式写死在本文件，便于逐条推翻），再扫描候选规则的拦截效果。

判定口径（独立于特征，按 §3.7 代际三要件读原始记录得出）：
  DUP   = 确为同一技术的不同叫法，合并正确
  SPLIT = 存在代际/地域/应用差异，本应各收一条并用 prereqs 相连，合并错误

用法: python scripts/gate_calibration.py
"""
import io
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")

# key = f"{kept_id} ← {swallowed_id}"
LABELS = {
    "delivery_drone ← drone_delivery": ("DUP", "同为 2016 无人机配送，只是 category 一个记 information 一个记 transport（贴标分歧，非两件事）"),
    "marine_clock_early ← huyghens_horologium": ("SPLIT", "同一年同一部《摆钟论》的两条不同贡献：摆线等时性/渐屈线（数学）与摆钟试航测经度（航海）。年份与描述都相同，闸门拦不住，须靠'著作型 wikiEn'排除项"),
    "safety_elevator ← otis_elevator": ("DUP", "同年 1852、同名'安全电梯'、同一发明人同一装置，纯重复收录"),
    "hemodialysis ← kidney_dialysis": ("DUP", "科尔夫=考尔夫=Kolff，转鼓人工肾同一事件；年份 1943/1945 需二选一"),
    "ink ← printing_ink": ("SPLIT", "书写墨(-3200) 与古腾堡油性印刷油墨(1440) 是两种配方两种用途"),
    "steering_oar ← sternpost_rudder": ("SPLIT", "操舵桨与船尾栓铰舵是舵的两代"),
    "steering_oar ← stern_rudder": ("SPLIT", "同上，且被两次合并吞掉两条"),
    "isoperimetric_zenodorus ← isoperimetric_inequality_modern": ("SPLIT", "古典等周问题与 1884 年严格证明是不同成果"),
    "bellows ← waterpowered_bellows": ("SPLIT", "皮囊风箱与水排（水力鼓风）动力源不同，且 category 不同"),
    "force_pump ← piston_pump": ("SPLIT", "希腊双动泵与加扎利双缸单向阀泵相隔 1460 年"),
    "blast_furnace ← blast_furnace_china": ("SPLIT", "中国战国生铁高炉与欧洲中世纪高炉，地域与技术脉络不同"),
    "canal_lock ← pound_lock": ("SPLIT", "托勒密单闸与 984 年乔维岳双闸复闸，是闸室的两代"),
    "match ← friction_match": ("SPLIT", "发烛（硫磺引火）与沃克摩擦火柴是不同代"),
    "windmill ← windmill_proto": ("SPLIT", "希罗风动玩具与 12 世纪磨坊风车，一个非实用装置"),
    "faience ← egyptian_faience": ("SPLIT", "釉砂(-4500) 与费昂斯(-3500) 同物异名倾向大，但年份差 1000 年必须人工定名"),
    "crank_handle ← crank": ("SPLIT", "同名不同代：汉代手摇曲柄 vs 9 世纪曲柄机构普及"),
    "paddle_wheel_boat ← paddle_wheel_ship": ("SPLIT", "《论军事》设想与南宋实际车船"),
    "coke_fuel ← coke_smelting": ("SPLIT", "宋代焦炭燃料与达比焦炭炼铁工艺，category 也不同"),
    "sugar_crystallization ← sugar": ("SPLIT", "笈多结晶法与伊斯兰炼糖推广是两件事"),
    "roller_cotton_gin ← cotton_gin": ("SPLIT", "蜗杆轧花机与惠特尼锯齿轧棉机是两代机构"),
    "hindu_numerals ← hindu_arabic_numerals": ("SPLIT", "印度形成与经花剌子米传播，是两个阶段"),
    "cannon ← cast_iron_cannon": ("SPLIT", "早期火炮与 1543 整体铸铁炮是两代"),
    "screw_cutting_lathe ← metal_lathe": ("SPLIT", "贝松木质车床与莫兹利全金属车床，机床史公认两代"),
    "bernoulli_law_large_numbers ← khinchin_law_large_numbers": ("SPLIT", "伯努利弱律与辛钦 iid 证明是两个定理"),
    "jacobs_staff ← cross_staff": ("SPLIT", "同一类仪器的两种条目，desc 几乎同文——须人工定名是否同物"),
    "canning ← canning_industrialization": ("SPLIT", "发明（阿佩尔/杜兰德）与 1903 卷封产线工业化"),
    "telephone_exchange ← digital_telephone_switch": ("SPLIT", "人工交换与 1970 E10 数字程控是两代"),
    "wind_turbine_electric ← modern_wind_turbine": ("SPLIT", "1888 布拉什首台与 1979 三叶片现代风机"),
    "early_hovercraft ← hovercraft": ("SPLIT", "1915 试验艇与 SR.N1 实用气垫船"),
    "maglev_train ← high_speed_maglev": ("SPLIT", "1984 商用低速线与 2021 时速 600 km 样车"),
    "positron_imaging ← pet_scanner": ("SPLIT", "1953 首例成像与 1973 商用 PET 机"),
    "necar_fuel_cell_vehicle ← fuel_cell_vehicle": ("SPLIT", "1994 NECAR 原型与 2014 Mirai 量产"),
    "ivf_mammal ← ivf": ("SPLIT", "1959 兔体外受精与 1978 试管婴儿"),
    "markov_chains ← markov_onegin_application": ("SPLIT", "模型创立与首次实证应用（奥涅金试验）"),
    "simplex_method ← lemke_dual_simplex": ("SPLIT", "单纯形法与对偶单纯形是两个算法，category 不同"),
    "conservation_of_energy ← first_law_thermodynamics": ("DUP", "同一条守恒律的两种表述，Δyear=3"),
    "de_humani_fabrica ← vesalius_fabrica": ("DUP", "同一部《人体的构造》，同年同名异写"),
    "game_theory ← game_theory_founding": ("DUP", "同一部《博弈论与经济行为》的两种写法"),
    "boolean_algebra ← boolean_algebra_structure": ("SPLIT", "逻辑代数(1854) 与作为抽象代数结构的布尔代数，源记录故意分两条"),
    "cayley_matrix_algebra ← cayley_hamilton_theorem": ("SPLIT", "矩阵代数的创立与凯莱-哈密顿定理是两项不同成果"),
    "wallace_natural_selection ← simson_line": ("SPLIT", "自然选择学说与西姆松线毫不相干，仅因发明人同名'华莱士'被 alias 撞并"),
    "calculus_of_variations ← euler_fluid_equations": ("SPLIT", "变分法与欧拉流体方程是不同领域成果，只因同由欧拉提出"),
    "calculus_of_variations ← euler_cauchy_equation": ("SPLIT", "变分法与柯西-欧拉方程同上，人名 alias 撞车"),
    "abel_integral_equation ← abel_summation": ("SPLIT", "阿贝尔积分方程与阿贝尔求和公式是两项不同成果"),
    "game_theory ← von_neumann_minimax_theorem": ("SPLIT", "1928 极小极大定理与 1944 奠基专著相隔 16 年，两代"),
    "markov_chains ← kolmogorov_markov_process": ("SPLIT", "马尔可夫链(1906) 与科尔莫戈罗夫连续时间一般理论(1931) 是两代"),
    "runge_theorem ← pade_approximant": ("SPLIT", "龙格逼近定理与帕德逼近是不同的逼近理论对象"),

}


def load():
    return json.load(io.open(os.path.join(D, "gate-features.json"), encoding="utf-8"))


def rules():
    """候选判据：命中 = 允许自动合并；未命中 = 拦下转人工。"""
    return {
        "R0 现状（wikiEn 命中即并）": lambda f: True,
        "R1 Δyear ≤ 3": lambda f: f["d_year"] <= 3,
        "R2 Δyear ≤ 3 且 era 相同": lambda f: f["d_year"] <= 3 and not f["era_diff"],
        "R3 Δyear ≤ 3 且 中文名相同": lambda f: f["d_year"] <= 3 and f["name_same"],
        "R4 Δyear ≤ 3 且 (同名 或 descJ ≥ 0.13)": lambda f: f["d_year"] <= 3 and (f["name_same"] or f["desc_jaccard"] >= 0.13),
        "R5 Δyear ≤ 15 且 (同名 或 descJ ≥ 0.13) 且 category 相同":
            lambda f: f["d_year"] <= 15 and (f["name_same"] or f["desc_jaccard"] >= 0.13) and not f["cat_diff"],
        "R6 取消 wikiEn 自动合并（全部转人工）": lambda f: False,
    }


def main():
    pairs = load()
    labeled, missing = [], []
    for p in pairs:
        key = f"{p['kept_id']} ← {p['swallowed_id']}"
        lab = LABELS.get(key)
        if lab and lab[0] != "占位":
            labeled.append({**p, "label": lab[0], "label_reason": lab[1]})
        else:
            missing.append(key)
    n_split = sum(1 for p in labeled if p["label"] == "SPLIT")
    n_dup = sum(1 for p in labeled if p["label"] == "DUP")
    print(f"标定集 {len(labeled)} 对：应拆 {n_split} / 确为重复 {n_dup}")
    if missing:
        print(f"未判定 {len(missing)} 对: {missing}")
    print(f"→ 现状自动合并的错误率 = {n_split}/{len(labeled)} = {n_split/len(labeled)*100:.0f}%\n")

    print(f"{'判据':<46}{'放行合并':>9}{'其中误并':>8}{'拦下转人工':>10}{'漏拆率':>8}{'人工量':>7}")
    for name, fn in rules().items():
        allow = [p for p in labeled if fn(p["features"])]
        bad = [p for p in allow if p["label"] == "SPLIT"]
        blocked = len(labeled) - len(allow)
        missed_split = len(bad) / n_split if n_split else 0
        print(f"{name:<46}{len(allow):>9}{len(bad):>8}{blocked:>10}{missed_split*100:>7.0f}%{blocked:>7}")

    print("\n各对在候选判据下的归属（P=放行合并 / R=拦下转人工）")
    for p in sorted(labeled, key=lambda x: -x["features"]["d_year"]):
        f = p["features"]
        row = "  ".join(("P" if fn(f) else "R") for fn in rules().values())
        print(f"  {p['label']:<6} Δy={f['d_year']:>5} Δera={f['d_era']} cat异={int(f['cat_diff'])} "
              f"同名={int(f['name_same'])} descJ={f['desc_jaccard']:>5} | {p['kept_id']} ← {p['swallowed_id']}")
    json.dump([{k: v for k, v in p.items() if k != "features"} | {"features": p["features"]} for p in labeled],
              io.open(os.path.join(D, "gate-calibration.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写 data/gate-calibration.json")


if __name__ == "__main__":
    main()
