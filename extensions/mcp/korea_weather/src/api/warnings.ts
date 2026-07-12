import {
  WARNING_CMD_MAP,
  WARNING_LEVEL_MAP,
  WARNING_TYPE_MAP,
  currentKstString,
  prettyDateTime,
} from "../format.js";
import { BASE_TYP01, fetchCsv, handleError } from "./client.js";

const WRN_NOW_COLUMNS = [
  "REG_UP",
  "REG_UP_KO",
  "REG_ID",
  "REG_KO",
  "TM_FC",
  "TM_EF",
  "WRN",
  "LVL",
  "CMD",
] as const;

export async function getActiveWarnings(regId?: string): Promise<string> {
  try {
    const rows = await fetchCsv(
      BASE_TYP01,
      "wrn_now_data.php",
      { fe: "f", tm: "" },
      WRN_NOW_COLUMNS,
    );

    const filtered = regId ? rows.filter((r) => r.REG_ID === regId) : rows;

    if (filtered.length === 0) {
      const head = regId
        ? `구역코드 ${regId} 에 현재 발효 중인 기상특보가 없습니다.`
        : `현재 발효 중인 기상특보가 없습니다.`;
      return `${head}\n조회 시각: ${currentKstString()}\n`;
    }

    const lines: string[] = [
      regId
        ? `\n구역 ${regId} 현재 발효 중인 기상특보 (${filtered.length}건)`
        : `\n전국 현재 발효 중인 기상특보 (${filtered.length}건)`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];

    for (const r of filtered) {
      const wrnName = WARNING_TYPE_MAP[r.WRN] ?? r.WRN;
      const lvlName = WARNING_LEVEL_MAP[r.LVL] ?? r.LVL;
      const cmdName = WARNING_CMD_MAP[r.CMD] ?? r.CMD;
      const region = r.REG_KO || r.REG_ID;
      const upper = r.REG_UP_KO ? `${r.REG_UP_KO} > ` : "";
      lines.push(`■ ${upper}${region} (${r.REG_ID})`);
      lines.push(`  ${wrnName} ${lvlName} (${cmdName})`);
      lines.push(`  발표 ${prettyDateTime(r.TM_FC)} / 발효 ${prettyDateTime(r.TM_EF)}`);
      lines.push("");
    }

    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_active_warnings(regId=${regId ?? "ALL"})`);
  }
}
