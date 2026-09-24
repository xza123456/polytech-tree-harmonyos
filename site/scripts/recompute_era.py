# -*- coding: utf-8 -*-
"""
F2+F3：era 一律由 year 查表生成，区间语义改为半开 [yearStart, yearEnd)（末段闭到 2030）。

用法:
  python scripts/recompute_era.py            # 干跑，只打印将发生的变化
  python scripts/recompute_era.py --apply    # 写 data/techs.json 并输出审计文件
"""
import io
import atomic
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(DATA, "techs.json")
OUTDIR = os.environ.get("ALLTECH_OUT") or DATA
ERAS = os.path.join(DATA, "eras.json")
REPORT = os.path.join(OUTDIR, "era-recompute-report.json")


def load(path):
    txt = io.open(path, encoding="utf-8").read()
    return json.loads(txt), txt


def dump_like(original, obj):
    """按原文件的排版回写（indent=2, 非 ASCII 不转义），并保留结尾换行习惯。"""
    out = json.dumps(obj, ensure_ascii=False, indent=2)
    if original.endswith("\n"):
        out += "\n"
    return out


def build_deriver(eras):
    ordered = sorted(eras, key=lambda e: e["order"])

    def derive(year):
        for i, e in enumerate(ordered):
            last = i == len(ordered) - 1
            if e["yearStart"] <= year < e["yearEnd"] or (last and year == e["yearEnd"]):
                return e["id"]
        raise ValueError(f"year {year} 落在所有 era 区间之外")
    return derive, ordered


def main():
    apply_changes = "--apply" in sys.argv
    techs_txt, raw_techs = load(TECHS)
    eras_txt, raw_eras = load(ERAS)
    techs = techs_txt
    assert dump_like(raw_techs, techs) == raw_techs, "techs.json 排版与 indent=2 不一致，拒绝回写"
    assert dump_like(raw_eras, eras_txt) == raw_eras, "eras.json 排版不一致"

    derive, ordered = build_deriver(eras_txt)
    changes = []
    for t in techs:
        want = derive(t["year"])
        if want != t["era"]:
            changes.append({"id": t["id"], "year": t["year"], "from": t["era"], "to": want,
                            "name": t["name"] or t["nameEn"]})
    print(f"半开区间 [start,end)（末段含 {ordered[-1]['yearEnd']}）下：{len(changes)}/{len(techs)} 条 era 需改动")
    moves = {}
    for c in changes:
        moves[(c["from"], c["to"])] = moves.get((c["from"], c["to"]), 0) + 1
    print("\n迁移路径（from → to : 条数）")
    for (f, to), n in sorted(moves.items(), key=lambda kv: -kv[1]):
        print(f"  {f:<20}→ {to:<20} {n}")
    print("\n逐条清单（前 30 条）")
    for c in changes[:30]:
        print(f"  {c['id']:<32}{c['year']:>8}  {c['from']} → {c['to']}   {c['name']}")
    if len(changes) > 30:
        print(f"  …其余 {len(changes)-30} 条见审计文件")

    # 原来归属不确定的那批：year 恰好等于某个时代的 yearEnd（旧闭区间下同时命中两个时代）
    shared_ends = {e["yearEnd"] for e in ordered[:-1]} & {e["yearStart"] for e in ordered[1:]}
    on_boundary = [t for t in techs if t["year"] in shared_ends]
    print(f"\n落在共享端点上的条目: {len(on_boundary)} 条（旧闭区间下归属不确定，半开下确定归后一时代）")
    json.dump({"semantics": "half-open [yearStart, yearEnd), last era inclusive of "
                            f"{ordered[-1]['yearEnd']}",
               "total": len(techs), "changed": len(changes), "moves": {f"{k[0]}->{k[1]}": v for k, v in moves.items()},
               "items": changes},
              open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"审计文件: data/era-recompute-report.json")

    if not apply_changes:
        print("\n（干跑，未写数据。加 --apply 才写。）")
        return
    for t in techs:
        t["era"] = derive(t["year"])
    atomic.write_atomic(TECHS, dump_like(raw_techs, techs))
    print(f"\n已写回 {TECHS}（{len(changes)} 条 era 更新）")


if __name__ == "__main__":
    main()
