# -*- coding: utf-8 -*-
"""
执行 2026-09-21 的边界归属决议（用户选择"按建议分别处理"）：

  走 (c) 改年份：plow / pottery_wheel / beer  -3500 → -4000
      依据：犁与轮制陶器的考古证据可推到约前 4000 年，改后自然落回农业革命，
      不需要动时代边界。year_basis 字段等 F4 统一补（届时应为 circa/scholarly_disputed）。
  走 (a) 改注册表：bessemer_steel / internal_combustion_engine / dynamite
      era: second_industrial → industrial。年份（1856/1860/1867）是硬事实，
      1870 起点是通说，故认定 core-ids.json 落后，不重划分期。

用法: python scripts/apply_boundary_decisions.py            # 干跑
      python scripts/apply_boundary_decisions.py --apply    # 写入
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")

YEAR_FIXES = {  # id -> (去年份, 新年份, 理由)
    "plow": (-3500, -4000, "犁的考古证据约前 4000 年（原记 -3500 恰落在农业革命/青铜边界上）"),
    "pottery_wheel": (-3500, -4000, "轮制陶器出现于约前 4000 年的美索不达米亚"),
    "beer": (-3500, -4000, "酿造证据早于前 3500（贾湖残留更早，此处取保守的前 4000）"),
}
REGISTRY_FIXES = {  # id -> (旧 era, 新 era)
    "bessemer_steel": ("second_industrial", "industrial"),
    "internal_combustion_engine": ("second_industrial", "industrial"),
    "dynamite": ("second_industrial", "industrial"),
}


def dump_like(original, obj):
    out = json.dumps(obj, ensure_ascii=False, indent=2)
    return out + "\n" if original.endswith("\n") else out


def main():
    apply_changes = "--apply" in sys.argv
    techs_raw = io.open(os.path.join(D, "techs.json"), encoding="utf-8").read()
    techs = json.loads(techs_raw)
    core_raw = io.open(os.path.join(D, "core-ids.json"), encoding="utf-8").read()
    core_doc = json.loads(core_raw)
    assert dump_like(techs_raw, techs) == techs_raw and dump_like(core_raw, core_doc) == core_raw, "排版不一致，拒绝回写"

    by_id = {t["id"]: t for t in techs}
    actions = []
    for tid, (old_y, new_y, why) in YEAR_FIXES.items():
        t = by_id.get(tid)
        if not t:
            sys.exit(f"数据里找不到 {tid}")
        if t["year"] != old_y:
            sys.exit(f"{tid} 现 year={t['year']}，与决议假设的 {old_y} 不符，中止")
        actions.append(f"year  {tid:<26} {old_y} → {new_y}")
    for tid, (old_e, new_e) in REGISTRY_FIXES.items():
        entry = next((c for c in core_doc["coreIds"] if c["id"] == tid), None)
        if not entry:
            sys.exit(f"注册表里找不到 {tid}，中止")
        if entry["era"] != old_e:
            sys.exit(f"{tid} 注册表现 era={entry['era']}，与决议假设的 {old_e} 不符，中止")
        now = by_id[tid]["era"]
        if now != new_e:
            sys.exit(f"{tid} 数据 era={now}，与目标 {new_e} 不符（派生逻辑变了？），中止")
        actions.append(f"注册表 {tid:<24} era {old_e} → {new_e}")

    print("\n".join(actions))
    if not apply_changes:
        print("\n（干跑。加 --apply 写入。）")
        return

    for tid, (_, new_y, _) in YEAR_FIXES.items():
        by_id[tid]["year"] = new_y
    for tid, (_, new_e) in REGISTRY_FIXES.items():
        next(c for c in core_doc["coreIds"] if c["id"] == tid)["era"] = new_e

    io.open(os.path.join(D, "techs.json"), "w", encoding="utf-8").write(dump_like(techs_raw, techs))
    io.open(os.path.join(D, "core-ids.json"), "w", encoding="utf-8").write(dump_like(core_raw, core_doc))
    json.dump({"date": "2026-09-21", "year_fixes": YEAR_FIXES, "registry_fixes": REGISTRY_FIXES,
               "backups": ["data/techs.json.bak-20260921b", "data/core-ids.json.bak-20260921"]},
              io.open(os.path.join(D, "boundary-decision-20260921.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("已写入 techs.json 与 core-ids.json，审计记录 data/boundary-decision-20260921.json")


if __name__ == "__main__":
    main()
