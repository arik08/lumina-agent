import {
  IMPACT_AREA_MAP,
  IMPACT_LEVEL_MAP,
  IMPACT_PARAM_MAP,
  currentKstString,
  formatDate,
  prettyDate,
} from "../format.js";
import { BASE_TYP01, fetchCsv, handleError } from "./client.js";

const IFS_COLUMNS = [
  "TM_FC",
  "TM_EF",
  "STN",
  "REG_ID",
  "IFPAR",
  "IFAREA",
  "ILVL",
] as const;

export type ImpactParam = "hw" | "cw";

export async function getImpactForecast(
  ifpar: ImpactParam,
  regId?: string,
): Promise<string> {
  try {
    const today = formatDate(new Date());
    const params: Record<string, string> = {
      ifpar,
      tmef1: today,
      tmef2: today,
    };
    if (regId) params.regid = regId;

    const rows = await fetchCsv(BASE_TYP01, "ifs_fct_pstt.php", params, IFS_COLUMNS);

    if (rows.length === 0) {
      const head = regId
        ? `구역코드 ${regId} 의 ${IMPACT_PARAM_MAP[ifpar]} 영향예보 결과가 없습니다.`
        : `오늘(${prettyDate(today)}) ${IMPACT_PARAM_MAP[ifpar]} 영향예보 결과가 없습니다.`;
      return `${head}\n조회 시각: ${currentKstString()}\n`;
    }

    const lines: string[] = [
      `\n${IMPACT_PARAM_MAP[ifpar]} 영향예보 (기준일 ${prettyDate(today)}, ${rows.length}건)`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];

    const areaMap = IMPACT_AREA_MAP[ifpar];
    for (const r of rows) {
      const ilvl = parseInt(r.ILVL, 10);
      const ilvlName = Number.isNaN(ilvl) ? r.ILVL : (IMPACT_LEVEL_MAP[ilvl] ?? r.ILVL);
      const ifarea = parseInt(r.IFAREA, 10);
      const areaName = Number.isNaN(ifarea) ? r.IFAREA : (areaMap[ifarea] ?? r.IFAREA);
      lines.push(
        `■ ${r.REG_ID} | ${areaName} | 위험수준 ${ilvl}=${ilvlName} | 발표 ${r.TM_FC} | 기준일 ${r.TM_EF}`,
      );
    }
    return lines.join("\n") + "\n";
  } catch (err) {
    return handleError(err, `get_impact_forecast(ifpar=${ifpar}, regId=${regId ?? "ALL"})`);
  }
}
