#!/usr/bin/env node
import "dotenv/config";

import { timingSafeEqual } from "node:crypto";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express, { type RequestHandler } from "express";
import { z } from "zod";

import {
  getNowcastObservation,
  getNowcastForecast,
  getShortTermForecast,
  getShortTermLandForecast,
  getShortTermSeaForecast,
  getWeatherSituation,
} from "./api/short-term.js";
import {
  getMidTermForecast,
  getMidTermTemperature,
} from "./api/mid-term.js";
import { getActiveWarnings } from "./api/warnings.js";
import { getImpactForecast } from "./api/impact.js";
import {
  lookupForecastZone,
  lookupWarningZone,
} from "./api/zones.js";

export function createServer(): McpServer {
  const server = new McpServer({
    name: "korea_weather",
    version: "0.3.0",
  });

  const coords = {
    lon: z.number().describe("경도 (longitude)"),
    lat: z.number().describe("위도 (latitude)"),
  };

  server.registerTool(
    "get_nowcast_observation",
    {
      description: "특정 좌표(위경도)의 현재 관측 날씨를 조회합니다. 기상청 초단기실황(getUltraSrtNcst).",
      inputSchema: coords,
    },
    async ({ lon, lat }) => ({
      content: [{ type: "text", text: await getNowcastObservation(lon, lat) }],
    }),
  );

  server.registerTool(
    "get_nowcast_forecast",
    {
      description: "특정 좌표(위경도)의 초단기(약 6시간) 예보를 조회합니다. 기상청 초단기예보(getUltraSrtFcst).",
      inputSchema: coords,
    },
    async ({ lon, lat }) => ({
      content: [{ type: "text", text: await getNowcastForecast(lon, lat) }],
    }),
  );

  server.registerTool(
    "get_short_term_forecast",
    {
      description: "특정 좌표(위경도)의 단기(약 3~5일) 시간별 예보를 조회합니다. 기상청 단기예보(getVilageFcst).",
      inputSchema: coords,
    },
    async ({ lon, lat }) => ({
      content: [{ type: "text", text: await getShortTermForecast(lon, lat) }],
    }),
  );

  server.registerTool(
    "get_short_term_land_forecast",
    {
      description:
        "단기 육상예보 텍스트(VilageFcstMsgService.getLandFcst). " +
        "regId 예: 11B10101(서울), 11A00101(백령도). " +
        "구역코드를 모를 경우 lookup_forecast_zone 를 먼저 호출하세요.",
      inputSchema: { regId: z.string().describe("단기예보 육상 구역코드 (예: 11B10101)") },
    },
    async ({ regId }) => ({
      content: [{ type: "text", text: await getShortTermLandForecast(regId) }],
    }),
  );

  server.registerTool(
    "get_short_term_sea_forecast",
    {
      description:
        "단기 해상예보 텍스트(VilageFcstMsgService.getSeaFcst). " +
        "regId 예: 12A20100(서해중부앞바다). lookup_forecast_zone 결과 참고.",
      inputSchema: { regId: z.string().describe("단기예보 해상 구역코드 (예: 12A20100)") },
    },
    async ({ regId }) => ({
      content: [{ type: "text", text: await getShortTermSeaForecast(regId) }],
    }),
  );

  server.registerTool(
    "get_weather_situation",
    {
      description:
        "발표관서(stnId) 기준 기상개황(VilageFcstMsgService.getWthrSituation). " +
        "예: 108=기상청, 109=수도권(서울).",
      inputSchema: { stnId: z.number().int().describe("발표관서 번호 (예: 108)") },
    },
    async ({ stnId }) => ({
      content: [{ type: "text", text: await getWeatherSituation(stnId) }],
    }),
  );

  server.registerTool(
    "get_mid_term_forecast",
    {
      description:
        "중기(4~10일) 육상예보. 하늘상태/강수확률 (MidFcstInfoService.getMidLandFcst). " +
        "regId 예: 11B00000(서울/인천/경기). 단기 육상 regId(11B10101 등)와 다르므로 주의.",
      inputSchema: { regId: z.string().describe("중기 육상 구역코드 (예: 11B00000)") },
    },
    async ({ regId }) => ({
      content: [{ type: "text", text: await getMidTermForecast(regId) }],
    }),
  );

  server.registerTool(
    "get_mid_term_temperature",
    {
      description:
        "중기(4~10일) 최저/최고 기온 예보 (MidFcstInfoService.getMidTa). " +
        "regId 예: 11B10101(서울).",
      inputSchema: { regId: z.string().describe("중기 기온 구역코드 (예: 11B10101)") },
    },
    async ({ regId }) => ({
      content: [{ type: "text", text: await getMidTermTemperature(regId) }],
    }),
  );

  server.registerTool(
    "get_active_warnings",
    {
      description:
        "현재 발효 중인 기상특보(강풍/호우/한파/태풍 등) 조회. wrn_now_data.php 사용. " +
        "regId 미입력 시 전국 전체. 특정 구역만 보려면 lookup_warning_zone 으로 코드 확인 후 입력.",
      inputSchema: { regId: z.string().optional().describe("특보구역 코드 (선택)") },
    },
    async ({ regId }) => ({
      content: [{ type: "text", text: await getActiveWarnings(regId) }],
    }),
  );

  server.registerTool(
    "get_impact_forecast",
    {
      description:
        "폭염(hw)/한파(cw) 영향예보 - 분야별 위험수준(0~4). ifs_fct_pstt.php 사용. 오늘 기준.",
      inputSchema: {
        ifpar: z.enum(["hw", "cw"]).describe("hw=폭염, cw=한파"),
        regId: z.string().optional().describe("특보구역 코드 (선택, 예: L1050100)"),
      },
    },
    async ({ ifpar, regId }) => ({
      content: [{ type: "text", text: await getImpactForecast(ifpar, regId) }],
    }),
  );

  server.registerTool(
    "lookup_forecast_zone",
    {
      description:
        "단기/중기 예보용 구역코드(regId) 검색 (FcstZoneInfoService.getFcstZoneCd). " +
        "regId 또는 regName(한글 일부 매칭) 중 하나 이상 지정.",
      inputSchema: {
        regId: z.string().optional().describe("정확한 예보구역 코드 (예: 11B10101)"),
        regName: z.string().optional().describe("구역명 한글/영문 부분 검색 (예: \"서울\")"),
      },
    },
    async ({ regId, regName }) => ({
      content: [{ type: "text", text: await lookupForecastZone({ regId, regName }) }],
    }),
  );

  server.registerTool(
    "lookup_warning_zone",
    {
      description:
        "특보구역 코드 검색 (WethrBasicInfoService.getWrnZoneCd). " +
        "korName 미입력 시 전체 목록 일부 반환.",
      inputSchema: {
        korName: z.string().optional().describe("구역명 한글 검색어 (예: \"서울\")"),
      },
    },
    async ({ korName }) => ({
      content: [{ type: "text", text: await lookupWarningZone({ korName }) }],
    }),
  );

  return server;
}

async function startStdio(): Promise<void> {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[korea_weather] MCP server listening on stdio");
}

function summarizeMcpBody(body: unknown): string {
  if (!body || typeof body !== "object") return "";
  const msgs = Array.isArray(body) ? body : [body];
  const parts: string[] = [];
  for (const m of msgs) {
    if (!m || typeof m !== "object" || !("method" in m)) continue;
    const method = (m as { method?: unknown }).method;
    if (typeof method !== "string") continue;
    const params = (m as { params?: unknown }).params;
    if (
      method === "tools/call" &&
      params &&
      typeof params === "object" &&
      "name" in params
    ) {
      const name = (params as { name?: unknown }).name;
      const args = (params as { arguments?: unknown }).arguments;
      const argStr = args === undefined ? "" : ` ${JSON.stringify(args)}`;
      parts.push(`tools/call:${String(name)}${argStr}`);
    } else {
      parts.push(method);
    }
  }
  if (parts.length === 0) return "";
  const joined = parts.join(",");
  return joined.length > 300 ? `${joined.slice(0, 297)}...` : joined;
}

function httpRequestLogger(): RequestHandler {
  return (req, res, next) => {
    const start = Date.now();
    const ip = req.ip ?? req.socket.remoteAddress ?? "-";
    const mcp = summarizeMcpBody(req.body);
    res.on("finish", () => {
      const duration = Date.now() - start;
      const mcpField = mcp ? ` mcp=${mcp}` : "";
      console.error(
        `[${new Date().toISOString()}] [korea_weather] ${ip} ${req.method} ${req.originalUrl} ${res.statusCode} ${duration}ms${mcpField}`,
      );
    });
    next();
  };
}

function apiKeyAuth(expectedKey: string): RequestHandler {
  const expectedBuf = Buffer.from(expectedKey, "utf8");
  return (req, res, next) => {
    const provided = req.header("x-api-key");
    if (!provided) {
      res.status(401).json({ error: "x-api-key header required" });
      return;
    }
    const providedBuf = Buffer.from(provided, "utf8");
    if (
      providedBuf.length !== expectedBuf.length ||
      !timingSafeEqual(providedBuf, expectedBuf)
    ) {
      res.status(401).json({ error: "invalid x-api-key" });
      return;
    }
    next();
  };
}

async function startHttp(host: string, port: number): Promise<void> {
  const expectedKey = process.env.MCP_API_KEY;
  if (!expectedKey) {
    throw new Error(
      "MCP_API_KEY 환경변수가 설정되어 있지 않습니다. HTTP 모드는 x-api-key 인증이 필수입니다.",
    );
  }

  const app = express();
  app.use(express.json());
  app.use(httpRequestLogger());

  app.get("/healthz", (_req, res) => {
    res.status(200).type("text/plain").send("ok");
  });

  app.use("/mcp", apiKeyAuth(expectedKey));

  app.all("/mcp", async (req, res) => {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });
    res.on("close", () => {
      transport.close();
    });
    const server = createServer();
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });

  await new Promise<void>((resolve, reject) => {
    const httpServer = app.listen(port, host, () => {
      const addr = httpServer.address();
      const actualHost =
        typeof addr === "object" && addr !== null ? addr.address : host;
      const actualPort =
        typeof addr === "object" && addr !== null ? addr.port : port;
      console.error(
        `[korea_weather] MCP server listening on http://${actualHost}:${actualPort}/mcp`,
      );
      resolve();
    });
    httpServer.once("error", reject);
  });
}

async function main(): Promise<void> {
  const useStdio = process.argv.includes("--stdio") || process.env.TRANSPORT === "stdio";
  if (useStdio) {
    await startStdio();
    return;
  }
  const host = process.env.HOST ?? "127.0.0.1";
  const port = Number.parseInt(process.env.PORT ?? "8081", 10);
  await startHttp(host, port);
}

main().catch((err) => {
  console.error("서버 실행 중 오류 발생:", err);
  process.exit(1);
});
