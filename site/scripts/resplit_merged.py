# -*- coding: utf-8 -*-
"""
F11 数据修复：撤销历史上 35 次"按 wikiEn 的跨 id 自动合并"造成的两类损伤。

  ① 保留条目被污染：merge_records 旧版取"更长的 desc"并把双方 prereqs/related 求并集，
     却保留自己的 year/era/category → year 与 desc 自相矛盾、并继承了对方的时间倒挂边。
     → desc 还原为源记录自己的；prereqs/related 减去被吞条目贡献的那部分。
  ② 被吞条目丢失：按 §3.7"不同代各收一条 + prereqs 连成演化链"拆回，
     演化边方向 = 晚出条目 prereqs 追加早出条目。

判定来自 scripts/gate_calibration.py（DUP=确为重复，保留合并；SPLIT=应拆回）。
两条我复核后从 SPLIT 改判 DUP（同物异名，拆回只会造出可见重复）：见 FORCE_DUP。
重名条目按 §3.2 消歧后缀规则改名：见 RENAMES。

用法: python scripts/resplit_merged.py            # 干跑，打印将要发生什么
      python scripts/resplit_merged.py --apply    # 备份后写入
"""
import glob
import io
import atomic
import json
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")                                   # 只读输入（research/ 与标定文件）
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUTDIR = os.environ.get("ALLTECH_OUT") or D

# 复核后改判为"确为重复"（不拆回）：名称不同但指同一材料/同一事件
FORCE_DUP = {
    "faience ← egyptian_faience": "釉砂 / 费昂斯 = faience 同一材料，1000 年差是测年分歧而非两代技术",
}
# 拆回后与保留条目中文名重名 → 按 §3.2 加限定
RENAMES = {
    "simson_line": "西姆松线（华莱士发表）",
    "stern_rudder": "船尾舵（古典）",
    "sternpost_rudder": "船尾柱舵（中世纪欧洲）",
    "crank": "曲柄机构（中世纪普及）",
}


def load_src():
    src = OrderedDict()
    for f in sorted(glob.glob(os.path.join(D, "research", "*.json"))):
        data = json.load(io.open(f, encoding="utf-8"))
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and x.get("id") and x["id"] not in src:
                    src[x["id"]] = x
    return src


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    by_id = {t["id"]: t for t in techs}
    calib = json.load(io.open(os.path.join(D, "gate-calibration.json"), encoding="utf-8"))
    src = load_src()

    restore, keep_dup, notes = [], [], []
    for p in calib:
        key = f"{p['kept_id']} ← {p['swallowed_id']}"
        a, b = src.get(p["kept_id"]), src.get(p["swallowed_id"])
        if not (a and b):
            notes.append(f"跳过 {key}：源记录缺失")
            continue
        surv = by_id.get(p["kept_id"])
        if surv is None:
            notes.append(f"跳过 {key}：保留条目已不在库")
            continue
        if p["swallowed_id"] in by_id:
            notes.append(f"已在库（幂等跳过）{p['swallowed_id']}")
            continue
        # ① 还原保留条目被污染的部分
        fix = {}
        if (a.get("desc") or "").strip() and (surv.get("desc") or "") != (a.get("desc") or ""):
            fix["desc"] = a["desc"]
        for k, own in (("prereqs", a.get("prereqs") or []), ("related", a.get("related") or [])):
            contributed = set(b.get(k) or [])
            cur = set(surv.get(k) or [])
            if cur - contributed != set(own) - contributed:
                fix[k] = sorted((cur - contributed) | (set(own) - contributed))
        # ② 决定拆回或保留合并
        is_dup = p["label"] == "DUP" or key in FORCE_DUP
        earlier, later = (a, b) if (a.get("year") or 0) <= (b.get("year") or 0) else (b, a)
        evo_link = None
        if not is_dup and earlier["id"] != later["id"]:
            evo_link = later["id"]   # 晚出的一条要在 prereqs 里指回早出的一条
        if is_dup:
            keep_dup.append((key, fix))
        else:
            rec = dict(b)
            rec.pop("_file", None)
            if b["id"] in RENAMES:
                rec["name"] = RENAMES[b["id"]]
            if evo_link == b["id"]:
                pr = list(rec.get("prereqs") or [])
                if earlier["id"] not in pr and len(pr) < 4:
                    rec["prereqs"] = sorted(set(pr + [earlier["id"]]))
            elif evo_link == a["id"]:
                pr = list(fix["prereqs"]) if "prereqs" in fix else list(surv.get("prereqs") or [])
                if earlier["id"] not in pr and len(pr) < 4:
                    fix["prereqs"] = sorted(set(pr + [earlier["id"]]))
            restore.append((key, rec, fix))

    print(f"标定集 {len(calib)} 对 → 拆回 {len(restore)} 条，保留合并 {len(keep_dup)} 对")
    for key, rec, fix in restore:
        print(f"  拆回 {rec['id']:<32} year={rec['year']:>7} {rec['name']}｜{(rec['desc'] or '')[:26]}"
              + (f"   [还原保留条目 {list(fix)}]" if fix else ""))
    print(f"\n保留合并（仅还原保留条目字段）{len(keep_dup)} 对：")
    for key, fix in keep_dup:
        print(f"  {key}" + (f"   还原 {list(fix)}" if fix else "   无污染"))
    if notes:
        print("\n备注:", "; ".join(notes))
    print(f"\n库规模变化: {len(techs)} → {len(techs) + len(restore)}")

    if not apply_changes:
        print("\n（干跑。--apply 写入，写入前另存备份。）")
        return

    for key, _, fix in restore:
        kid = key.split(" ← ")[0]
        by_id[kid].update(fix)
    for key, fix in keep_dup:
        by_id[key.split(" ← ")[0]].update(fix)
    for _, rec, _ in restore:
        techs.append(rec)
    techs.sort(key=lambda t: t["year"])
    bak = TECHS + ".bak-resplit"
    io.open(bak, "w", encoding="utf-8").write(raw)
    out = json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else "")
    atomic.write_atomic(TECHS, out)
    json.dump({"restored": [[k, r["id"]] for k, r, _ in restore],
               "kept_merged": [k for k, _ in keep_dup],
               "force_dup_reclassified": {k: v for k, v in FORCE_DUP.items() if v}},
              io.open(os.path.join(OUTDIR, "resplit-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"已写入 {TECHS}（备份 data/techs.json.bak-resplit），明细 data/resplit-report.json")


if __name__ == "__main__":
    main()
