// TypeSafe (System One / Jev) 连通性冒烟测试
// 用法（在项目根目录）：
//   node --env-file=.env scripts/typesafe-smoketest.mjs
//
// 前置：在 .env 中设置 TYPESAFE_API_KEY（获取：https://console.typesafe.ai/keys）
// 该脚本仅在 Node 端运行，不打包进前端，避免泄露密钥。

const API_URL = "https://api.typesafe.ai/v1/systemone";
const MODEL = "jev-latest";

function fail(message) {
  console.error(`\n✗ ${message}`);
  process.exit(1);
}

const apiKey = process.env.TYPESAFE_API_KEY;
if (!apiKey || apiKey.includes("在此粘贴") || apiKey.includes("你的key")) {
  fail(
    "未配置有效的 TYPESAFE_API_KEY。\n" +
      "  请在项目根目录 .env 中填入真实 key（https://console.typesafe.ai/keys），\n" +
      "  并用 node --env-file=.env scripts/typesafe-smoketest.mjs 运行。"
  );
}

// 用青铜时代数据集里的一条概念做最小判断
const payload = {
  state: "Bronze is an alloy of copper and tin, used for tools and weapons in the Bronze Age.",
  model: MODEL,
  questions: {
    // Noul：是/否概率（无独立 confidence）
    is_materials_metallurgy: {
      type: "noul",
      instructions: "Is this text about materials science or metallurgy?",
    },
    // Choice：在给定集合中选一个，返回各选项概率
    domain: {
      type: "choice",
      instructions: "Which technology domain does this concept belong to?",
      criteria: {
        materials: "材料-制造：金属、合金、工艺、器物",
        energy: "能源-动力：能量获取、转换与动力机械",
        information: "信息-计算：信息记录、计算与通信",
        life: "生命-医学：生物、农业、医疗健康",
        transportation: "交通-探索：运输工具、航行与地理探索",
      },
    },
    // Score：沿有序等级给出概率加权位置
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
  },
};

console.log(`→ POST ${API_URL}  (model=${MODEL})`);

try {
  const res = await fetch(API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (res.status === 401) {
    fail("401 Unauthorized：API Key 无效或已过期，请到 https://console.typesafe.ai/keys 检查。");
  }
  if (res.status === 429) {
    fail("429 Rate Limited：请求过于频繁或额度不足，请稍后再试。");
  }
  if (!res.ok) {
    const text = await res.text();
    fail(`请求失败 HTTP ${res.status} ${res.statusText}\n  ${text}`);
  }

  const data = await res.json();

  console.log("\n✓ 调用成功，结构化结果：\n");
  const a = data.answers ?? {};

  if (a.is_materials_metallurgy) {
    console.log(`  is_materials_metallurgy (noul) : P(yes) = ${a.is_materials_metallurgy.noul}`);
  }
  if (a.domain) {
    console.log(`  domain (choice)                 : ${a.domain.choice}  (confidence=${a.domain.confidence})`);
    console.log(`    probabilities = ${JSON.stringify(a.domain.probabilities)}`);
  }
  if (a.importance) {
    console.log(`  importance (score)              : ${a.importance.score}  (confidence=${a.importance.confidence})`);
    console.log(`    legend = ${JSON.stringify(a.importance.legend)}`);
  }
  if (data.usage) {
    console.log(`\n  usage: input=${data.usage.input_tokens} tokens, output=${data.usage.output_tokens} tokens`);
  }
  console.log("\n全部三种原语（Noul / Choice / Score）均正常返回，TypeSafe 已可用。");
} catch (err) {
  fail(`网络或运行时错误：${err?.message ?? err}`);
}
