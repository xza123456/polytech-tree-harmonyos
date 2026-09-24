# -*- coding: utf-8 -*-
"""
F10 第二步：把 techs.json 的 category 从 8 域确定性重标到 22 域。

规则是有序的（先命中先得），每条记录都记进 data/domain-relabel-audit.json，
标注它被哪条规则、哪个关键词判到哪个域，未命中任何规则则落回该旧域的"主干域"。
不接模型：8→22 是映射 + 关键词裁决，必须可复现、可回退。

用法: python scripts/relabel_domains.py           # 干跑，打印分布与规则命中量
      python scripts/relabel_domains.py --apply    # 写 techs.json 与 core-ids.json
"""
import io
import atomic
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
TECHS = os.environ.get("ALLTECH_TECHS") or os.path.join(D, "techs.json")
OUTDIR = os.path.join(D)

# 旧域 → 主干新域（没有任何规则命中时的落点）
TRUNK = {
    "math_logic": "math_pure", "information": "info_media", "physical_science": "physics",
    "life_medicine": "life_medicine", "materials": "materials", "energy_power": "energy_power",
    "transport_exploration": "transport", "society": "governance",
}
# (旧域, 正则, 新域) —— 顺序即优先级
RULES = [
    # ── 数学内部先分逻辑/算法，再留数学 ──
    ("math_logic", r"公理|集合论|可计算|停机|不可判定|证明论|类型论|数理逻辑|逻辑斯蒂|哥德尔|丘奇|皮亚诺|序数|基数", "logic_foundations"),
    ("math_logic", r"算法|复杂性|NP|图算法|排序算法|编码理论|密码|信息论|香农|自动机|计算理论|机器学习理论", "algorithms_cs"),
    # ── information：计算系统 / 算法理论 / 其余留信息传播 ──
    ("information", r"望远镜|显微镜|光谱仪|探测器|粒子探测|加速|量热|射电|干涉仪", "physics"),
    ("information", r"密码|编码理论|信息论|压缩算法|算法|复杂性|图论算法|随机化算法", "algorithms_cs"),
    ("information", r"计算机|处理器|微处理|内存|存储程序|操作系|软件|程序|编译|数据库|人工智能|神经网络|机器学习|深度学习|芯片|集成电路|晶体管|逻辑门|图形界面|编程语言|算法实现", "computing_systems"),
    # ── 生命 / 农业食品 分家 ──
    ("life_medicine", r"^(?!.*麻醉).*?农|作物品?种|耕|耘|畜|牧|饲|肥料|(?<!肥)肥|粮|稻|麦|粟|黍|棉花|大麻|桑|蚕|茶|酒|醋|酱|面包|乳制品|蜂|育种|选种|轮作|犁|镰|脱粒|灌溉|食物|烹饪|保鲜|腌|制糖|榨油|菇|栽培|人造黄油", "agriculture_food"),
    ("life_medicine", r"望远镜|显微镜|X ?射线|CT|核磁|超声|内镜|起搏|人工?器官|透析|注射|手术|麻醉|缝合|疫苗|免疫|抗生素|药物|医|病|基因|染色|细胞|细菌|病毒|解剖|生理|胚胎|进化|生态|分类学|光合|神经", "life_medicine"),
    # ── 材料 / 制造工艺 / 化学 / 建筑 / 军事 分家 ──
    ("materials", r"武器|兵|炮|箭|弹|甲|盔|盾|铠|城防|要塞|壕|地雷|坦克|战舰|军舰|火药|炸药|毒气|军事", "military"),
    ("materials", r"建筑|房屋|墙|屋顶|混凝|砂浆|灰泥|砖|石砌|拱|穹顶|桥|大坝|堤|隧道|下水道|供水|排水|管道|铺装|脚手架|施工法", "construction"),
    ("materials", r"聚合|塑料|化纤|合成纤维|染料|颜料|酸|碱|盐|溶剂|催化|电解|化学工业|制药工艺|蒸馏|发酵|炼油|石化|橡胶|树脂", "chemistry"),
    ("materials", r"机床|车削|铣|磨削|钻|铸造|锻|焊接|铆|纺织|织机|纺|染|印刷工艺|印刷机|光刻|封装|镀膜|切削|拉丝|制鞋|制陶|窑|烧结|增材|3D ?打印|流水线|批量生产|标准化生产|制造工艺|加工技术", "manufacturing"),
    ("materials", r"钢|铁|铜|青铜|合金|金属|陶瓷|瓷|玻璃|釉|漆|纸|木材|石|水泥|纤维|晶体|半导体材料|超导材料|纳米|复合材|碳|硅|石墨|金刚石", "materials"),
    # ── 交通 / 航天深海 / 军事 ──
    ("transport_exploration", r"火箭|卫星|载人|飞船|空间站|航天|月球|火星|冥王星|柯伊伯|深空|飞掠|返回式|探月|着陆器|发射台|组网|近地轨道", "space_exploration"),
    ("transport_exploration", r"深海|潜水器|极地|科考船|无人潜|马里亚纳", "space_exploration"),
    ("transport_exploration", r"战舰|军舰|潜艇|鱼雷|航母|装甲车|军用飞?机|补给|登陆|军械", "military"),
    ("transport_exploration", r"轮|车|船|舰|桥?梁?|轨道|铁路|机动车|内燃|自行|帆|桨|滑翔|飞机|飞行器|直升机|气垫|磁悬浮|运河|航道|码头|港|导航|经度|罗盘|海图|地图测绘|管道运输|电梯|缆车", "transport"),
    # ── 物理科学 → 物理 / 化学 / 地空 / 生命 ──
    ("physical_science", r"化学|元素|化合|原子量|周期表|分子结构|同位素化学|电解质|催化剂|燃烧化学|氧化物|酸|碱|盐类|pH|中和|氧化还原", "chemistry"),
    ("physical_science", r"天文|行星|恒星|宇宙|星系|彗星|陨石|岁差|星表|光谱分析|望远镜|射电", "earth_space"),
    ("physical_science", r"地球|地质|板块|地震|火山|矿物|岩石|化石|气象|气候|海洋|大陆漂移|地磁|水文|土壤", "earth_space"),
    ("physical_science", r"基因|遗传|细胞|物种|进化|生态|生理|解剖|光合|微生?物|细菌|病毒", "life_medicine"),
    # ── 社会 → 治理 / 经济 / 教育 / 文化 / 日常 ──
    ("society", r"货币|银行|税|贸易|市场|保险|信贷|金融|股票|公司|产权|经济|成本|价格|商业", "economy"),
    ("society", r"学校|大学|学院|教育|教学|考试|科举|学位|学会|期刊|图书|馆藏|标准化|术语|目录|百科|学术|课程", "education_knowledge"),
    ("society", r"艺术|绘画|绘|雕塑|音乐|乐器|舞蹈|戏剧|诗|文学|小说|电影|摄影|动画|游戏|体育|奥运|宗教|礼仪|服饰风格|媒体|新闻|出版内容", "culture_media"),
    ("society", r"日用|家居|家具|衣|鞋|帽|梳|镜|皂|洗涤|化妆|厨具|餐具|文具|钟表?家用|玩具|清洁", "daily_life"),
    ("energy_power", r"武器|核武|弹道|导弹|军", "military"),
    ("energy_power", r"燃料|炼油|汽油|柴油|天然?气|煤|炭|石油", "energy_power"),
]
COMPILED = [(old, re.compile(rx, re.I), new) for old, rx, new in RULES]


JEV = {}
_jev_path = os.path.join(D, "domain-relabel-jev.json")
if os.path.exists(_jev_path):
    JEV = json.load(io.open(_jev_path, encoding="utf-8"))


NEW_IDS = {c["id"] for c in json.load(io.open(os.path.join(D, "categories.json"), encoding="utf-8"))}


def decide(t):
    """判定优先级：Jev 受限选择 → 关键词规则 → 该旧域主干域。

    跳过条件：记录已经在 22 域体系内**且**没有历史 Jev 判定 —— 说明它是净增批次里
    按新 schema 直接 authored 的条目，重洗只会把好数据搅乱（materials/life_medicine/
    energy_power 三个 id 在新旧体系里同名，不区分会被规则二次改写）。
    """
    cached = JEV.get(t["id"])
    if cached and cached.get("domain"):
        return cached["domain"], f"jev(conf={cached.get('conf')})"
    if t.get("category") in NEW_IDS:
        return t["category"], "already-v2"
    return _decide_rule(t)


def _decide_rule(t):
    text = " ".join([t.get("name") or "", t.get("nameEn") or "", t.get("desc") or "",
                     " ".join(t.get("aliases") or [])])
    for old, rx, new in COMPILED:
        if t.get("category") != old:
            continue
        m = rx.search(text)
        if m:
            return new, f"rule:{old}~{m.group(0)[:14]}"
    return TRUNK.get(t.get("category"), t.get("category")), "trunk:" + str(t.get("category"))


def main():
    apply_changes = "--apply" in sys.argv
    raw = io.open(TECHS, encoding="utf-8").read()
    techs = json.loads(raw)
    cats = {c["id"] for c in json.load(io.open(os.path.join(D, "categories.json"), encoding="utf-8"))}
    audit, moves = [], Counter()
    for t in techs:
        new, how = decide(t)
        assert new in cats, f"目标域 {new} 不在 categories.json"
        moves[(t["category"], new)] += 1
        if new != t["category"]:
            audit.append({"id": t["id"], "name": t["name"] or t["nameEn"], "from": t["category"],
                          "to": new, "how": how})
    print(f"全库 {len(techs)} 条；需改判 {len(audit)} 条")
    srcs = Counter(decide(t)[1].split("(")[0].split(":")[0] for t in techs)
    print("判定来源分布:", dict(srcs))
    new_dist = Counter(decide(t)[0] for t in techs)
    print("\n新分布（按条数）")
    for k, v in new_dist.most_common():
        print(f"  {k:<24}{v:>5}  {v/len(techs)*100:>5.1f}%")
    print("\n主干迁移 top 12")
    for (a, b), n in moves.most_common(12):
        print(f"  {a:<22}→ {b:<22}{n}")
    print("\n改判样例:", "  ".join(f"{a['id']}[{a['how'].split('~')[0]}]" for a in audit[:8]))
    json.dump({"total": len(techs), "changed": len(audit), "distribution": dict(new_dist),
               "moves": {f"{a}->{b}": n for (a, b), n in moves.items()}, "items": audit},
              io.open(os.path.join(OUTDIR, "domain-relabel-audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if not apply_changes:
        print("\n（干跑。--apply 写入。）")
        return
    for t in techs:
        t["category"] = decide(t)[0]
    atomic.write_atomic(TECHS, 
        json.dumps(techs, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""))
    core_path = os.path.join(D, "core-ids.json")
    core_raw = io.open(core_path, encoding="utf-8").read()
    core_doc = json.loads(core_raw)
    by_id = {t["id"]: t for t in techs}
    n = 0
    for c in core_doc["coreIds"]:
        t = by_id.get(c["id"])
        if t and c["category"] != t["category"]:
            c["category"] = t["category"]
            n += 1
    io.open(core_path, "w", encoding="utf-8").write(
        json.dumps(core_doc, ensure_ascii=False, indent=2) + "\n")
    print(f"已写 techs.json 与 core-ids.json（注册表 category 同步 {n} 条）")


if __name__ == "__main__":
    main()
