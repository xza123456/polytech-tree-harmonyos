# -*- coding: utf-8 -*-
"""
merge_research.py — 合并 data/research/ 下 18 个任务包片段。
L2 机械去重：id / 规范化 nameEn / aliases / wikiEn 四键匹配，命中即合并。
输出：data/techs.json + merge-report.json（供 L3 语义审查）。
"""
import json
import re
import glob
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 路径可用环境变量覆盖，便于把整条流水线跑到临时目录做复现性验证
RESEARCH_DIR = os.environ.get("MR_RESEARCH_DIR") or os.path.join(ROOT, "data", "research")
OUT_JSON = os.environ.get("MR_OUT_JSON") or os.path.join(ROOT, "data", "techs.json")
REPORT = os.environ.get("MR_REPORT") or os.path.join(ROOT, "data", "merge-report.json")

# 规范 §3.1 v2 的 16 字段，且必须按此顺序投影 —— 之前只留 12 个旧字段，
# 会把净增批次按新规范填好的 kind/year_basis 等直接丢掉。
REQUIRED_FIELDS = ["id", "name", "nameEn", "wikiEn", "aliases", "year", "year_basis",
                   "year_span", "year_note", "era", "category", "kind", "importance",
                   "prereqs", "related", "desc"]


# ── 准入闸门：wikiEn 必须能在英文维基解析到真实条目 ──
# 依据 scripts/verify_wikien.py 产出的缓存判定；缓存里没有的标题按"未核验"放行并告警，
# 确认不存在的记录一律移出主库、进隔离文件（防止模型编造的概念混进科技树）。
WIKI_CACHE = os.path.join(ROOT, "data", "wikien-batch-cache.json")
QUARANTINE = os.environ.get("MR_QUARANTINE") or os.path.join(ROOT, "data", "quarantine-unverified.json")


def load_wiki_cache():
    if not os.path.exists(WIKI_CACHE):
        return {}
    with open(WIKI_CACHE, encoding="utf-8") as f:
        return json.load(f)


def norm_title(s: str) -> str:
    """规范化英文标题：小写、去标点、空格折叠。不做词干/复数归一（误伤率高）。"""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[\u2010-\u2015\-_/(),.:;!?'\"&]", " ", s)  # 标点（含 en-dash）转空格
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── F11 合并闸门（判据与校准数据见 .trae/documents/待补领域与新分类方案.md §5.4）──
# wikiEn/nameEn/alias 都是"文章标题"而非概念身份：历史上 35 次按 wikiEn 的跨 id 自动合并
# 有 32 次是误并（91%），被吞掉的多是本该各收一条的代际/地域变体。
# 因此非 id 键命中时，只有"同一事件的不同叫法"证据充分才自动合并，否则保留两条并记入 conflicts。
MAX_MERGE_YEAR_GAP = 3
MIN_DESC_SIM = 0.13
# 同一著作/人物的不同贡献：年份相同、描述高度相似，数值闸门拦不住，只能名单排除
BOOK_KEYS = {"almagest", "horologium oscillatorium", "georges cuvier"}
# L3 裁决：闸门保守拦下、经人工确认确为"同一事件的不同叫法"的一对，强制合并
FORCE_MERGE = {
    frozenset(("faience", "egyptian_faience")),        # 釉砂 / 费昂斯 = faience 同一材料
    frozenset(("game_theory", "game_theory_founding")),  # 同一部《博弈论与经济行为》
}


def _cjk_bigrams(s):
    s = "".join(ch for ch in (s or "") if "一" <= ch <= "鿿")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def desc_sim(a, b):
    ga, gb = _cjk_bigrams(a), _cjk_bigrams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def auto_merge_ok(a, b, reason):
    """闸门：返回 (是否允许自动合并, 拒绝原因)。id 命中必须合并，否则产出重复 id。"""
    if reason == "id":
        return True, ""
    w = norm_title(a.get("wikiEn") or "")
    if w and w in BOOK_KEYS:
        return False, "book_or_person_title"
    gap = abs((a.get("year") or 0) - (b.get("year") or 0))
    if gap > MAX_MERGE_YEAR_GAP:
        return False, f"year_gap_{gap}"
    if (a.get("name") or "") and a.get("name") == b.get("name"):
        return True, ""
    if desc_sim(a.get("desc"), b.get("desc")) >= MIN_DESC_SIM:
        return True, ""
    return False, "no_name_or_desc_evidence"


# L3 裁决：以下 id 对虽被机械键匹配，但实为不同概念/不同代，强制拆为独立条目
FORCE_SPLIT = {
    frozenset(p) for p in [
        ("ssl", "http"),                              # HTTPS 别名碰撞；安全层 ≠ HTTP
        ("twitter", "weibo"),                          # 共同别名“微博客”；两个平台
        ("nfc", "apple_pay"),                          # 共同别名“NFC支付”；技术 ≠ 服务
        ("smart_speaker", "voice_assistant"),          # 共同别名“小度”；硬件 ≠ 软件服务
        ("gas_turbine", "gas_turbine_ship"),           # 原动机 ≠ 舰船平台
        ("insulin", "recombinant_insulin"),            # 动物胰岛素 ≠ 重组人胰岛素（代际）
        ("integrated_development_environment", "ide_ata"),  # 缩写 IDE 撞车：开发环境 ≠ 硬盘接口
        ("nuclear_marine_propulsion", "nuclear_submarine"),  # 动力系统 ≠ 舰艇平台
        ("natural_gas_salt", "natural_gas_distribution"),    # 古代火井利用 ≠ 近代管网
        ("proto_porcelain", "porcelain"),              # 原始瓷 ≠ 成熟瓷（代际）
        ("ct_precursor", "ct_scanner"),                # CT 理论前身 ≠ CT 扫描仪（代际）
        ("ptolemaic_astronomy", "ptolemy_trigonometry"),   # 地心天文模型 ≠ 三角学弦表（同书两成果）
        ("marine_clock_early", "huygens_centrifugal_force"),  # 航海钟应用 ≠ 离心力理论
        ("cuvier_paleontology_catastrophism", "cuvier_comparative_anatomy"),  # 灾变论 ≠ 比较解剖学
        ("newtonian_mechanics", "inverse_square_gravity"),  # 力学体系 ≠ 万有引力定律（独立知识节点）
    ]
}

# L3 拆分后的修补（wikiEn 置空 + 关系连线），key=id
PATCH = {
    "gas_turbine_ship": {"wikiEn": "", "add_related": ["gas_turbine"]},
    "recombinant_insulin": {"wikiEn": "", "add_prereqs": ["insulin"]},
    "natural_gas_salt": {"wikiEn": "", "add_related": ["natural_gas_distribution"]},
    "ct_precursor": {"wikiEn": "", "add_related": ["x_ray"]},
    "ct_scanner": {"add_prereqs": ["ct_precursor"]},
    "ssl": {"add_related": ["http"]},
    "twitter": {"add_related": ["weibo"]},
    "weibo": {"add_related": ["twitter"]},
    "nfc": {"add_related": ["apple_pay"]},
    "apple_pay": {"add_related": ["nfc"]},
    "smart_speaker": {"add_related": ["voice_assistant"]},
    "voice_assistant": {"add_related": ["smart_speaker"]},
    "nuclear_marine_propulsion": {"add_related": ["nuclear_submarine"]},
    "nuclear_submarine": {"add_related": ["nuclear_marine_propulsion"]},
    "lunar_calendar": {"add_related": ["calendar"]},
    "stonehenge": {"add_related": ["stone_circle"]},
    "lacquerware": {"add_prereqs": ["lacquer"]},
    "camshaft": {"add_prereqs": ["cam_mechanism"]},
    "wagonway": {"add_prereqs": ["diolkos"]},
    "modern_sewer": {"add_prereqs": ["sewerage_system"]},
    "teletype_model_33": {"add_prereqs": ["teleprinter"]},
    "wikipedia": {"add_prereqs": ["wiki"]},
    "digital_wallet": {"add_prereqs": ["digicash"]},
    "grid_plan": {"add_related": ["planned_city"]},
    # 知识包新冲突（同书/同人多成果，拆分后互链）
    "ptolemy_trigonometry": {"add_related": ["ptolemaic_astronomy"]},
    "ptolemaic_astronomy": {"add_related": ["ptolemy_trigonometry"]},
    "huygens_centrifugal_force": {"add_related": ["marine_clock_early", "pendulum_clock"]},
    "cuvier_comparative_anatomy": {"add_related": ["cuvier_paleontology_catastrophism"]},
    "cuvier_paleontology_catastrophism": {"add_related": ["cuvier_comparative_anatomy"]},
    "inverse_square_gravity": {"add_prereqs": ["newtonian_mechanics"]},
    "hafting": {"set_name": "装柄术"},
    "bolas": {"set_name": "投石绊索"},
    "silk_throwing_mill": {"set_name": "水力捻丝机"},
    "gas_mantle": {"set_name": "稀土白炽纱罩"},
    "mannesmann_piercing": {"set_name": "斜轧穿孔法"},
    "linde_air_liquefaction": {"set_name": "空气液化精馏"},
    "turbinia": {"set_name": "特宾尼亚号轮机船"},
    "birkeland_eyde_process": {"set_name": "电弧固氮制硝酸法"},
    "fourcault_process": {"set_name": "垂直引上平板玻璃法"},
    "continuous_strip_mill": {"set_name": "带钢热连轧机"},
    "whirlwind": {"set_name": "旋风一号计算机"},
    "sage_system": {"set_name": "赛奇防空指挥系统"},
    "sabre_system": {"set_name": "萨布机票订票系统"},
    "os_360": {"set_name": "OS/360 批处理操作系统"},
    "ims_database": {"set_name": "IMS 层次数据库管理系统"},
    "altair_8800": {"set_name": "牵牛星 8800 微型计算机"},
    "osiris_rex": {"set_name": "奥西里斯-雷克斯采样探测器"},
    "embodied_ai": {"set_name": "具身智能体"},
    "warded_lock": {"set_name": "障片锁"},              # N-01 D2 批次留空中文名
    # L3 同名裁决：research 条目自带 name，set_name（仅填空）不生效，用 rename 强制消歧
    "pike": {"rename": "长枪"},                        # 与 spear(长矛) 同名
    "crank_handle": {"rename": "曲柄摇柄"},            # 与 crank(曲柄) 同名
    "sternpost_rudder": {"rename": "尾柱舵"},          # 与 stern_rudder(船尾舵) 同名
    "abel_summation": {"rename": "分部求和法（阿贝尔变换）"},  # 与 abel_summation_formula 同名，实为两条不同成果
    # L3 年份与标题裁决（方案 §5.2 / §6：era 由 year 派生，边界争议年按考古证据定值）
    "plow": {"set_year": -4000},
    "pottery_wheel": {"set_year": -4000},
    "beer": {"set_year": -4000},
    "impetus_theory": {"set_wikiEn": "Theory of impetus"},
    # 准入闸门查出的 5 条"标题差一点"：经检索改挂真实条目标题；确无独立条目的两条置空
    # （旧标题保留进 aliases 供追溯），置空者不再被闸门隔离。
    "wire_recorder": {"wikiEn": "Wire recording"},
    "niobium_tin": {"wikiEn": "Niobium–tin"},
    "von_neumann_quantum_foundations": {"wikiEn": "Mathematical Foundations of Quantum Mechanics"},
    "auger_tlp": {"wikiEn": ""},
    "li_yorke_chaos": {"wikiEn": ""},
    "superphosphate_fertilizer": {"set_wikiEn": "Superphosphate"},
    "mathematical_induction": {"set_desc": "由 n 成立推出 n+1 成立从而穷尽全体自然数的证明方法。"},
    "electromechanical_relay": {"set_desc": "以小电流吸合触点控制大电流的电磁开关，兼作电报中继与早期逻辑元件。"},
    "riemann_hypothesis": {"set_desc": "猜测黎曼 ζ 函数非平凡零点全落在临界线上，牵动素数分布，列为千禧难题。"},
    "public_key_cryptography": {"set_desc": "公钥加密私钥解密，免去秘密传递密钥的难题，支撑 HTTPS 与数字签名。"},
    "lempel_ziv_compression": {"set_desc": "以已见内容建字典、用指针替换重复串的通用压缩族，ZIP 与 GIF 承其衣钵。"},
    "b2fh_nucleosynthesis": {"add_prereqs": ["bethe_stellar_nucleosynthesis"]},
    "bethe_stellar_nucleosynthesis": {"add_related": ["b2fh_nucleosynthesis"]},
    "buffon_natural_history": {"add_related": ["pliny_natural_history"]},
    "pliny_natural_history": {"add_related": ["buffon_natural_history"]},
    "streptomycin": {"remove_related": ["tuberculosis"], "remove_prereqs": ["penicillin"]},
    # 知识包反向 prereq 修正（晚出条不能作前置；同代互启改 related）
    "pythagorean_theorem": {"remove_prereqs": ["shulba_sutras"], "add_related": ["shulba_sutras"]},
    "platonic_solids": {"remove_prereqs": ["geometry_deductive"], "add_related": ["geometry_deductive"]},
    "eudoxus_proportion_theory": {"remove_prereqs": ["geometry_deductive"], "add_related": ["geometry_deductive"]},
    "diophantine_equations": {"remove_prereqs": ["algebra"]},
    "merkle_puzzles": {"remove_prereqs": ["des"]},
    "diffie_hellman": {"remove_prereqs": ["des"]},
    "hopfield_network": {"remove_prereqs": ["backpropagation"], "add_related": ["backpropagation"]},
    # 通称条目并入后代应用条后，反向（更晚的）prereq 无效，清理
    "map": {"remove_prereqs": ["clay_tablet"]},
    "ink": {"remove_prereqs": ["movable_type_printing"]},
    "bellows": {"remove_prereqs": ["blast_furnace", "water_wheel"]},
    "force_pump": {"remove_prereqs": ["crankshaft"]},
    "finery_forge": {"remove_prereqs": ["blast_furnace"]},
    "clock_tower": {"remove_prereqs": ["mechanical_clock"]},
    "proto_porcelain": {"wikiEn": "", "add_related": ["porcelain"]},
    "porcelain": {"add_prereqs": ["proto_porcelain"]},
    "coke_fuel": {"remove_prereqs": ["blast_furnace"]},
    "cannon": {"remove_prereqs": ["blast_furnace"]},
    "jacobs_staff": {"remove_prereqs": ["mariners_astrolabe"]},
    "screw_cutting_lathe": {"remove_prereqs": ["cylinder_boring_machine"]},
    "blood_transfusion": {"remove_prereqs": ["aseptic_surgery"]},
    "telephone_exchange": {"remove_prereqs": ["pulse_code_modulation"]},
    "halftone": {"remove_prereqs": ["kodak_camera"]},
    "cesarean_section": {"remove_prereqs": ["aseptic_surgery"]},
    "positron_imaging": {"remove_prereqs": ["gamma_camera"]},
    "gene_therapy": {"remove_prereqs": ["human_genome_project"]},
}

# id 撞车预修复：(批次, 原id) -> 新id（同包内引用同步重写）
PRE_ID_FIX = {
    ("14-info-network", "mosaic"): "mosaic_browser",  # NCSA Mosaic 浏览器 ≠ 古代镶嵌工艺
}

# ── 8 领域重分类 ──────────────────────────────────────────────
# 批次默认领域：21 物理包、22 化学+天地包全部入物理科学
BATCH_CATEGORY = {"21": "physical_science", "22": "physical_science"}

# id 级领域覆盖（旧包知识节点 + 20/23 包逐条归类）
CATEGORY_OVERRIDE = {
    # —— 旧 01-19 包：数学·逻辑 ——
    "zero": "math_logic", "hindu_numerals": "math_logic",
    "aristotelian_logic": "math_logic", "shulba_sutras": "math_logic",
    "geometry_deductive": "math_logic", "algebra": "math_logic",
    "symbolic_algebra": "math_logic", "analytic_geometry": "math_logic",
    "projective_geometry": "math_logic", "probability_theory": "math_logic",
    "calculus": "math_logic", "boolean_algebra": "math_logic",
    "information_theory": "math_logic", "fuzzy_logic": "math_logic",
    # —— 旧包：物理科学（物理/化学/天文地学理论） ——
    "camera_obscura": "physical_science", "archimedes_statics": "physical_science",
    "impetus_theory": "physical_science", "book_of_optics": "physical_science",
    "heliocentric_model": "physical_science", "keplers_laws": "physical_science",
    "snells_law": "physical_science", "galilean_kinematics": "physical_science",
    "boyles_law": "physical_science", "hookes_law": "physical_science",
    "pascal_law": "physical_science", "wave_theory_light": "physical_science",
    "newtonian_mechanics": "physical_science", "atomic_theory": "physical_science",
    "conservation_of_energy": "physical_science", "maxwell_equations": "physical_science",
    "periodic_table": "physical_science", "steno_stratigraphy": "physical_science",
    "x_ray_crystallography": "physical_science", "equatorium": "physical_science",
    "calendar": "physical_science", "lunar_calendar": "physical_science",
    "julian_calendar": "physical_science", "gregorian_calendar": "physical_science",
    "maya_calendar": "physical_science",
    # —— 旧包：生命科学理论归位 ——
    "cell_theory": "life_medicine", "evolution_natural_selection": "life_medicine",
    "germ_theory": "life_medicine",
    # —— 旧包：社会·生活（制度/货币/知识制度） ——
    "law_code": "society", "patent_system": "society", "coinage": "society",
    "shell_money": "society", "paper_money": "society",
    "double_entry_bookkeeping": "society", "medieval_university": "society",
    "scientific_journal": "society",
    # —— 20 包：纯数学/统计/运筹/可计算性 → 数学·逻辑 ——
    **{k: "math_logic" for k in [
        "egyptian_rhind_papyrus", "pythagorean_theorem", "irrational_numbers",
        "zeno_paradoxes", "platonic_solids", "eudoxus_proportion_theory",
        "golden_ratio", "herons_formula", "diophantine_equations",
        "liu_hui_circle_cutting", "chinese_remainder_theorem", "zu_chongzhi_pi",
        "khayyam_cubic_equations", "fibonacci_sequence", "qin_jiushao_treatise",
        "tusi_trigonometry", "ptolemy_trigonometry", "madhava_infinite_series",
        "cavalieri_principle", "fermat_last_theorem", "newton_generalized_binomial",
        "fundamental_theorem_of_calculus", "leibniz_binary", "newton_iterative_method",
        "bernoulli_law_large_numbers", "taylor_series", "demoivre_normal_curve",
        "seven_bridges_graph_theory", "calculus_of_variations", "eulers_identity",
        "bayes_theorem", "laplace_transform", "lagrange_multipliers",
        "gauss_least_squares", "monge_descriptive_geometry",
        "gauss_fundamental_theorem_algebra", "gauss_normal_error_theory",
        "central_limit_theorem", "bolzano_intermediate_value", "fourier_analysis",
        "abel_impossibility_quintic", "lobachevsky_non_euclidean", "galois_theory",
        "hamilton_quaternions", "riemann_geometry", "riemann_integral",
        "cayley_matrix_algebra", "weierstrass_epsilon_delta", "dedekind_cuts",
        "cantor_set_theory", "frege_begriffsschrift", "peano_axioms",
        "peano_space_filling_curve", "poincare_topology", "hilbert_program",
        "russell_paradox", "lebesgue_integration", "markov_chains", "zermelo_zfc",
        "godel_incompleteness", "tarski_truth_theory", "church_lambda_calculus",
        "turing_machine", "game_theory", "nash_equilibrium", "category_theory",
        "shannon_sampling_theorem", "lorenz_chaos", "kolmogorov_complexity",
        "cook_levin_np_completeness", "appel_haken_four_color",
        "black_scholes_formula", "wiles_fermat_proof", "perelman_poincare_conjecture",
        "finite_element_method", "operations_research", "mandelbrot_fractal",
        "watts_strogatz_small_world", "barabasi_scale_free_network",
    ]},
    # 20 包中的物理原理
    "fermat_principle_least_time": "physical_science",
    # —— 23 包：经济学/心理学/社会学/管理/语言/系统 → 社会·生活 ——
    **{k: "society" for k in [
        "smith_wealth_of_nations", "malthus_population", "ricardo_comparative_advantage",
        "marx_das_kapital", "marginal_utility_revolution", "wundt_experimental_psychology",
        "james_principles_psychology", "marshall_neoclassical_economics",
        "durkheim_sociology", "freud_psychoanalysis", "taylor_scientific_management",
        "gestalt_psychology", "watson_behaviorism", "weber_bureaucracy",
        "kuznets_national_income", "keynes_general_theory",
        "schumpeter_creative_destruction", "maslow_hierarchy_needs",
        "arrow_impossibility_theory", "bowlby_attachment_theory",
        "arrow_debreu_model", "simon_bounded_rationality", "miller_magical_number_seven",
        "solow_growth_model", "sapir_whorf_relativity", "chomsky_generative_grammar",
        "festinger_cognitive_dissonance", "coase_theorem", "becker_human_capital",
        "neisser_cognitive_psychology", "bertalanffy_general_systems",
        "tversky_kahneman_heuristics", "prospect_theory", "santa_fe_complex_systems",
        "pavlov_conditioned_reflex",
    ]},
    # 23 包跨界条目
    "gaia_hypothesis": "life_medicine",
}


def apply_category(rec, batch):
    """知识节点迁移到新领域；器物条目不动。"""
    rid = rec["id"]
    if rid in CATEGORY_OVERRIDE:
        rec["category"] = CATEGORY_OVERRIDE[rid]
    elif batch[:2] in BATCH_CATEGORY:
        rec["category"] = BATCH_CATEGORY[batch[:2]]
    elif batch[:2] == "23" and rec.get("category") == "information":
        rec["category"] = "society"



def merge_records(a: dict, b: dict, reason: str, sources: list) -> dict:
    """两个同概念记录合并，a 为先到（更早批次）。"""
    m = dict(a)
    # 中文名取非空，优先 a
    if not m.get("name") and b.get("name"):
        m["name"] = b["name"]
    # nameEn/wikiEn 取非空且较短的规范名（a 优先）
    for k in ("nameEn", "wikiEn"):
        if not m.get(k) and b.get(k):
            m[k] = b[k]
    # 别名并集（含被合并条目的主名，便于追溯）
    alias = set(m.get("aliases") or [])
    alias.update(b.get("aliases") or [])
    for r in (b,):
        if r.get("nameEn") and r["nameEn"] != m.get("nameEn"):
            alias.add(r["nameEn"])
        if r.get("name") and r["name"] != m.get("name"):
            alias.add(r["name"])
        if r.get("wikiEn") and r["wikiEn"] != m.get("wikiEn"):
            alias.add(r["wikiEn"])
    m["aliases"] = sorted(x for x in alias if x)
    # 关系并集（剔除指向合并双方自身的引用）
    self_ids = {a.get("id"), b.get("id")}
    m["prereqs"] = sorted((set(m.get("prereqs") or []) | set(b.get("prereqs") or [])) - self_ids)
    m["related"] = sorted((set(m.get("related") or []) | set(b.get("related") or [])) - self_ids)
    # 描述只在主记录缺失时取 b。旧写法"取更长"会把 b 的事件文本挂到 a 的年份上，
    # 造出 year 与 desc 自相矛盾的条目（历史污染 17 条，见方案 §5.4 第 4 条）。
    if not (m.get("desc") or "").strip():
        m["desc"] = b.get("desc") or ""
    # importance 取更高优先级（数值更小）
    m["importance"] = min(m.get("importance", 3), b.get("importance", 3))
    # year/era/category 保留先到（以注册表为准的修正留给 validate 阶段）
    m["_mergedFrom"] = list(dict.fromkeys(sources + [b["id"]]))
    m["_mergeReason"] = reason
    return m


def main():
    wiki_cache = load_wiki_cache()   # 键=原标题（勿规范化：en-dash 会塌陷成同键）
    files = sorted(glob.glob(os.path.join(RESEARCH_DIR, "*.json")))
    records = []
    parse_errors = []
    for fp in files:
        batch = os.path.splitext(os.path.basename(fp))[0]
        with open(fp, encoding="utf-8") as f:
            try:
                arr = json.load(f)
            except Exception as e:
                parse_errors.append({"file": batch, "error": str(e)})
                continue
        for rec in arr:
            rec["_batch"] = batch
            new_id = PRE_ID_FIX.get((batch, rec["id"]))
            if new_id:
                old_id = rec["id"]
                rec["id"] = new_id
                for k in ("prereqs", "related"):  # 同包内引用同步重写
                    rec[k] = [new_id if x == old_id else x for x in (rec.get(k) or [])]
            apply_category(rec, batch)
            records.append(rec)

    total_in = len(records)

    # 注册表核心 id：合并时核心条目必须作为最终 id/时代归属
    with open(os.path.join(ROOT, "data", "core-ids.json"), encoding="utf-8") as f:
        CORE = {c["id"] for c in json.load(f)["coreIds"]}
    ID_REDIRECT = {}  # 被并入核心条目的非核心旧 id -> 核心 id

    # 索引：id -> 合并记录下标；其余键 -> id
    by_id = {}
    by_nameen = {}
    by_alias = {}
    by_wikien = {}
    merged = []
    auto_merges = []
    conflicts = []  # 疑似但无法自动合并

    def find_existing(rec):
        rid = rec["id"]
        if rid in by_id:
            return by_id[rid], "id"
        w = norm_title(rec.get("wikiEn", ""))
        if w and w in by_wikien:
            return by_wikien[w], "wikiEn"
        n = norm_title(rec.get("nameEn", ""))
        if n and n in by_nameen:
            return by_nameen[n], "nameEn"
        for al in rec.get("aliases") or []:
            na = norm_title(al)
            if na and na in by_alias:
                return by_alias[na], "alias"
        # 反向：现有记录的 alias 是否命中本条的 nameEn/wikiEn
        if n:
            if n in by_alias:
                return by_alias[n], "reverse-alias"
        return None, None

    for rec in records:
        idx, reason = find_existing(rec)

        def register(new_rec):
            new_rec.setdefault("_mergedFrom", [new_rec["id"]])
            merged.append(new_rec)
            i = len(merged) - 1
            by_id[new_rec["id"]] = i
            nk = norm_title(new_rec.get("nameEn", ""))
            if nk:
                by_nameen.setdefault(nk, i)
            wk = norm_title(new_rec.get("wikiEn", ""))
            if wk:
                by_wikien.setdefault(wk, i)
            for al in new_rec.get("aliases") or []:
                na = norm_title(al)
                if na:
                    by_alias.setdefault(na, i)

        if idx is not None:
            old = merged[idx]
            if frozenset((old["id"], rec["id"])) in FORCE_SPLIT:
                register(rec)  # L3 裁决：强制保留为独立条目
                continue
            # F11 闸门：证据不足则不自动合并，两条都保留并记入冲突供 L3 人工裁决
            forced = frozenset((old["id"], rec["id"])) in FORCE_MERGE
            gate_ok, gate_why = (True, "force_merge") if forced else auto_merge_ok(old, rec, reason)
            if not gate_ok:
                conflicts.append({
                    "reason": reason, "gate_reject": gate_why,
                    "kept": {"id": old["id"], "era": old["era"], "year": old.get("year"),
                             "nameEn": old["nameEn"], "wikiEn": old.get("wikiEn")},
                    "dropped": {"id": rec["id"], "era": rec["era"], "year": rec.get("year"),
                                "nameEn": rec["nameEn"], "wikiEn": rec.get("wikiEn"),
                                "batch": rec["_batch"]},
                })
                register(rec)
                continue
            # 同键匹配但 era 跨度大 → 可能是代际误并，保留独立并记录冲突
            if old["era"] != rec["era"] and reason in ("nameEn", "alias", "reverse-alias"):
                conflicts.append({
                    "reason": reason,
                    "kept": {"id": old["id"], "era": old["era"], "nameEn": old["nameEn"], "wikiEn": old.get("wikiEn")},
                    "dropped": {"id": rec["id"], "era": rec["era"], "nameEn": rec["nameEn"], "wikiEn": rec.get("wikiEn"), "batch": rec["_batch"]},
                })
                register(rec)
                continue
            if rec["id"] in CORE and old["id"] not in CORE:
                # 核心条目作为基底（最终 id/year/era/category 取核心条）
                ID_REDIRECT[old["id"]] = rec["id"]
                base, other = rec, old
                by_id[rec["id"]] = idx
            else:
                base, other = old, rec
            merged[idx] = merge_records(base, other, reason, old.get("_mergedFrom", [old["id"]]))
            for k in ("nameEn", "wikiEn"):
                nk = norm_title(merged[idx].get(k, ""))
                if nk:
                    (by_nameen if k == "nameEn" else by_wikien).setdefault(nk, idx)
            for al in merged[idx].get("aliases") or []:
                na = norm_title(al)
                if na:
                    by_alias.setdefault(na, idx)
            auto_merges.append({"into": merged[idx]["id"], "from": other["id"], "reason": reason, "batch": rec["_batch"]})
            ID_REDIRECT[other["id"]] = merged[idx]["id"]
        else:
            register(rec)

    # 全局重写被并入核心条目的旧 id 引用（须先于 PATCH 清理，保证引用名已是最终 id）
    if ID_REDIRECT:
        for r in merged:
            for k in ("prereqs", "related"):
                vals = [ID_REDIRECT.get(x, x) for x in (r.get(k) or [])]
                vals = [x for x in dict.fromkeys(vals) if x != r["id"]]
                r[k] = vals

    # 应用 L3 拆分修补
    for r in merged:
        p = PATCH.get(r["id"])
        if not p:
            continue
        if "set_desc" in p:      # L3 精简：desc 超 40 字的批次条目
            r["desc"] = p["set_desc"]
        if "set_name" in p and not (r.get("name") or "").strip():
            r["name"] = p["set_name"]
        if "rename" in p:
            r["name"] = p["rename"]
        if "set_year" in p:
            r["year"] = int(p["set_year"])
        if "set_wikiEn" in p and not (r.get("wikiEn") or "").strip():
            r["wikiEn"] = p["set_wikiEn"]
        if "wikiEn" in p and r.get("wikiEn"):
            r.setdefault("aliases", [])
            if r["wikiEn"] not in r["aliases"]:
                r["aliases"].append(r["wikiEn"])
            r["wikiEn"] = p["wikiEn"]
        if p.get("add_related"):
            r["related"] = sorted(set((r.get("related") or []) + p["add_related"]))
        if p.get("remove_related"):
            r["related"] = sorted(set(r.get("related") or []) - set(p["remove_related"]))
        if p.get("remove_prereqs"):
            r["prereqs"] = sorted(set(r.get("prereqs") or []) - set(p["remove_prereqs"]))
        if p.get("add_prereqs"):
            r["prereqs"] = sorted(set((r.get("prereqs") or []) + p["add_prereqs"]))

    # 关系数量上限 4：超出时优先保留年代更早、重要度更高的目标
    meta = {r["id"]: r for r in merged}
    for r in merged:
        for k in ("prereqs", "related"):
            vals = r.get(k) or []
            if len(vals) > 4:
                vals.sort(key=lambda x: (meta.get(x, {}).get("year", 99999),
                                         meta.get(x, {}).get("importance", 5)))
                r[k] = vals[:4]

    # wikiEn 重复但未被合并（理论上不应有，兜底报告）
    wikien_dupes = defaultdict(list)
    for r in merged:
        wk = norm_title(r.get("wikiEn", ""))
        if wk:
            wikien_dupes[wk].append(r["id"])
    wiki_conflicts = [{"wikiEnNorm": k, "ids": v} for k, v in wikien_dupes.items() if len(v) > 1]

    # 输出（去掉内部字段前保留溯源到报告，正式数据不含 _batch）
    out = []
    for r in merged:
        rr = {k: r.get(k) for k in REQUIRED_FIELDS}
        rr["year_note"] = rr.get("year_note") or ""
        rr["aliases"] = rr["aliases"] or []
        rr["prereqs"] = rr["prereqs"] or []
        rr["related"] = rr["related"] or []
        out.append(rr)
    kept, quarantined, unverified = [], [], []
    for r in out:
        raw = (r.get("wikiEn") or "").strip()
        # 缓存键是**原标题**（勿规范化：en-dash/大小写会塌陷成同键，见 verify_wikien 注释）
        v = wiki_cache.get(raw)
        w = raw
        if v is None or not w:
            if w:
                unverified.append(r["id"])
            kept.append(r)
        elif v.get("ok"):
            kept.append(r)
        else:
            quarantined.append({"id": r["id"], "name": r.get("name"), "wikiEn": r.get("wikiEn"),
                                "reason": "维基条目不存在（准入闸门）"})
    out = kept
    out.sort(key=lambda x: (x["year"], x["id"]))
    # 剔除指向"最终不存在的 id"的引用：净增批次常引用后来被闸门隔离、或被并入他条的 id，
    # 留着就是悬空边。剔除动作要报数，否则静默丢边无人知晓。
    final_ids = {r["id"] for r in out}
    pruned = []
    for r in out:
        for k in ("prereqs", "related"):
            keep = [x for x in (r.get(k) or []) if x in final_ids]
            lost = [x for x in (r.get(k) or []) if x not in final_ids]
            if lost:
                pruned.append({"id": r["id"], "field": k, "dropped": lost})
            r[k] = keep

    with open(QUARANTINE, "w", encoding="utf-8") as f:
        json.dump({"quarantined": quarantined, "unverified_titles_passed_with_warning": unverified},
                  f, ensure_ascii=False, indent=1)
    if quarantined or unverified:
        print(f"准入闸门：隔离 {len(quarantined)} 条（维基查不到），未核验放行 {len(unverified)} 条")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    report = {
        "files": [os.path.basename(x) for x in files],
        "parseErrors": parse_errors,
        "totalRaw": total_in,
        "totalMerged": len(out),
        "autoMergedCount": len(auto_merges),
        "autoMerges": auto_merges,
        "prunedDanglingRefs": pruned,
        "eraSpanConflicts": conflicts,
        "wikiKeyConflicts": wiki_conflicts,
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"raw={total_in} merged={len(out)} auto_merges={len(auto_merges)} "
          f"era_conflicts={len(conflicts)} wiki_conflicts={len(wiki_conflicts)} parse_errors={len(parse_errors)}")


if __name__ == "__main__":
    main()
