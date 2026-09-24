# -*- coding: utf-8 -*-
"""
F4：按规范 §3.8 的定值规则补 year_basis / year_span / year_note 三字段（幂等）。

可机械判定的档位：
  convention_floor  year 恰为其 era 的起点 —— 该年份是"只知时代归属"的约定值
  century           整百或世纪中值（xx00 / xx50）
  decade            整十
  batch_asserted    其余：批次给了一个确切年份，但尚未逐条核对
诚实说明：`batch_asserted` 只代表"批次给了个年份"。**取证在下一步**
`promote_exact_year.py`：年份能在该词条正文/信息框检得的才升 `exact`。
"""
import io
import json
import os
import atomic
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")

def main():
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    eras = {e["id"]: e for e in json.load(io.open(os.path.join(D, "eras.json"), encoding="utf-8"))}
    counts = {}
    out = []
    for t in techs:
        have = t.get("year_basis")
        # 先整体拷贝，再统一覆盖：逐键拷贝时 year_basis/year_span/year_note 排在 year 之后，
        # 赋完值又会被源记录里的 null 覆盖回去（F4 曾被这样静默吞掉 2799 条，只报了"已赋值"）。
        rec = dict(t)
        if have in {"exact", "decade", "century", "circa", "range_midpoint",
                    "scholarly_disputed", "convention_floor", "batch_asserted"}:
            # 已按规范 §3.8 手工判定过（净增批次会自己填），不得被机械规则覆盖
            if "year_span" not in rec:
                rec["year_span"] = None
            if "year_note" not in rec:
                rec["year_note"] = ""
            out.append(rec)
            counts["kept(authored)"] = counts.get("kept(authored)", 0) + 1
            continue
        y, e = t["year"], eras[t["era"]]
        if y == e["yearStart"]:
            b, note = "convention_floor", "仅知时代归属，取该时代起点（规范 §3.8 规则 6）"
        elif y % 100 == 0 or y % 100 == 50:
            b, note = "century", "只知世纪，取该世纪中值（规范 §3.8 规则 3）"
        elif y % 10 == 0:
            b, note = "decade", "只知年代，取该十年代中点（规范 §3.8 规则 4）"
        else:
            # 批次给了一个确切年份，但"确切"要到词条正文/信息框能检得才算数，
            # 所以这里只标 batch_asserted，由 promote_exact_year.py 做取证升级。
            b, note = "batch_asserted", ""
        counts[b] = counts.get(b, 0) + 1
        rec["year_basis"], rec["year_span"], rec["year_note"] = b, rec.get("year_span"), note
        out.append(rec)
    atomic.write_atomic(TECHS, 
        json.dumps(out, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    print("year_basis 赋值:", counts, "合计", sum(counts.values()))

if __name__ == "__main__":
    main()
