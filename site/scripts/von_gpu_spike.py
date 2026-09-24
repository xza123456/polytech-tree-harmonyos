# -*- coding: utf-8 -*-
"""
Von (本地 System One) GPU 决策 + 延迟 spike
RTX 4090 / CUDA / bf16。首次运行会从 HuggingFace 下载 wfzyx/von-1.0 (~1.5GB)。

用法:
  python scripts/von_gpu_spike.py [轮次]
强制设备可用环境变量: VON_DEVICE=cuda|cpu
"""
import os
import sys
import time
import statistics

import torch
import von
from von.engine import VonEngine

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 200

# 一个 MOBA/动作对战风格的“战场状态”
STATE = {
    "self": {"hp": 0.32, "mana": 0.55, "ultimate_ready": True, "dash_ready": False},
    "enemy_closest": {"hp": 0.61, "distance": 320, "cc_available": True},
    "enemy_count_visible": 3,
    "ally_count_near": 1,
    "under_turret": False,
    "event": "enemy jungler just appeared in river bush",
}

QUESTIONS = {
    # 战术决策：这一拍选哪个动作（离散候选，单次前向打分）
    "action": {
        "type": "choice",
        "instructions": "Given this real-time combat state, which single action should the AI take right now?",
        "criteria": {
            "engage": "我方有把握击杀或留人，人数/技能占优，主动开战",
            "retreat": "血量低或敌众我寡，立即后撤到安全位置",
            "poke": "距离允许但不宜all-in，消耗/试探走位",
            "use_ultimate": "对方关键目标在大招范围内，立即交大招",
            "rotate_objective": "放弃对线，转去打龙/推塔/支援",
        },
    },
    # 是/否：闪现/位移这种高价值资源现在该不该交
    "should_burn_escape": {
        "type": "noul",
        "instructions": "Is there immediate lethal danger requiring an emergency escape summoner spell right now?",
    },
    # 评分：当前威胁等级
    "threat": {
        "type": "score",
        "instructions": "Rate the immediate threat level to this hero.",
        "criteria": [
            "0 安全：无敌人威胁",
            "1 低：可控的小摩擦",
            "2 中：需要谨慎走位",
            "3 高：很可能被开/被秒",
            "4 致命：不立刻撤退或交位移就死",
        ],
    },
}


def main():
    print("=" * 64)
    print("Von 本地 System One · GPU spike")
    print("=" * 64)

    # 显式构建引擎，打印真实设备/dtype
    eng = VonEngine(backend_name="von-1.0", device=os.environ.get("VON_DEVICE"))
    backend = eng.backend

    t0 = time.time()
    model, tok = backend._get_model_and_tok()  # 首次触发权重下载与加载
    load_s = time.time() - t0
    dev = backend.device
    dtype = next(model.parameters()).dtype
    n_params = sum(p.numel() for p in model.parameters()) / 1e6

    print(f"模型        : {backend.model_id}")
    print(f"设备        : {dev}")
    if dev.type == "cuda":
        print(f"GPU         : {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info(0)
        print(f"精度 dtype  : {dtype}")
        print(f"参数量      : {n_params:.0f}M")
        print(f"显存占用    : {(total-free)/1024**3:.2f} GB / {total/1024**3:.1f} GB (整卡当前)")
        print(f"模型权重显存: 约 {torch.cuda.memory_allocated(0)/1024**3:.2f} GB")
    print(f"加载+下载耗时: {load_s:.1f}s\n")

    # 功能正确性：打印一次决策
    print("-" * 64)
    print("战场决策示例:")
    r = eng.evaluate(state=STATE, questions=QUESTIONS)
    a = r.answers
    print(f"  action            = {a['action'].choice}  (conf={a['action'].confidence})")
    print(f"    probs = {a['action'].probabilities}")
    print(f"  should_burn_escape= {a['noul' if False else 'should_burn_escape'].noul}")
    print(f"  threat score      = {a['threat'].score}  (conf={a['threat'].confidence})")

    # 预热（含 CUDA kernel 编译/缓存），不计入统计
    for _ in range(10):
        eng.evaluate(state=STATE, questions=QUESTIONS)
    if dev.type == "cuda":
        torch.cuda.synchronize()

    # 延迟测量：完整一次 system_one（3 个问题）
    def sync():
        if dev.type == "cuda":
            torch.cuda.synchronize()

    lat = []
    sync()
    for _ in range(ROUNDS):
        t = time.perf_counter()
        eng.evaluate(state=STATE, questions=QUESTIONS)
        sync()
        lat.append((time.perf_counter() - t) * 1000.0)

    lat.sort()

    def pct(p):
        return lat[min(len(lat) - 1, int(len(lat) * p))]

    print("\n" + "-" * 64)
    print(f"单次 system_one 延迟（含 3 个判断，n={ROUNDS}，已预热）")
    print(f"  mean = {statistics.mean(lat):8.2f} ms")
    print(f"  p50  = {pct(0.50):8.2f} ms")
    print(f"  p95  = {pct(0.95):8.2f} ms")
    print(f"  p99  = {pct(0.99):8.2f} ms")
    print(f"  min  = {lat[0]:8.2f} ms")
    print(f"  max  = {lat[-1]:8.2f} ms")
    print(f"  吞吐 ≈ {1000.0/statistics.mean(lat):8.1f} 决策/秒（每决策含3问）")
    if dev.type == "cuda":
        print(f"  峰值模型显存: {torch.cuda.max_memory_allocated(0)/1024**3:.2f} GB")


if __name__ == "__main__":
    main()
