# -*- coding: utf-8 -*-
"""
生成 data/wikien-none-allowlist.json：确认"无独立英文维基条目"的条目豁免清单。

为什么需要它：`wikiEn` 是去重主键，规范 §3.1 允许冷门古发明留空。但"留空"本身不区分
① 忘了填 ② 经检索确认无独立条目 ③ 只有重定向、且目标标题已被别的条目占用（填了会撞主键）。
本清单把 ②③ 固化下来，validate_data.py 只对未列入清单的空 wikiEn 报警，
于是"F6 修完没有"变成可机械判定的问题，而不是一堆长期存在的告警噪音。

用法: python scripts/make_wikien_allowlist.py [--add id:id2 ...] --reason "..."
"""
import argparse
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(D, "wikien-none-allowlist.json")

VERIFIED_EMPTY = {
    "bronze_agricultural_tools": "检索无独立条目；'Bronze Age'/'Agriculture' 过宽，填了会污染去重主键",
    "piece_mold_casting": "'Piece-mold casting'/'Chinese bronze casting' 均无条目；'Casting' 过宽",
    "moldboard_plow": "'Moldboard'/'Mouldboard' 仅重定向到 'Plough'，而 'Plough' 已被 plow(犁) 占用",
    "drawloom": "'Drawloom'/'Treadle loom' 仅重定向到 'Loom'，已被 weaving_loom(织机) 占用",
    "horizontal_treadle_loom": "'Treadle loom' 重定向到 'Loom'，同上占用",
    "proto_porcelain": "'Proto-celadon' 是独立条目但已被 proto_celadon(原始青瓷) 占用；两者是否同物属 §3.7 待裁决",
    "cofusion_steel": "'Co-fusion steel' 无条目；'Pattern welding' 是另一工艺，不可借用",
    "drug_testing": "所指的是《医典》中的药效检验规则；'Drug test' 讲现代药检，语义不同",
    "water_powered_bellows": "'Water-powered bellows' 无条目；'Bellows' 已被风箱(bellows) 占用",
    "anesthetic_sponge": "'Spongia somnifera' 与 'Sleeping sponge' 均无独立条目",
    "corned_gunpowder": "'Corned gunpowder' 无条目；'Gunpowder' 已被火药占用",
    "steam_printing_press": "'Koenig steam press' 无条目；'Friedrich Koenig' 是人物条目，不是该机器",
    "gas_turbine_ship": "刻意置空（merge_research L3 裁决）：'Gas-turbine ship' 无条目，宽条 'Gas turbine' 会撞主键",
    "recombinant_insulin": "刻意置空：'Recombinant human insulin' 无条目，'Insulin'/'Humulin' 属更宽概念或商品名",
    "natural_gas_salt": "刻意置空：'Natural gas' 为宽条目且已被 natural_gas_distribution 占用",
    "ct_precursor": "刻意置空：'CT scan' 已被 ct_scanner(CT扫描仪) 占用，本条是理论前身",
    "tungsten_filament": "'Tungsten filament lamp' 无独立条目；'Incandescent light bulb' 属更宽概念",
    "li_yorke_chaos": "刻意置空（merge_research L3 裁决）：'Li–Yorke chaos' 检索无独立条目，'Chaos theory' 已被他条占用",
    "auger_tlp": "刻意置空（merge_research L3 裁决）：'Auger (platform)' 检索无条目",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", default="")
    ap.add_argument("--reason", default="人工检索确认无独立英文条目")
    a = ap.parse_args()
    doc = {"_comment": "wikiEn 留空豁免清单（规范 §3.1/§3.7）。键=id，值=为何确实无法填标题。",
           "items": dict(VERIFIED_EMPTY)}
    if a.add:
        for i in a.add.split(":"):
            if i.strip():
                doc["items"][i.strip()] = a.reason
    techs = json.load(io.open(os.path.join(D, "techs.json"), encoding="utf-8"))
    empty = {t["id"] for t in techs if not (t.get("wikiEn") or "").strip()}
    json.dump(doc, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"豁免清单 {len(doc['items'])} 条 → {OUT}")
    print("未豁免的空 wikiEn（仍需补）:", sorted(empty - set(doc["items"])))


if __name__ == "__main__":
    main()
