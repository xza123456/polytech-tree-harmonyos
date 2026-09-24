# -*- coding: utf-8 -*-
"""
Von 延迟分解：单候选前向 / 单个Choice(5动作,一次batch) / 完整3问
验证“多候选是否被合并成单次批量前向”，给出实时对战真实口径。
"""
import os
import time
import statistics
import torch
from von.engine import VonEngine

eng = VonEngine(backend_name="von-1.0", device="cuda")
backend = eng.backend
model, tok = backend._get_model_and_tok()
dev = backend.device


def sync():
    torch.cuda.synchronize()


STATE = "self hp 32%, mana 55%, ultimate ready; nearest enemy hp 61% distance 320; enemies visible 3 allies 1; enemy jungler in river bush"
ACTIONS = {
    "engage": "we have kill pressure and advantage, start the fight",
    "retreat": "low hp or outnumbered, back to safety",
    "poke": "harass at range without committing",
    "use_ultimate": "key target inside ultimate range, cast now",
    "rotate_objective": "abandon lane, rotate to dragon/turret",
}


def encode(pairs):
    pre, hyp = zip(*pairs)
    return tok(list(pre), list(hyp), padding=True, truncation=True, max_length=512, return_tensors="pt").to(dev)


def bench(fn, rounds=200, warm=20):
    for _ in range(warm):
        fn()
    sync()
    out = []
    for _ in range(rounds):
        t = time.perf_counter()
        fn()
        sync()
        out.append((time.perf_counter() - t) * 1000)
    out.sort()
    return statistics.mean(out), out[len(out) // 2], out[int(len(out) * 0.95)]


# 1) 单个候选对的前向（最小粒度）
single = encode([(STATE, ACTIONS["engage"])])
def f_single():
    with torch.no_grad():
        model(**single).logits

# 2) 一个动作Choice：5个候选一次batch（这才是实战单决策）
five = encode([(STATE, h) for h in ACTIONS.values()])
def f_five():
    with torch.no_grad():
        model(**five).logits

# 3) SDK 的单个 choice 调用（对比是否等价于上面batch）
from von.types import Choice
q = Choice(instructions="which single action now?", criteria=ACTIONS)
def f_sdk_choice():
    backend.evaluate_choice("action", STATE, q)

# 4) SDK 完整 3 问
def f_full():
    eng.evaluate(state=STATE, questions={
        "action": {"type": "choice", "instructions": "which single action now?", "criteria": ACTIONS},
        "escape": {"type": "noul", "instructions": "Is there immediate lethal danger requiring flash now?"},
        "threat": {"type": "score", "instructions": "Rate threat level.",
                   "criteria": ["safe", "low", "medium", "high", "lethal"]},
    })

for name, fn in [
    ("单候选前向 (1 pair)", f_single),
    ("单个动作决策 Choice-5 (1次batch前向)", f_five),
    ("SDK choice(5) 调用", f_sdk_choice),
    ("完整 system_one (3问/12候选, SDK串行)", f_full),
]:
    mean, p50, p95 = bench(fn)
    print(f"{name:42s} mean {mean:6.2f}ms | p50 {p50:6.2f} | p95 {p95:6.2f}")

print(f"\n模型显存峰值: {torch.cuda.max_memory_allocated(0)/1024**3:.3f} GB")
print(f"batch形状 1pair={tuple(single['input_ids'].shape)}  5pair={tuple(five['input_ids'].shape)}")
