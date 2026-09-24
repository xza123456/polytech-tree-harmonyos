# -*- coding: utf-8 -*-
"""
§3.7 收尾：32 组"同 wikiEn 多条目"逐组裁决的机械化落地。

结论：32 组里没有一组是漏合并——它们都是同一篇维基词条下的不同贡献/不同代
（同书两成果、通称与代际变体、原理与应用）。但"一篇词条只能作为一个条目的溯源"，
因此每组只保留一条挂 wikiEn，其余置空并把原标题移入 aliases；无连线者补一条演化边。

保留哪一条的判据（按组显式写死在 KEEP，不猜）：挂名那条应是"词条主题本身"
——通常是通名/最早确立该概念的一条，而不是派生变体。

用法: python scripts/fix_dup_wikien.py            # 干跑
      python scripts/fix_dup_wikien.py --apply    # 写入，并产出裁决表
输出: data/dup-wikien-adjudication.json（校验器据此豁免被置空的条目）
"""
import io
import atomic
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_research import MIN_DESC_SIM, desc_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
ADJ = os.environ.get("ALLTECH_ADJ") or os.path.join(D, "dup-wikien-adjudication.json")

# 词条标题 → 保留链接的 id
KEEP = {
    "Almagest": "ptolemaic_astronomy",                       # 词条主体是天文学体系，弦表是其中的数学成果
    "Bellows": "bellows",                                    # 通名
    "Blast furnace": "blast_furnace",                        # 词条主体是欧洲中世纪高炉工艺
    "Canning": "canning",                                    # 发明本身
    "Cannon": "cannon",                                      # 通名
    "Coke (fuel)": "coke_fuel",                              # 词条即燃料本身
    "Cotton gin": "cotton_gin",                              # 词条主体是惠特尼锯齿轧棉机
    "Crank (mechanism)": "crank",                            # 词条即曲柄机构
    "Fuel cell vehicle": "fuel_cell_vehicle",                # 通名
    "Georges Cuvier": "cuvier_paleontology_catastrophism",   # 人物词条，取其主成就（古生物/灾变论）
    "Hindu–Arabic numeral system": "hindu_arabic_numerals",  # 词条即传开的位值制体系
    "Horologium Oscillatorium": "huygens_centrifugal_force",  # 著作词条，挂在正文成果上
    "Hovercraft": "hovercraft",                              # SR.N1 实用化一条
    "In vitro fertilisation": "ivf",                         # 通名
    "Ink": "ink",                                            # 通名
    "Isoperimetric inequality": "isoperimetric_inequality_modern",  # 词条即不等式及其严格证明
    "Jacob's staff": "jacobs_staff",                         # 器械起源一条
    "Law of large numbers": "bernoulli_law_large_numbers",   # 定理首证一条
    "Lock (water navigation)": "canal_lock",                 # 通名
    "Maglev": "maglev_train",                                # 通名
    "Markov chain": "markov_chains",                         # 模型创立一条
    "Match": "match",                                        # 通名
    "Paddle wheel": "paddle_wheel_boat",                     # 概念起源一条
    "Piston pump": "force_pump",                             # 概念起源一条
    "Positron emission tomography": "positron_imaging",      # 首例成像
    "Rudder": "steering_oar",                                # 舵的起源形态
    "Screw-cutting lathe": "screw_cutting_lathe",            # 概念起源一条
    "Simplex algorithm": "simplex_method",                   # 通名
    "Sugar": "sugar",                                        # 词条即糖本身
    "Telephone exchange": "telephone_exchange",              # 通名
    "Wind turbine": "wind_turbine_electric",                 # 首台风力发电机
    "Windmill": "windmill",                                  # 词条主体是磨坊风车
}


def pick_auto(g):
    """未写进 KEEP 的新同题组：只有"确为两件事"才敢自动裁决挂名方。
    同年代且 desc 高度相似 → 疑似漏合并，交人工（保持 error）。"""
    if len(g) > 2:
        return None
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            if g[i]["year"] == g[j]["year"] and desc_sim(g[i].get("desc"), g[j].get("desc")) >= MIN_DESC_SIM:
                return None
    return sorted(g, key=lambda x: (x["importance"], x["year"]))[0]["id"]


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    by_id = {t["id"]: t for t in techs}

    groups = defaultdict(list)
    for t in techs:
        if t.get("wikiEn"):
            groups[t["wikiEn"]].append(t)
    dup = {w: g for w, g in groups.items() if len(g) > 1}

    # KEEP 是人工裁决表；新出现的同题组先按 pick_auto 自动判定，判不动的留给校验器报错
    keep_of = dict(KEEP)
    undecided = []
    for w, g in dup.items():
        if w in keep_of:
            continue
        auto = pick_auto(g)
        if auto:
            keep_of[w] = auto
            print(f"  自动挂名 {w} → {auto}（年代/描述确为两件事）")
        else:
            undecided.append(w)
    if undecided:
        print("!! 需人工裁决的同题组（疑似漏合并，校验器会报 error）:")
        for w in sorted(undecided):
            print("   ", w, [x["id"] for x in dup[w]])

    records = []
    if os.path.exists(ADJ):   # 幂等：上一轮已置空的条目仍在豁免表里
        prev = json.load(io.open(ADJ, encoding="utf-8"))
        records = [r for r in prev if r["id"] in by_id and not (by_id[r["id"]].get("wikiEn") or "")]
    changed = 0
    for w, g in sorted(dup.items()):
        keep_id = keep_of.get(w)
        if not keep_id:
            continue
        keep = by_id.get(keep_id)
        if keep is None or (keep.get("wikiEn") or "") != w:
            print(f"!! {w}: 保留目标 {keep_id} 不在库或已不挂此题，跳过")
            continue
        for x in g:
            if x["id"] == keep_id:
                continue
            ids = {y["id"] for y in g if y["id"] != x["id"]}
            linked = ids & (set(x.get("prereqs") or []) | set(x.get("related") or []))
            if not linked:
                other = keep
                a, b = (x, other) if (x.get("year") or 0) <= (other.get("year") or 0) else (other, x)
                if len(b.get("prereqs") or []) < 4:
                    b["prereqs"] = sorted(set(b["prereqs"] or []) | {a["id"]})
                else:
                    b["related"] = sorted(set(b["related"] or []) | {a["id"]})
            x.setdefault("aliases", [])
            if w not in x["aliases"]:
                x["aliases"] = sorted(set(x["aliases"]) | {w})
            x["wikiEn"] = ""
            changed += 1
            tag = "同题拆分" if w in KEEP else "同题拆分（自动）"
            records.append({"id": x["id"], "title": w, "kept_by": keep_id,
                            "reason": f"{tag}，链接归 {keep_id}"})
            print(f"  置空 {x['id']:<32} ← {w}（保留 {keep_id}）")

    print(f"\n同题组 {len(dup)}，已裁决 {len(dup) - len(undecided)}（其中自动 "
          f"{sum(1 for w in dup if w not in KEEP and w in keep_of)}），置空 {changed} 条")
    if not apply_changes:
        print("（干跑。--apply 写入。）")
        return
    raw_t = io.open(TECHS, encoding="utf-8").read()
    atomic.write_atomic(TECHS + ".bak-dupwikien", raw_t)
    out = json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw_t.endswith("\n") else "")
    atomic.write_atomic(TECHS, out)
    json.dump(records, io.open(ADJ, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已写入 {TECHS}（备份 .bak-dupwikien），裁决表 {ADJ}")


if __name__ == "__main__":
    main()
