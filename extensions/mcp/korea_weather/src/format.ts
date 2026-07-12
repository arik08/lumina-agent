export const PTY_MAP: Record<number, string> = {
  0: "없음",
  1: "비",
  2: "비/눈",
  3: "눈",
  4: "소나기",
  5: "빗방울",
  6: "빗방울눈날림",
  7: "눈날림",
};

export const SKY_MAP: Record<number, string> = {
  1: "맑음",
  3: "구름많음",
  4: "흐림",
};

export const DIRECTION_16 = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

export const DIRECTION_16_KR = [
  "북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동",
  "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서",
];

export const WARNING_TYPE_MAP: Record<string, string> = {
  W: "강풍",
  R: "호우",
  C: "한파",
  D: "건조",
  O: "해일",
  N: "지진해일",
  V: "풍랑",
  T: "태풍",
  S: "대설",
  Y: "황사",
  H: "폭염",
  F: "안개",
};

export const WARNING_LEVEL_MAP: Record<string, string> = {
  "1": "예비특보",
  "2": "주의보",
  "3": "경보",
};

export const WARNING_CMD_MAP: Record<string, string> = {
  "1": "발표",
  "2": "해제",
  "3": "대치",
  "6": "연장",
  "7": "변경",
  "8": "변경 해제",
};

export const IMPACT_LEVEL_MAP: Record<number, string> = {
  0: "영향없음",
  1: "관심",
  2: "주의",
  3: "경고",
  4: "위험",
};

export const IMPACT_AREA_MAP: Record<"hw" | "cw", Record<number, string>> = {
  hw: {
    0: "모든 분야",
    1: "보건(일반인)",
    2: "보건(취약인)",
    3: "산업",
    4: "축산업",
    5: "농업",
    6: "수산양식",
    7: "기타",
  },
  cw: {
    0: "모든 분야",
    1: "보건",
    2: "산업",
    3: "시설물",
    4: "농축산업",
    5: "수산양식",
    6: "기타",
  },
};

export const IMPACT_PARAM_MAP: Record<string, string> = {
  hw: "폭염",
  cw: "한파",
};

export function windDirection(degree: number, labels: readonly string[]): string {
  const index = Math.floor((degree + 11.25) / 22.5) % 16;
  return labels[(index + 16) % 16];
}

export function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

export function formatDate(d: Date): string {
  return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}`;
}

export function formatDateTime(d: Date): string {
  return `${formatDate(d)}${pad2(d.getHours())}${pad2(d.getMinutes())}`;
}

export function formatYYYYMMDDHH(d: Date): string {
  return `${formatDate(d)}${pad2(d.getHours())}`;
}

export function prettyDate(yyyymmdd: string): string {
  if (yyyymmdd.length < 8) return yyyymmdd;
  return `${yyyymmdd.slice(0, 4)}년 ${yyyymmdd.slice(4, 6)}월 ${yyyymmdd.slice(6, 8)}일`;
}

export function prettyTime(hhmm: string): string {
  if (hhmm.length < 4) return hhmm;
  return `${hhmm.slice(0, 2)}:${hhmm.slice(2, 4)}`;
}

export function prettyDateTime(yyyymmddhhmm: string): string {
  if (yyyymmddhhmm.length < 12) return yyyymmddhhmm;
  return `${prettyDate(yyyymmddhhmm.slice(0, 8))} ${prettyTime(yyyymmddhhmm.slice(8, 12))}`;
}

const KST_FORMATTER = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function currentKstString(d: Date = new Date()): string {
  return `${KST_FORMATTER.format(d)} KST (UTC+9)`;
}
