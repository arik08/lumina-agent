import { currentKstString, formatDate } from "../format.js";
import { BASE_TYP02, fetchJson, handleError, type KmaJsonItem } from "./client.js";

const MID_PATH = "MidFcstInfoService";

/**
 * 중기예보 발표시각: 매일 06:00, 18:00.
 * 현재 시각 기준 가장 최근 발표 시각을 YYYYMMDDHHMM 형식으로 반환.
 */
function latestMidTmFc(now: Date = new Date()): string {
  const d = new Date(now);
  const hour = d.getHours();
  let baseHour: number;
  if (hour < 6) {
    d.setDate(d.getDate() - 1);
    baseHour = 18;
  } else if (hour < 18) {
    baseHour = 6;
  } else {
    baseHour = 18;
  }
  return `${formatDate(d)}${baseHour.toString().padStart(2, "0")}00`;
}

function getStr(it: KmaJsonItem, key: string): string {
  const v = it[key];
  if (v === undefined || v === null) return "";
  return String(v);
}

export async function getMidTermForecast(regId: string): Promise<string> {
  try {
    const tmFc = latestMidTmFc();
    const items = await fetchJson(BASE_TYP02, `${MID_PATH}/getMidLandFcst`, {
      numOfRows: "10",
      pageNo: "1",
      regId,
      tmFc,
    });
    if (items.length === 0) {
      return `구역코드 ${regId} (발표 ${tmFc}) 에 대한 중기 육상예보 결과가 없습니다.\n`;
    }
    const it = items[0];

    const lines: string[] = [
      `\n예보구역 ${regId} 중기 육상예보 (발표: ${tmFc})`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];

    for (const day of [4, 5, 6, 7]) {
      const wfAm = getStr(it, `wf${day}Am`);
      const wfPm = getStr(it, `wf${day}Pm`);
      const rnAm = getStr(it, `rnSt${day}Am`);
      const rnPm = getStr(it, `rnSt${day}Pm`);
      lines.push(`■ ${day}일 후`);
      if (wfAm || rnAm) {
        lines.push(`  오전: ${wfAm || "-"} (강수확률 ${rnAm || "-"}%)`);
      }
      if (wfPm || rnPm) {
        lines.push(`  오후: ${wfPm || "-"} (강수확률 ${rnPm || "-"}%)`);
      }
    }
    for (const day of [8, 9, 10]) {
      const wf = getStr(it, `wf${day}`);
      const rn = getStr(it, `rnSt${day}`);
      if (wf || rn) {
        lines.push(`■ ${day}일 후: ${wf || "-"} (강수확률 ${rn || "-"}%)`);
      }
    }

    return lines.join("\n") + "\n";
  } catch (err) {
    return handleError(err, `get_mid_term_forecast(regId=${regId})`);
  }
}

export async function getMidTermTemperature(regId: string): Promise<string> {
  try {
    const tmFc = latestMidTmFc();
    const items = await fetchJson(BASE_TYP02, `${MID_PATH}/getMidTa`, {
      numOfRows: "10",
      pageNo: "1",
      regId,
      tmFc,
    });
    if (items.length === 0) {
      return `구역코드 ${regId} (발표 ${tmFc}) 에 대한 중기 기온예보 결과가 없습니다.\n`;
    }
    const it = items[0];

    const lines: string[] = [
      `\n예보구역 ${regId} 중기 기온예보 (발표: ${tmFc})`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];

    for (const day of [4, 5, 6, 7, 8, 9, 10]) {
      const min = getStr(it, `taMin${day}`);
      const minLow = getStr(it, `taMin${day}Low`);
      const minHigh = getStr(it, `taMin${day}High`);
      const max = getStr(it, `taMax${day}`);
      const maxLow = getStr(it, `taMax${day}Low`);
      const maxHigh = getStr(it, `taMax${day}High`);
      if (!min && !max) continue;

      const minRange = minLow && minHigh ? ` (범위 ${minLow}~${minHigh}°C)` : "";
      const maxRange = maxLow && maxHigh ? ` (범위 ${maxLow}~${maxHigh}°C)` : "";
      lines.push(`■ ${day}일 후: 최저 ${min}°C${minRange} / 최고 ${max}°C${maxRange}`);
    }

    return lines.join("\n") + "\n";
  } catch (err) {
    return handleError(err, `get_mid_term_temperature(regId=${regId})`);
  }
}
