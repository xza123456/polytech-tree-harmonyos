// TypeSafe 延迟分解：区分网络(连接/TLS) 与 服务端(TTFB/推理) 耗时
// 用法: node --env-file=.env scripts/typesafe-latency.mjs [次数]
import { performance } from "node:perf_hooks";
import https from "node:https";

const HOST = "api.typesafe.ai";
const apiKey = process.env.TYPESAFE_API_KEY;
if (!apiKey || apiKey.includes("在此粘贴") || apiKey.includes("你的key")) {
  console.error("✗ 未配置 TYPESAFE_API_KEY");
  process.exit(1);
}
const ROUNDS = Number(process.argv[2]) || 8;

const body = JSON.stringify({
  state: "Bronze is an alloy of copper and tin.",
  model: "jev-latest",
  questions: { q: { type: "noul", instructions: "Is this about metallurgy?" } },
});

// 1) 纯网络：TCP + TLS 握手耗时（不发业务请求体到推理）
function measureConnect() {
  return new Promise((resolve, reject) => {
    const t0 = performance.now();
    const req = https.request(
      { host: HOST, port: 443, method: "HEAD", path: "/", servername: HOST },
      (res) => {
        res.resume();
        res.on("end", () => resolve(performance.now() - t0));
      }
    );
    req.on("error", () => resolve(performance.now() - t0)); // 即便 404/405，握手也已完成
    req.end();
  });
}

// 2) 业务请求：分解 TTFB/总耗时；可传入共享 agent 以复用连接
function measureApi(agent) {
  return new Promise((resolve, reject) => {
    const marks = {};
    const t0 = performance.now();
    const req = https.request(
      {
        host: HOST,
        method: "POST",
        path: "/v1/systemone",
        agent,
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        marks.ttfb = performance.now() - t0; // 收到响应头/首字节
        let chunks = 0;
        res.on("data", () => chunks++);
        res.on("end", () => {
          marks.total = performance.now() - t0;
          resolve({ status: res.statusCode, ...marks });
        });
      }
    );
    req.on("socket", (socket) => {
      socket.on("secureConnect", () => (marks.tls = performance.now() - t0));
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

const stats = (arr) => {
  const s = [...arr].sort((a, b) => a - b);
  const avg = arr.reduce((x, y) => x + y, 0) / arr.length;
  return {
    avg,
    min: s[0],
    p50: s[Math.floor(s.length * 0.5)],
    max: s[s.length - 1],
  };
};
const row = (name, st) =>
  `  ${name.padEnd(18)} 平均 ${st.avg.toFixed(0).padStart(5)}ms | 最小 ${st.min
    .toFixed(0)
    .padStart(5)} | P50 ${st.p50.toFixed(0).padStart(5)} | 最大 ${st.max.toFixed(0).padStart(5)}`;

async function main() {
  console.log(`目标: ${HOST} ；轮次 ${ROUNDS}\n`);

  console.log("● 纯网络建连（TCP+TLS，不推理）");
  const conn = [];
  for (let i = 0; i < ROUNDS; i++) conn.push(await measureConnect());
  const cs = stats(conn);
  console.log(row("TCP+TLS 建连", cs));

  console.log("\n● 完整 API 请求（新连接，每次重新握手）");
  const cold = { ttfb: [], total: [] };
  for (let i = 0; i < ROUNDS; i++) {
    const r = await measureApi(undefined);
    cold.ttfb.push(r.ttfb);
    cold.total.push(r.total);
  }
  console.log(row("TTFB(服务端+网络)", stats(cold.ttfb)));
  console.log(row("总耗时", stats(cold.total)));

  console.log("\n● 复用连接(keep-alive，共享连接+预热)，剔除握手影响后");
  const shared = new https.Agent({ keepAlive: true, maxSockets: 1 });
  await measureApi(shared); // 预热，建立并复用连接
  const warm = { ttfb: [], total: [] };
  for (let i = 0; i < ROUNDS; i++) {
    const r = await measureApi(shared);
    warm.ttfb.push(r.ttfb);
    warm.total.push(r.total);
  }
  shared.destroy();
  console.log(row("TTFB(≈推理+排队)", stats(warm.ttfb)));
  console.log(row("总耗时", stats(warm.total)));

  const net = cs.avg;
  const svr = stats(warm.ttfb).avg;
  console.log("\n──────── 结论估算 ────────");
  console.log(`  网络建连开销 ≈ ${net.toFixed(0)}ms/次(仅新连接需付)`);
  console.log(`  服务端响应(复用连接) ≈ ${svr.toFixed(0)}ms`);
  console.log(`  新连接单次总延迟中，握手占比 ≈ ${((net / stats(cold.total).avg) * 100).toFixed(0)}%`);
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
