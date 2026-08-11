export const BASE_TYP02 = "https://apihub.kma.go.kr/api/typ02/openApi";
export const BASE_TYP01 = "https://apihub.kma.go.kr/api/typ01/url";

export const TIMEOUT_MS = 15000;

export interface KmaJsonItem {
  category?: string;
  obsrValue?: string;
  fcstDate?: string;
  fcstTime?: string;
  fcstValue?: string;
  [key: string]: unknown;
}

interface KmaJsonResponse {
  response?: {
    header?: { resultCode?: string; resultMsg?: string };
    body?: {
      items?: { item?: KmaJsonItem[] | KmaJsonItem };
      totalCount?: number;
    };
  };
}

export function requireApiKey(): string {
  const apiKey = process.env.KOREA_WEATHER_API_KEY;
  if (!apiKey) {
    throw new Error("KOREA_WEATHER_API_KEY 환경변수가 설정되어 있지 않습니다.");
  }
  return decodeURIComponent(apiKey);
}

function buildUrl(
  baseUrl: string,
  path: string,
  params: Record<string, string | number | undefined>,
): URL {
  const url = new URL(`${baseUrl}/${path}`);
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    url.searchParams.append(key, String(value));
  }
  url.searchParams.set("authKey", requireApiKey());
  return url;
}

async function fetchText(url: URL, fallbackEncoding = "utf-8"): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  const charset = parseCharset(response.headers.get("content-type")) ?? fallbackEncoding;
  const buffer = await response.arrayBuffer();
  try {
    return new TextDecoder(charset, { fatal: false }).decode(buffer);
  } catch {
    return new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  }
}

function parseCharset(contentType: string | null): string | null {
  if (!contentType) return null;
  const match = /charset\s*=\s*"?([^";]+)"?/i.exec(contentType);
  return match ? match[1].trim().toLowerCase() : null;
}

export async function fetchJson(
  baseUrl: string,
  path: string,
  params: Record<string, string | number | undefined>,
): Promise<KmaJsonItem[]> {
  const url = buildUrl(baseUrl, path, { ...params, dataType: "JSON" });
  const text = await fetchText(url);

  let result: KmaJsonResponse;
  try {
    result = JSON.parse(text) as KmaJsonResponse;
  } catch (e) {
    throw new SyntaxError(
      `JSON 파싱 실패: ${(e as Error).message}\n응답: ${text.slice(0, 200)}`,
    );
  }

  const header = result.response?.header;
  if (header?.resultCode && header.resultCode !== "00") {
    throw new Error(
      `API 오류: ${header.resultCode} - ${header.resultMsg ?? "Unknown error"}`,
    );
  }

  const item = result.response?.body?.items?.item;
  if (!item) return [];
  return Array.isArray(item) ? item : [item];
}

export interface CsvRow {
  [columnName: string]: string;
}

/**
 * 기상청 typ01 PHP 엔드포인트의 CSV 응답을 파싱한다.
 *
 * 응답 형식:
 *   - `#`로 시작하는 줄은 메타정보/헤더/구분선이라 데이터에서 제외한다.
 *   - 첫 `#` 코멘트 직전 또는 직후에 컬럼명이 들어있을 수 있으나,
 *     순서가 스펙과 일치한다는 보장이 없으므로 호출자가 컬럼명을 명시한다.
 *   - 데이터 라인은 콤마로 구분되며, 토큰은 trim 한다.
 */
export async function fetchCsv(
  baseUrl: string,
  path: string,
  params: Record<string, string | number | undefined>,
  columns: readonly string[],
): Promise<CsvRow[]> {
  const url = buildUrl(baseUrl, path, { ...params, disp: "1", help: "0" });
  // typ01 PHP 엔드포인트는 Content-Type charset을 명시하지 않거나 EUC-KR로 응답한다.
  const text = await fetchText(url, "euc-kr");

  const rows: CsvRow[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith("#")) continue;
    const tokens = line.split(",").map((t) => t.trim());
    if (tokens.length === 0) continue;
    if (tokens.every((t) => t === "")) continue;
    const row: CsvRow = {};
    for (let i = 0; i < columns.length; i++) {
      row[columns[i]] = tokens[i] ?? "";
    }
    rows.push(row);
  }
  return rows;
}

function isNetworkError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  return (
    err.name === "AbortError" ||
    err.name === "TypeError" ||
    err.message.startsWith("HTTP ") ||
    "code" in err
  );
}

export function handleError(err: unknown, context: string): string {
  const detail = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
  console.error(
    `[${new Date().toISOString()}] [korea_weather] ${context} 호출 실패 - ${detail}`,
  );
  if (err instanceof SyntaxError) {
    return `JSON 파싱 중 오류 발생: ${err.message}\n`;
  }
  if (err instanceof Error) {
    if (isNetworkError(err)) {
      return `API 요청 중 오류 발생: ${err.message}\n`;
    }
    return `오류: ${err.message}\n`;
  }
  return `예상치 못한 오류 발생: ${String(err)}\n`;
}
