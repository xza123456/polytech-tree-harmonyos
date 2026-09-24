# -*- coding: utf-8 -*-
"""
validate_data.py — 校验 data/techs.json（合并后唯一事实源）。
检查：schema 字段、枚举、id 唯一、引用闭合、自环、年份/era 区间、
注册表白名单、importance 配额，并输出分布统计。
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TECHS_PATH = os.environ.get("ALLTECH_TECHS") or os.path.join(DATA, "techs.json")
OUTDIR = os.environ.get("ALLTECH_OUT") or DATA

# 规范 §3.1 v2 全部 15 字段。year_span/year_note 允许为 null/空串但键必须存在。
REQUIRED = ["id", "name", "nameEn", "wikiEn", "aliases", "year", "year_basis", "year_span",
            "year_note", "era", "category", "kind", "importance", "prereqs", "related", "desc"]
YEAR_BASIS = {"exact", "decade", "century", "circa", "range_midpoint", "scholarly_disputed",
              "convention_floor", "batch_asserted"}

import re


def norm_title(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[‐-―\-_/(),.:;!?'\"&]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def era_deriver(era_list):
    """era 由 year 查表：半开区间 [yearStart, yearEnd)，仅末段包含其 yearEnd（规范 §3.8）。"""
    ordered = sorted(era_list, key=lambda e: e["order"])

    def derive(year):
        for i, e in enumerate(ordered):
            last = i == len(ordered) - 1
            if e["yearStart"] <= year < e["yearEnd"] or (last and year == e["yearEnd"]):
                return e["id"]
        return None
    return derive


def main():
    techs = json.load(open(TECHS_PATH, encoding="utf-8"))
    # wikiEn 留空的两种情况要分开：豁免清单里的是"检索确认无独立条目"，不报警；
    # 不在清单里的才是真漏填。
    exempt_path = os.path.join(DATA, "wikien-none-allowlist.json")
    WIKIEN_EXEMPT = set()
    if os.path.exists(exempt_path):
        WIKIEN_EXEMPT = set(json.load(open(exempt_path, encoding="utf-8"))["items"])
    # 同题拆分表里被置空的条目也是"有意留空"，不算漏填
    adj_path = os.environ.get("ALLTECH_ADJ") or os.path.join(DATA, "dup-wikien-adjudication.json")
    if os.path.exists(adj_path):
        WIKIEN_EXEMPT |= {r["id"] for r in json.load(open(adj_path, encoding="utf-8"))}
    era_list = json.load(open(os.path.join(DATA, "eras.json"), encoding="utf-8"))
    eras = {e["id"]: e for e in era_list}
    derive_era = era_deriver(era_list)
    cats = {c["id"]: c for c in json.load(open(os.path.join(DATA, "categories.json"), encoding="utf-8"))}
    core = json.load(open(os.path.join(DATA, "core-ids.json"), encoding="utf-8"))["coreIds"]
    core_map = {c["id"]: c for c in core}

    ids = set()
    id_counter = Counter()
    for t in techs:
        id_counter[t.get("id", "?")] += 1
    dup_ids = [i for i, n in id_counter.items() if n > 1]
    if dup_ids:
        err(f"重复 id: {dup_ids}")

    for t in techs:
        rid = t.get("id", "?")
        missing = [k for k in REQUIRED if k not in t]
        extra = [k for k in t if k not in REQUIRED]
        if missing:
            err(f"{rid}: 缺字段 {missing}")
        if extra:
            warn(f"{rid}: 多余字段 {extra}")
        ids.add(rid)

        if t.get("era") not in eras:
            err(f"{rid}: 非法 era={t.get('era')}")
        if t.get("category") not in cats:
            err(f"{rid}: 非法 category={t.get('category')}")
        imp = t.get("importance")
        if not isinstance(imp, int) or not (1 <= imp <= 5):
            err(f"{rid}: 非法 importance={imp}")
        y = t.get("year")
        if not isinstance(y, int):
            err(f"{rid}: 非法 year={y}")
        elif t.get("era") in eras:
            want = derive_era(y)
            if want is None:
                err(f"{rid}: year={y} 落在所有 era 区间之外")
            elif want != t["era"]:
                err(f"{rid}: era 与 year 不一致（year={y} 应为 {want}，实为 {t['era']}）—— era 由 year 生成，不得手填")
        for key in ("aliases", "prereqs", "related"):
            if not isinstance(t.get(key), list):
                err(f"{rid}: {key} 必须是数组")
        if len(t.get("prereqs", [])) > 4 or len(t.get("related", [])) > 4:
            warn(f"{rid}: 关系超过 4 条")
        if rid in (t.get("prereqs") or []) or rid in (t.get("related") or []):
            err(f"{rid}: 自引用")
        yb = t.get("year_basis")
        if yb is None:
            # §6 规定 year_basis 必填。这条必须查产物而不是查补字段脚本的自我汇报：
            # fill_year_basis.py 曾因逐键拷贝顺序把赋值又覆盖成 null，静默漏了 2799 条。
            err(f"{rid}: year_basis 为空（§6 必填）")
        elif yb not in YEAR_BASIS:
            err(f"{rid}: 非法 year_basis={yb}")
        if not t.get("wikiEn") and rid not in WIKIEN_EXEMPT:
            warn(f"{rid}: wikiEn 为空")
        if not (t.get("name") or "").strip():
            err(f"{rid}: 中文名留空（界面会回退显示英文，属可见缺陷）")
        if not t.get("name"):
            warn(f"{rid}: 中文名留空（将回退显示英文）")
        if t.get("desc") and len(t["desc"]) > 40:
            warn(f"{rid}: desc 超 40 字 ({len(t['desc'])})")

    # 引用闭合
    year_of = {t["id"]: t["year"] for t in techs if "id" in t and isinstance(t.get("year"), int)}
    dangling = defaultdict(list)
    for t in techs:
        for key in ("prereqs", "related"):
            for ref in t.get(key) or []:
                if ref not in ids:
                    dangling[ref].append(f"{t['id']}({key})")
                elif key == "prereqs" and isinstance(t.get("year"), int) and ref in year_of:
                    if year_of[ref] > t["year"]:
                        err(f"{t['id']}: 前置 {ref} 年份晚于本条（{year_of[ref]} > {t['year']}）—— 时间上不可能构成依赖，应改判或降级为 related")
    if dangling:
        for ref, used in sorted(dangling.items()):
            # 合并阶段已有"剔除悬空引用"的步骤，走到这里还出现就是真缺陷 → error
            err(f"悬空引用 {ref} <- {used}")

    # 注册表白名单
    missing_core = []
    mismatched_core = []
    for cid, c in core_map.items():
        t = next((x for x in techs if x.get("id") == cid), None)
        if t is None:
            missing_core.append(cid)
        else:
            if t["era"] != c["era"] or t["category"] != c["category"]:
                mismatched_core.append(f"{cid}: 数据 era={t['era']}/cat={t['category']} vs 注册表 {c['era']}/{c['category']}")
    if missing_core:
        err(f"缺失注册表核心 id（{len(missing_core)}）: {missing_core}")
    for m in mismatched_core:
        err(f"注册表归属不一致: {m}")

    # 去重主键健康度：一篇词条只能挂在一个条目上（§3.7 裁决已把同题多贡献拆到 aliases + 演化边）
    wk = Counter(norm_title(t.get("wikiEn")) for t in techs if t.get("wikiEn"))
    dup_groups = {k: v for k, v in wk.items() if v > 1}
    isolated = [t["id"] for t in techs if not (t.get("prereqs") or []) and not (t.get("related") or [])]
    # §4.3：标成"基石"（1 档）却没有任何条目依赖它 —— 要么下游漏接线，要么档位虚高
    inbound = Counter(o for t in techs for o in (set(t.get("prereqs") or []) | set(t.get("related") or [])))
    p1_unlinked = sorted(t["id"] for t in techs if t.get("importance") == 1 and inbound[t["id"]] == 0)
    if p1_unlinked:
        warn(f"P1 条目零入边 {len(p1_unlinked)}：{p1_unlinked[:8]}（补下游入边或降档，见 §16）")
    # §4.3 结构信号：某域几乎没有 1 档条目，通常是"该域的基石没标出来"而不是"该域真的没有基石"
    n = len(techs)
    dom = defaultdict(lambda: [0, 0])
    for t_ in techs:
        d = dom[t_.get("category")]
        d[0] += 1
        if t_.get("importance") == 1:
            d[1] += 1
    for cid, (dtot, dp1) in sorted(dom.items()):
        if dtot >= 50 and dp1 / dtot < 0.02:
            warn(f"领域 {cid} 的 1 档仅 {dp1}/{dtot} = {dp1 / dtot:.1%}（<2%，疑基石层漏标，见 §4.3）")
    # §4.3 对称信号：长尾/骨干比过高 = 该域收得很细但主干还没齐（N-09 就是这么找出来的）
    ratio = defaultdict(lambda: [0, 0])
    for t_ in techs:
        r = ratio[t_.get("category")]
        r[0 if t_.get("importance", 3) >= 3 else 1] += 1
    for cid, (tail, back) in sorted(ratio.items(), key=lambda kv: -(kv[1][0] / max(kv[1][1], 1))):
        if back >= 15 and tail / back > 2.5:
            warn(f"领域 {cid} 长尾/骨干 = {tail}/{back} = {tail / back:.2f}（>2.5，建议做 P1/P2 欠账普查）")
    if dup_groups:
        err(f"wikiEn 重复组 {len(dup_groups)}：{sorted(dup_groups)[:8]}")
    nm = Counter(t.get("name") for t in techs)
    same_name = {k: v for k, v in nm.items() if v > 1}
    if same_name:
        err(f"中文同名条目 {len(same_name)}：{sorted(same_name)[:8]}")

    # F8 溯源闸：techs.json 是产物，每条必须能从 data/research/*.json 复现出来。
    # 手改进产物的条目会在下次重建时凭空消失，所以宁可现在报红也不要留孤儿。
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from merge_research import PRE_ID_FIX, RESEARCH_DIR  # noqa: PLC0415
        sourced = set()
        for fp in glob.glob(os.path.join(RESEARCH_DIR, "*.json")):
            try:
                sourced |= {r.get("id") for r in json.load(open(fp, encoding="utf-8"))}
            except Exception:  # noqa: BLE001  半写文件由合并阶段负责报
                continue
        sourced |= set(PRE_ID_FIX.values())          # 改名后的 id 也算有源
        orphans = sorted(t["id"] for t in techs if t["id"] not in sourced)
        if orphans:
            err(f"无溯源条目（不在任何 research 包，重建会丢失）{len(orphans)}：{orphans[:10]}")
    except FileNotFoundError as e:
        warn(f"溯源检查跳过：{e}")
    if isolated:
        # F9：61 → 0 已达成（§5 的 F7 接线 + 同题拆分的演化边），按原计划升为 error
        err(f"无任何连线的孤立点 {len(isolated)} 条：{isolated[:8]}（规范 §4.2-4 要求每条至少 1 条出边）")
    # §4/§7 护栏：净增批次不得把某一域堆成长尾垃圾场。
    # 存量已经超线（math_pure 611/3297 = 18.5%），所以这是"该域关闭 P3 以下净增"的信号，
    # 不是构建错误——超线时降为警告并点名，避免把删除存量当成通过闸门的手段。
    share = Counter(t["category"] for t in techs)
    over = {k: v for k, v in share.items() if v > 0.12 * len(techs)}
    for k, v in sorted(over.items(), key=lambda x: -x[1]):
        warn(f"单域占比 {v / len(techs):.1%} 超 12% 护栏: {k}（{v} 条）—— 该域只允许 P1/P2 净增")

    # 统计
    by_era = Counter(t["era"] for t in techs)
    by_cat = Counter(t["category"] for t in techs)
    by_imp = Counter(t["importance"] for t in techs)
    cross = Counter((t["era"], t["category"]) for t in techs)

    print("=== 校验结果 ===")
    print(f"总数: {len(techs)}")
    print(f"错误: {len(errors)}  警告: {len(warnings)}  悬空引用种类: {len(dangling)}")
    # 明细必须打出来：只报计数的校验器等于没有校验器
    for e in errors[:30]:
        print(f"  [err] {e}")
    if len(errors) > 30:
        print(f"  [err] …另有 {len(errors) - 30} 条")
    for w in warnings[:20]:
        print(f"  [warn] {w}")
    if len(warnings) > 20:
        print(f"  [warn] …另有 {len(warnings) - 20} 条")
    print("\n-- 按时代 --")
    for eid, e in sorted(eras.items(), key=lambda x: x[1]["order"]):
        print(f"  {e['name']:<12} {by_era.get(eid, 0)}")
    print("\n-- 按领域 --")
    for cid, c in cats.items():
        print(f"  {c['name']:<10} {by_cat.get(cid, 0)}")
    print("\n-- 按重要度（1 最高）--")
    for i in range(1, 6):
        print(f"  {i}: {by_imp.get(i, 0)}")

    out_report = os.path.join(OUTDIR, "validate-report.json")
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(techs), "errors": errors, "warnings": warnings,
            "dangling": {k: v for k, v in dangling.items()},
            "missingCoreIds": missing_core,
            "byEra": dict(by_era), "byCategory": dict(by_cat),
            "byImportance": dict(by_imp),
        }, f, ensure_ascii=False, indent=2)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
