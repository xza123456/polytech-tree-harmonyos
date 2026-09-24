# -*- coding: utf-8 -*-
"""
数据流水线编排：research/ → 合并 → era 派生 → 拆回修复 → 连线与命名修复 → 校验。
每一步都是幂等的脚本，顺序固定；techs.json 因此是"可复现产物"而不是手工文件。

用法: python scripts/build_pipeline.py               # 正式重建 data/techs.json
      python scripts/build_pipeline.py --tmp         # 只跑到临时目录，用于复现性验证
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
STEPS = ["verify_wikien.py", "merge_research.py", "recompute_era.py", "resplit_merged.py",
         "fix_dup_wikien.py",
         "fix_edges_and_names.py", "relabel_domains.py", "fix_kind.py",
         # 决策③收尾：知识域里被规则误标成"工艺"的理论条目改回 原理/器物
         "fill_year_basis.py",
         # 年代取证：batch_asserted → exact 只在词条正文/信息框能检得该年份时才升
         "promote_exact_year.py",
         # 补边必须是流水线一步：techs.json 是产物，直接改它会被下次重建冲掉
         "apply_edge_patches.py", "link_by_mention.py",
         # importance 复核要用完整扇入，所以放在所有补边之后
         "recalibrate_importance.py",
         # 溯源第二道判据：条目存在还不算，挂到消歧页等于没溯源（首轮全扫 ~7 分钟，之后只查新标题）
         "scan_disambig.py", "validate_data.py"]


def preflight():
    """并发批次代理会反复覆盖写 research/*.json：抓到半截文件时给出明确 abort，
    而不是让某个步骤抛 JSONDecodeError  traceback。"""
    import io
    import json
    bad = []
    for pat in (os.path.join(ROOT, "data", "research", "*.json"),
                os.path.join(ROOT, "data", "edge-patches", "*.json")):
        for f in glob.glob(pat):
            try:
                json.load(io.open(f, encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                bad.append(f"{os.path.relpath(f, ROOT)}: {e}")
    if bad:
        sys.exit("输入文件不可解析（可能正被并发写入），构建中止：\n  " + "\n  ".join(bad))


def run(script, extra=()):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"\n=== {script} {' '.join(extra)} ===")
    r = subprocess.run([sys.executable, os.path.join(S, script), *extra], env=env, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"{script} 失败（exit {r.returncode}），流水线中止")


# 年代取证的信息框二查（--deep）不进构建：它要为每条未命中条目单独发一次请求，
# 1500 条要 20 分钟以上，会把每次重建拖成联网批作业。它是维护任务，手工跑：
#   python scripts/promote_exact_year.py --deep --apply
# 构建里只跑导语批量核验（按 id 缓存，只为新增条目发请求），命中才升 exact；
# 由于没有二查，降级（自报 exact 但正文查不到）只在维护跑时发生。
EXTRA = {"scan_disambig.py": []}


def main():
    tmp = "--tmp" in sys.argv
    if tmp:
        outdir = os.path.join(ROOT, "data", "_pipeline_tmp")
        os.makedirs(outdir, exist_ok=True)
        os.environ["ALLTECH_TECHS"] = os.path.join(outdir, "techs.json")
        os.environ["ALLTECH_OUT"] = outdir
        os.environ["MR_OUT_JSON"] = os.path.join(outdir, "techs.json")
        os.environ["MR_REPORT"] = os.path.join(outdir, "merge-report.json")
        os.environ["ALLTECH_ADJ"] = os.path.join(outdir, "dup-wikien-adjudication.json")
        # 联网取证的缓存也必须分家：--tmp 跑的是验证，不该写正式取证结果
        os.environ["ALLTECH_YEAR_CACHE"] = os.path.join(outdir, "year-basis-corroboration-cache.json")
        os.environ["ALLTECH_DISAMBIG_CACHE"] = os.path.join(outdir, "disambiguation-cache.json")
        print(f"（临时模式：产物 {os.environ['ALLTECH_TECHS']}，不动 data/techs.json）")
    preflight()
    for st in STEPS:
        run(st, [] if st == "validate_data.py" else ["--apply", *EXTRA.get(st, [])])
    if tmp:
        print(f"\n临时产物：{os.environ['MR_OUT_JSON']}")


if __name__ == "__main__":
    main()
