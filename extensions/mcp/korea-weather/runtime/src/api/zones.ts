import { BASE_TYP02, fetchJson, handleError } from "./client.js";

export interface LookupForecastZoneInput {
  regId?: string;
  regName?: string;
  numOfRows?: number;
}

export async function lookupForecastZone(
  input: LookupForecastZoneInput,
): Promise<string> {
  try {
    const params: Record<string, string | number> = {
      pageNo: 1,
      numOfRows: input.numOfRows ?? 50,
    };
    if (input.regId) params.regId = input.regId;

    const items = await fetchJson(
      BASE_TYP02,
      "FcstZoneInfoService/getFcstZoneCd",
      params,
    );

    const filtered = input.regName
      ? items.filter((it) => {
          const name = String(it.regName ?? "");
          const en = String(it.regEn ?? "");
          return name.includes(input.regName!) || en.toLowerCase().includes(input.regName!.toLowerCase());
        })
      : items;

    if (filtered.length === 0) {
      return `검색 조건에 맞는 예보구역이 없습니다.\n`;
    }

    const lines: string[] = [
      `\n예보구역 검색 결과 (${filtered.length}건)`,
      "=".repeat(50),
    ];
    for (const it of filtered) {
      const regId = String(it.regId ?? "");
      const regName = String(it.regName ?? "");
      const regEn = String(it.regEn ?? "");
      const lat = String(it.lat ?? "");
      const lon = String(it.lon ?? "");
      const stnFd = String(it.stnFd ?? "");
      lines.push(`■ ${regId} | ${regName}${regEn ? ` (${regEn})` : ""}`);
      if (lat && lon) lines.push(`  위경도: ${lat}, ${lon}`);
      if (stnFd) lines.push(`  단기예보관서: ${stnFd}`);
    }
    return lines.join("\n") + "\n";
  } catch (err) {
    return handleError(
      err,
      `lookup_forecast_zone(regId=${input.regId ?? "-"}, regName=${input.regName ?? "-"})`,
    );
  }
}

export interface LookupWarningZoneInput {
  korName?: string;
  numOfRows?: number;
}

export async function lookupWarningZone(
  input: LookupWarningZoneInput,
): Promise<string> {
  try {
    const params: Record<string, string | number> = {
      pageNo: 1,
      numOfRows: input.numOfRows ?? 100,
    };
    if (input.korName) params.korName = input.korName;

    const items = await fetchJson(
      BASE_TYP02,
      "WethrBasicInfoService/getWrnZoneCd",
      params,
    );

    if (items.length === 0) {
      return `검색 조건에 맞는 특보구역이 없습니다.\n`;
    }

    const lines: string[] = [
      `\n특보구역 검색 결과 (${items.length}건)`,
      "=".repeat(50),
    ];
    for (const it of items) {
      const code = String(it.warningAreaCode ?? it.regId ?? "");
      const name = String(it.korName ?? it.regName ?? "");
      lines.push(`■ ${code} | ${name}`);
    }
    return lines.join("\n") + "\n";
  } catch (err) {
    return handleError(err, `lookup_warning_zone(korName=${input.korName ?? "-"})`);
  }
}
