import { getGridCoordinateFromLonLat } from "../grid.js";
import {
  DIRECTION_16,
  DIRECTION_16_KR,
  PTY_MAP,
  SKY_MAP,
  currentKstString,
  formatDate,
  pad2,
  prettyDate,
  windDirection,
} from "../format.js";
import { BASE_TYP02, fetchJson, handleError } from "./client.js";

const VILAGE_FCST_PATH = "VilageFcstInfoService_2.0";
const MSG_PATH = "VilageFcstMsgService";

export async function getNowcastObservation(lon: number, lat: number): Promise<string> {
  try {
    const { nx, ny } = getGridCoordinateFromLonLat(lon, lat);
    const now = new Date();
    if (now.getMinutes() < 40) {
      now.setHours(now.getHours() - 1);
    }

    const items = await fetchJson(BASE_TYP02, `${VILAGE_FCST_PATH}/getUltraSrtNcst`, {
      numOfRows: "10",
      pageNo: "1",
      base_date: formatDate(now),
      base_time: `${pad2(now.getHours())}00`,
      nx,
      ny,
    });

    const data: Record<string, string> = {};
    for (const item of items) {
      const value = item.obsrValue;
      if (value === undefined) continue;
      switch (item.category) {
        case "T1H": data.temperature = `${value}°C`; break;
        case "RN1": data.rainfall = `${value}mm`; break;
        case "REH": data.humidity = `${value}%`; break;
        case "WSD": data.wind_speed = `${value}m/s`; break;
      }
    }

    return (
      `\n위도 ${lat}, 경도 ${lon} 현재 날씨:\n` +
      `조회 시각: ${currentKstString()}\n` +
      `기온: ${data.temperature ?? "N/A"}\n` +
      `강수량: ${data.rainfall ?? "N/A"}\n` +
      `습도: ${data.humidity ?? "N/A"}\n` +
      `풍속: ${data.wind_speed ?? "N/A"}\n`
    );
  } catch (err) {
    return handleError(err, `get_nowcast_observation(lon=${lon}, lat=${lat})`);
  }
}

export async function getNowcastForecast(lon: number, lat: number): Promise<string> {
  try {
    const { nx, ny } = getGridCoordinateFromLonLat(lon, lat);
    const now = new Date();
    if (now.getMinutes() < 45) {
      now.setHours(now.getHours() - 1);
    }
    const baseDate = formatDate(now);
    const baseTime = `${pad2(now.getHours())}30`;

    const items = await fetchJson(BASE_TYP02, `${VILAGE_FCST_PATH}/getUltraSrtFcst`, {
      numOfRows: "60",
      pageNo: "1",
      base_date: baseDate,
      base_time: baseTime,
      nx,
      ny,
    });

    const grouped: Record<string, Record<string, string>> = {};
    for (const item of items) {
      if (!item.fcstDate || !item.fcstTime || !item.category || item.fcstValue === undefined) continue;
      const key = `${item.fcstDate} ${item.fcstTime}`;
      if (!grouped[key]) grouped[key] = {};
      grouped[key][item.category] = item.fcstValue;
    }

    const lines: string[] = [
      `\n위도 ${lat}, 경도 ${lon} 초단기 예보 (발표: ${prettyDate(baseDate)} ${baseTime.slice(0, 2)}:${baseTime.slice(2)}시)`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];

    for (const key of Object.keys(grouped).sort()) {
      const fcst = grouped[key];
      const dateStr = prettyDate(key.slice(0, 8));
      const hhmm = key.slice(9);
      lines.push(`■ ${dateStr} ${hhmm.slice(0, 2)}:${hhmm.slice(2)}시 예보`);

      if (fcst.T1H !== undefined) lines.push(`  기온: ${fcst.T1H}°C`);
      if (fcst.PTY !== undefined) {
        lines.push(`  강수형태: ${PTY_MAP[parseInt(fcst.PTY, 10)] ?? "알 수 없음"}`);
      }
      if (fcst.RN1 !== undefined) {
        lines.push(`  1시간 강수량: ${fcst.RN1 === "강수없음" ? "없음" : fcst.RN1}`);
      }
      if (fcst.REH !== undefined) lines.push(`  습도: ${fcst.REH}%`);
      if (fcst.SKY !== undefined) {
        lines.push(`  하늘상태: ${SKY_MAP[parseInt(fcst.SKY, 10)] ?? "알 수 없음"}`);
      }
      if (fcst.WSD !== undefined) lines.push(`  풍속: ${fcst.WSD}m/s`);
      if (fcst.VEC !== undefined) {
        lines.push(`  풍향: ${windDirection(parseFloat(fcst.VEC), DIRECTION_16)} (${fcst.VEC}°)`);
      }
      if (fcst.LGT !== undefined) {
        const lgt = parseInt(fcst.LGT, 10);
        lines.push(`  낙뢰: ${lgt === 0 ? "없음" : `${lgt} kA/㎢`}`);
      }
      lines.push("");
    }

    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_nowcast_forecast(lon=${lon}, lat=${lat})`);
  }
}

export async function getShortTermForecast(lon: number, lat: number): Promise<string> {
  try {
    const { nx, ny } = getGridCoordinateFromLonLat(lon, lat);
    const now = new Date();
    const baseTimes = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"];

    let availableTime: string | null = null;
    for (const bt of baseTimes) {
      const btHour = parseInt(bt.slice(0, 2), 10);
      if (now.getHours() > btHour || (now.getHours() === btHour && now.getMinutes() >= 10)) {
        availableTime = bt;
      }
    }
    if (availableTime === null) {
      availableTime = "2300";
      now.setDate(now.getDate() - 1);
    }
    const baseDate = formatDate(now);

    const items = await fetchJson(BASE_TYP02, `${VILAGE_FCST_PATH}/getVilageFcst`, {
      numOfRows: "1000",
      pageNo: "1",
      base_date: baseDate,
      base_time: availableTime,
      nx,
      ny,
    });

    const byDateTime: Record<string, Record<string, Record<string, string>>> = {};
    for (const item of items) {
      if (!item.fcstDate || !item.fcstTime || !item.category || item.fcstValue === undefined) continue;
      if (!byDateTime[item.fcstDate]) byDateTime[item.fcstDate] = {};
      if (!byDateTime[item.fcstDate][item.fcstTime]) byDateTime[item.fcstDate][item.fcstTime] = {};
      byDateTime[item.fcstDate][item.fcstTime][item.category] = item.fcstValue;
    }

    const lines: string[] = [
      `\n위도 ${lat}, 경도 ${lon} 단기 예보 (발표: ${baseDate} ${availableTime})`,
      `조회 시각: ${currentKstString()}`,
      `총 ${items.length}개 데이터 조회`,
      "=".repeat(50),
    ];

    for (const fcstDate of Object.keys(byDateTime).sort()) {
      lines.push(`\n【 ${prettyDate(fcstDate)} 예보 】`);
      const dayValues = Object.values(byDateTime[fcstDate]);
      const tmn = dayValues.find((d) => d.TMN !== undefined)?.TMN;
      const tmx = dayValues.find((d) => d.TMX !== undefined)?.TMX;
      if (tmn) lines.push(`  ▶ 최저기온: ${tmn}°C`);
      if (tmx) lines.push(`  ▶ 최고기온: ${tmx}°C`);

      lines.push("\n  시간별 예보:");
      for (const fcstTime of Object.keys(byDateTime[fcstDate]).sort()) {
        const hour = parseInt(fcstTime.slice(0, 2), 10);
        const amPm = hour < 12 ? "오전" : "오후";
        const displayHour = hour === 0 ? 12 : hour <= 12 ? hour : hour - 12;
        const formattedTime = `${amPm} ${displayHour}시`;
        const t = byDateTime[fcstDate][fcstTime];

        const info: string[] = [];
        if (t.TMP !== undefined) info.push(`기온 ${t.TMP}°C`);
        if (t.POP !== undefined) info.push(`강수확률 ${t.POP}%`);
        if (t.PTY !== undefined) {
          const v = parseInt(t.PTY, 10);
          if (v !== 0 && PTY_MAP[v]) info.push(PTY_MAP[v]);
        }
        if (t.PCP !== undefined && t.PCP !== "" && t.PCP !== "강수없음") {
          info.push(`강수량 ${t.PCP}`);
        }
        if (t.SNO !== undefined && t.SNO !== "" && t.SNO !== "적설없음") {
          info.push(`적설 ${t.SNO}`);
        }
        if (t.SKY !== undefined) {
          const v = parseInt(t.SKY, 10);
          if (SKY_MAP[v]) info.push(SKY_MAP[v]);
        }
        if (t.REH !== undefined) info.push(`습도 ${t.REH}%`);

        lines.push(`  ■ ${formattedTime}: ${info.join(", ")}`);

        if (t.VEC !== undefined && t.WSD !== undefined) {
          const wsd = parseFloat(t.WSD);
          const desc = wsd < 4 ? "약한 바람" : wsd < 9 ? "약간 강한 바람" : "강한 바람";
          lines.push(
            `    - ${windDirection(parseFloat(t.VEC), DIRECTION_16_KR)}풍 ${desc}(${wsd}m/s)`,
          );
        }
      }
    }

    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_short_term_forecast(lon=${lon}, lat=${lat})`);
  }
}

export async function getShortTermLandForecast(regId: string): Promise<string> {
  try {
    const items = await fetchJson(BASE_TYP02, `${MSG_PATH}/getLandFcst`, {
      numOfRows: "100",
      pageNo: "1",
      regId,
    });
    if (items.length === 0) {
      return `구역코드 ${regId}에 대한 단기 육상예보 결과가 없습니다.\n`;
    }

    const lines: string[] = [
      `\n예보구역 ${regId} 단기 육상예보 (텍스트)`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];
    for (const it of items) {
      const announceTime = String(it.announceTime ?? "");
      const numEf = String(it.numEf ?? "");
      lines.push(`■ 발표시간 ${announceTime} / 발효번호 ${numEf}`);
      if (it.ta !== undefined && it.ta !== "") lines.push(`  기온: ${it.ta}°C`);
      if (it.rnSt !== undefined && it.rnSt !== "") lines.push(`  강수확률: ${it.rnSt}%`);
      if (it.wf !== undefined && it.wf !== "") lines.push(`  날씨: ${it.wf}`);
      if (it.rnYn !== undefined && it.rnYn !== "") lines.push(`  강수형태: ${it.rnYn}`);
      const wd1 = it.wd1 ?? "";
      const wd2 = it.wd2 ?? "";
      if (wd1 || wd2) lines.push(`  풍향: ${[wd1, wd2].filter(Boolean).join("→")}`);
      if (it.wsIt !== undefined && it.wsIt !== "") lines.push(`  풍속 강도: ${it.wsIt}`);
      lines.push("");
    }
    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_short_term_land_forecast(regId=${regId})`);
  }
}

export async function getShortTermSeaForecast(regId: string): Promise<string> {
  try {
    const items = await fetchJson(BASE_TYP02, `${MSG_PATH}/getSeaFcst`, {
      numOfRows: "100",
      pageNo: "1",
      regId,
    });
    if (items.length === 0) {
      return `구역코드 ${regId}에 대한 단기 해상예보 결과가 없습니다.\n`;
    }

    const lines: string[] = [
      `\n예보구역 ${regId} 단기 해상예보 (텍스트)`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];
    for (const it of items) {
      const tmFc = String(it.tmFc ?? "");
      const numEf = String(it.numEf ?? "");
      lines.push(`■ 발표시간 ${tmFc} / 발효번호 ${numEf}`);
      if (it.wf !== undefined && it.wf !== "") lines.push(`  날씨: ${it.wf}`);
      const wd1 = it.wd1 ?? "";
      const wd2 = it.wd2 ?? "";
      if (wd1 || wd2) lines.push(`  풍향: ${[wd1, wd2].filter(Boolean).join("→")}`);
      const ws1 = it.ws1 ?? "";
      const ws2 = it.ws2 ?? "";
      if (ws1 || ws2) lines.push(`  풍속: ${ws1}${ws2 ? `~${ws2}` : ""}m/s`);
      const wh1 = it.wh1 ?? "";
      const wh2 = it.wh2 ?? "";
      if (wh1 || wh2) lines.push(`  파고: ${wh1}${wh2 ? `~${wh2}` : ""}m`);
      if (it.rnYn !== undefined && it.rnYn !== "") lines.push(`  강수형태: ${it.rnYn}`);
      lines.push("");
    }
    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_short_term_sea_forecast(regId=${regId})`);
  }
}

export async function getWeatherSituation(stnId: number): Promise<string> {
  try {
    const items = await fetchJson(BASE_TYP02, `${MSG_PATH}/getWthrSituation`, {
      numOfRows: "10",
      pageNo: "1",
      stnId,
    });
    if (items.length === 0) {
      return `발표관서 ${stnId}에 대한 기상개황 결과가 없습니다.\n`;
    }

    const lines: string[] = [
      `\n발표관서 ${stnId} 기상개황`,
      `조회 시각: ${currentKstString()}`,
      "=".repeat(50),
    ];
    for (const it of items) {
      const tmFc = String(it.tmFc ?? "");
      lines.push(`■ 발표시각 ${tmFc}`);
      if (it.wfSv1 !== undefined && it.wfSv1 !== "") {
        lines.push(`  [종합]\n  ${String(it.wfSv1).replace(/\r?\n/g, "\n  ")}`);
      }
      if (it.wn !== undefined && it.wn !== "") lines.push(`  [특보사항] ${it.wn}`);
      if (it.wr !== undefined && it.wr !== "") lines.push(`  [예비특보] ${it.wr}`);
      lines.push("");
    }
    return lines.join("\n");
  } catch (err) {
    return handleError(err, `get_weather_situation(stnId=${stnId})`);
  }
}
