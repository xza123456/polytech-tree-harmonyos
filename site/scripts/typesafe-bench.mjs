// TypeSafe (System One / Jev) 批量测速脚本
// 用法（项目根目录）：
//   node --env-file=.env scripts/typesafe-bench.mjs [条目数]
// 例： node --env-file=.env scripts/typesafe-bench.mjs 30
//
// 目的：测量真实批量评估的反应速度，对比不同并发策略。
// 只读数据、只发请求，不修改任何源文件。

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const API_URL = "https://api.typesafe.ai/v1/systemone";
const MODEL = "jev-latest";

const LIMIT = Number(process.argv[2]) || 0; // 0 = 全部
const CONCURRENCIES = [1, 5, 10]; // 1 = 纯串行
const DATA_FILE = join(__dirname, "..", "data", "research", "02-bronze-age.json");

const apiKey = process.env.TYPESAFE_API_KEY;
if (!apiKey || apiKey.includes("在此粘贴") || apiKey.includes("你的key")) {
  console.error("✗ 未配置有效的 TYPESAFE_API_KEY（检查 .env）。");
  process.exit(1);
}

// 每条技术评估 3 个问题（与数据集字段对齐）
function buildQuestions() {
  return {
    domain: {
      type: "choice",
      instructions: "Which technology domain does this concept belong to?",
      criteria: {
        materials: "材料-制造：金属、合金、工艺、器物",
        energy: "能源-动力：能量获取、燃料与动力",
        information: "信息-计算：信息记录、计算与通信",
        life: "生命-医学：生物、农业、医疗",
        transportation: "交通-探索：运输、航行、地理探索",
      },
    },
    importance: {
      type: "score",
      instructions: "How foundational is this invention to later technology? (1 = most foundational)",
      criteria: [
        "1 核心奠基：长期广泛影响多个文明与领域",
        "2 重要：影响一个时代或多个行业",
        "3 中等：区域性或单领域显著影响",
        "4 次要：有限范围的改进",
        "5 边缘：小众或很快被取代",
      ],
    },
    is_material: {
      type: "noul",
      instructions: "Is this concept primarily about a physical material or manufacturing process?",
    },
  };
}

function buildState(item) {
  return {
    name: item.nameEn ?? item.name,
    aliases: item.aliases ?? [],
    year: item.year,
    existing_category: item.category,
    description: item.desc,
  };
}

async function evaluateOne(item) {
  const body = { state: buildState(item), model: MODEL, questions: buildQuestions() };
  const t0 = performance.now();
  const res = await fetch(API_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  const ms = performance.now() - t0;
  return { ms, usage: data.usage ?? null, domain: data.answers?.domain?.choice };
}

// 受限并发池
async function runPool(items, concurrency) {
  const latencies = [];
  let inTok = 0,
    outTok = 0,
    errors = 0;
  let cursor = 0;
  const workers = Array.from({ length: concurrency }, async () => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) break;
      try {
        const r = await evaluateOne(items[i]);
        latencies.push(r.ms);
        if (r.usage) {
          inTok += r.usage.input_tokens ?? 0;
          outTok += r.usage.output_tokens ?? 0;
        }
      } catch (e) {
        errors++;
        console.error(`  [条目 ${items[i].id}] 失败: ${e.message}`);
      }
    }
  });
  await Promise.all(workers);
  return { latencies, inTok, outTok, errors };
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[idx];
}

function summarize(label, latencies, wallMs) {
  const s = [...latencies].sort((a, b) => a - b);
  const n = s.length;
  const avg = s.reduce((x, y) => x + y, 0) / (n || 1);
  return {
    label,
    n,
    wallMs,
    avg,
    p50: percentile(s, 50),
    p95: percentile(s, 95),
    min: s[0] ?? 0,
    max: s[n - 1] ?? 0,
    rps: n / (wallMs / 1000),
  };
}

function fmtRow(r) {
  const f = (x) => x.toFixed(0).padStart(6);
  return `  ${r.label.padEnd(14)} | n=${String(r.n).padStart(2)} | 总耗时 ${(r.wallMs / 1000).toFixed(2)}s | 平均 ${f(r.avg)}ms | P50 ${f(r.p50)}ms | P95 ${f(r.p95)}ms | 吞吐 ${r.rps.toFixed(2)} 条/秒`;
}

async function main() {
  const raw = JSON.parse(await readFile(DATA_FILE, "utf8"));
  let items = Array.isArray(raw) ? raw : [];
  if (LIMIT > 0) items = items.slice(0, LIMIT);
  const N = items.length;
  console.log(`数据源: 02-bronze-age.json，共 ${N} 条；每条 3 个问题；模型 ${MODEL}\n`);

  // 单独测一次冷启动首请求
  console.log("● 冷启动首请求…");
  const cold = await evaluateOne(items[0]);
  console.log(`  首请求延迟: ${cold.ms.toFixed(0)}ms\n`);

  const results = [];
  for (const c of CONCURRENCIES) {
    const label = c === 1 ? "串行(1)" : `并发(${c})`;
    console.log(`● ${label} 批量评估 ${N} 条…`);
    const t0 = performance.now();
    const { latencies, inTok, outTok, errors } = await runPool(items, c);
    const wall = performance.now() - t0;
    const r = summarize(label, latencies, wall);
    r.inTok = inTok;
    r.outTok = outTok;
    r.errors = errors;
    results.push(r);
    console.log(fmtRow(r));
    console.log(`    tokens: 输入 ${inTok}, 输出 ${outTok}；失败 ${errors}\n`);
  }

  console.log("──────────────── 汇总 ────────────────");
  results.forEach((r) => console.log(fmtRow(r)));
  const serial = results[0];
  const best = results.reduce((a, b) => (b.wallMs < a.wallMs ? b : a));
  if (serial && best !== serial) {
    console.log(`\n最快策略「${best.label.trim()}」相比串行提速 ${(serial.wallMs / best.wallMs).toFixed(1)}×`);
  }
}

main().catch((e) => {
  console.error("✗ 运行失败:", e);
  process.exit(1);
});
