interface LambertConformalConic {
  re: number;
  slat1Rad: number;
  slat2Rad: number;
  olonRad: number;
  sn: number;
  sf: number;
  ro: number;
  xo: number;
  yo: number;
  pi: number;
  degrad: number;
}

let cachedProjection: LambertConformalConic | null = null;

function getProjection(): LambertConformalConic {
  if (cachedProjection) return cachedProjection;

  const reKm = 6371.00877;
  const grid = 5.0;
  const slat1 = 30.0;
  const slat2 = 60.0;
  const olon = 126.0;
  const olat = 38.0;
  const xo = 210 / grid;
  const yo = 675 / grid;

  const pi = Math.PI;
  const degrad = pi / 180.0;

  const re = reKm / grid;
  const slat1Rad = slat1 * degrad;
  const slat2Rad = slat2 * degrad;
  const olonRad = olon * degrad;
  const olatRad = olat * degrad;

  let sn = Math.tan(pi * 0.25 + slat2Rad * 0.5) / Math.tan(pi * 0.25 + slat1Rad * 0.5);
  sn = Math.log(Math.cos(slat1Rad) / Math.cos(slat2Rad)) / Math.log(sn);
  let sf = Math.tan(pi * 0.25 + slat1Rad * 0.5);
  sf = (Math.pow(sf, sn) * Math.cos(slat1Rad)) / sn;
  let ro = Math.tan(pi * 0.25 + olatRad * 0.5);
  ro = (re * sf) / Math.pow(ro, sn);

  cachedProjection = {
    re,
    slat1Rad,
    slat2Rad,
    olonRad,
    sn,
    sf,
    ro,
    xo,
    yo,
    pi,
    degrad,
  };
  return cachedProjection;
}

/**
 * 위경도 좌표를 기상청 격자 좌표(nx, ny)로 변환합니다.
 */
export function getGridCoordinateFromLonLat(lon: number, lat: number): { nx: number; ny: number } {
  const proj = getProjection();

  let ra = Math.tan(proj.pi * 0.25 + lat * proj.degrad * 0.5);
  ra = (proj.re * proj.sf) / Math.pow(ra, proj.sn);
  let theta = lon * proj.degrad - proj.olonRad;

  if (theta > proj.pi) theta -= 2.0 * proj.pi;
  if (theta < -proj.pi) theta += 2.0 * proj.pi;

  theta *= proj.sn;

  const x = ra * Math.sin(theta) + proj.xo;
  const y = proj.ro - ra * Math.cos(theta) + proj.yo;
  return {
    nx: Math.floor(x + 1.5),
    ny: Math.floor(y + 1.5),
  };
}
