# -*- coding: utf-8 -*-
"""
F10 第一步：生成 v2 领域表 data/categories.json（4 群 × 22 域）。

配色按群分配色相带、群内等分开，不手挑颜色 —— 保证可复现且群内相近、群间可辨。
`polyhedron` 字段已废弃（形状改由重要度决定，见方案 §5.1），不再写入。
"""
import colorsys
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "categories.json")

# (域 id, 中文名, 英文名, 群, 子类目)
DOMAINS = [
    ("math_pure", "数学", "Mathematics", "A",
     ["数论与代数", "几何与拓扑", "分析学", "概率统计", "离散与组合"]),
    ("logic_foundations", "逻辑与基础", "Logic and Foundations", "A",
     ["数理逻辑", "集合论", "证明论与公理化", "类型论与可计算性"]),
    ("algorithms_cs", "算法与计算理论", "Algorithms and Computation Theory", "A",
     ["算法与数据结构", "计算复杂性", "信息论与编码", "密码学理论"]),
    ("computing_systems", "计算系统", "Computing Systems", "A",
     ["计算机硬件", "操作系统与软件", "人工智能", "机器学习"]),
    ("info_media", "信息记录与传播", "Information Recording and Communication", "A",
     ["文字与书写", "印刷与出版", "电信", "计算机网络", "科学仪器"]),
    ("physics", "物理学", "Physics", "B",
     ["力学", "电磁与光学", "热学与统计", "近代物理", "声学"]),
    ("chemistry", "化学", "Chemistry", "B",
     ["化学理论", "无机化学", "有机与高分子", "电化学与催化"]),
    ("life_medicine", "生命科学与医学", "Life Science and Medicine", "B",
     ["生物学", "医药", "疫苗与免疫", "基因与细胞", "医学影像", "公共卫生"]),
    ("earth_space", "地球与天文", "Earth and Space Science", "B",
     ["天文学", "观测天文仪器", "地质与板块", "气象与气候", "地球物理"]),
    ("materials", "材料", "Materials", "C",
     ["金属材料", "无机非金属", "有机与高分子材料", "半导体材料", "复合材料"]),
    ("manufacturing", "制造与工艺", "Manufacturing and Processes", "C",
     ["冶金工艺", "机械加工", "纺织与染色", "铸造与锻造", "光刻与封装", "增材制造"]),
    ("energy_power", "能源与动力", "Energy and Power", "C",
     ["火与燃料", "蒸汽与内燃", "电力与电网", "核能", "新能源与储能"]),
    ("construction", "建筑与基础设施", "Construction and Infrastructure", "C",
     ["建筑结构", "材料与施工", "市政管网", "交通土建", "水利工程的非通航部分"]),
    ("transport", "交通与运载", "Transport", "C",
     ["轮与陆路车辆", "船舶", "航空器", "管道与物流", "导航定位"]),
    ("agriculture_food", "农业与食品", "Agriculture and Food", "C",
     ["农具与耕作", "作物与育种", "畜牧", "食品加工与保藏", "肥料与土壤"]),
    ("military", "军事与安全", "Military and Security", "C",
     ["冷兵器与防护", "火器与弹药", "要塞与城防", "军用载具", "情报与通信安全"]),
    ("space_exploration", "航天与深海极地探索", "Space and Deep-sea Exploration", "C",
     ["火箭与发射", "航天器与卫星", "载人航天", "深海与极地载具"]),
    ("governance", "社会组织与治理", "Governance and Institutions", "D",
     ["法律与司法", "行政与官僚制", "公共政策", "军事与政治制度", "权利与身份制度"]),
    ("economy", "经济与金融", "Economy and Finance", "D",
     ["货币与信用", "贸易与市场制度", "财税", "银行与保险", "经济思想"]),
    ("education_knowledge", "教育与知识制度", "Education and Knowledge Systems", "D",
     ["学校与教学", "考试与选才", "学术组织", "知识整理与标准"]),
    ("culture_media", "文化与艺术媒介", "Culture and Artistic Media", "D",
     ["视觉艺术", "音乐与乐器", "文学与戏剧", "体育与游戏", "影像与广播内容"]),
    ("daily_life", "日常生活器物", "Daily Life Objects", "D",
     ["家居与日用", "服饰与穿戴", "饮食器具", "清洁与卫生用品", "文具与办公"]),
]

GROUP_HUE = {"A": 195, "B": 8, "C": 88, "D": 312}   # 色相带起点（度）


def main():
    per_group = {}
    for d in DOMAINS:
        per_group.setdefault(d[3], []).append(d)
    out = []
    for gid, items in per_group.items():
        n = len(items)
        for i, (did, zh, en, _, subs) in enumerate(items):
            h = ((GROUP_HUE[gid] + (i - (n - 1) / 2) * (26.0 / max(n - 1, 1))) % 360) / 360
            s = 0.62 if gid in ("A", "B") else 0.58
            l = 0.56 + (0.06 if i % 2 else -0.04)
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            out.append({"id": did, "name": zh, "nameEn": en, "group": gid,
                        "color": "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255)),
                        "subcategories": subs})
    out.sort(key=lambda c: [d[0] for d in DOMAINS].index(c["id"]))
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"写入 {OUT}：{len(out)} 域，群分布 " +
          " ".join(f"{g}={sum(1 for c in out if c['group'] == g)}" for g in "ABCD"))
    print("配色:", " ".join(f"{c['id']}={c['color']}" for c in out[:4]), "…")


if __name__ == "__main__":
    main()
