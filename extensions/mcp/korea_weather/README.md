# korea-weather-mcp

기상청 [API 허브](https://apihub.kma.go.kr/)의 5개 카테고리(단기예보·중기예보·기상특보·영향예보·구역정보)를 래핑한 [Model Context Protocol](https://modelcontextprotocol.io) 서버입니다. 위경도 좌표 또는 구역코드(`regId`)를 입력하면 해당 데이터를 한국어 텍스트로 정리해 반환합니다.

- **Runtime**: Node.js 18+ (TypeScript, ESM)
- **Transport**: stdio, Streamable HTTP
- **MCP SDK**: `@modelcontextprotocol/sdk`

## 제공 도구 (Tools)

### 좌표(위경도) 입력

| Tool | 설명 | 호출 API |
| --- | --- | --- |
| `get_nowcast_observation` | 현재 관측 (기온/강수/습도/풍속) | `VilageFcstInfoService_2.0/getUltraSrtNcst` |
| `get_nowcast_forecast` | 초단기(약 6시간) 예보 | `VilageFcstInfoService_2.0/getUltraSrtFcst` |
| `get_short_term_forecast` | 단기(약 3~5일) 시간별 예보 | `VilageFcstInfoService_2.0/getVilageFcst` |

### 구역코드(`regId`) / 발표관서(`stnId`) 입력

| Tool | 설명 | 호출 API |
| --- | --- | --- |
| `get_short_term_land_forecast` | 단기 육상예보 텍스트 | `VilageFcstMsgService/getLandFcst` |
| `get_short_term_sea_forecast` | 단기 해상예보 텍스트 | `VilageFcstMsgService/getSeaFcst` |
| `get_weather_situation` | 기상개황 (`stnId` 입력) | `VilageFcstMsgService/getWthrSituation` |
| `get_mid_term_forecast` | 중기 육상예보 (4~10일, 하늘상태/강수확률) | `MidFcstInfoService/getMidLandFcst` |
| `get_mid_term_temperature` | 중기 최저/최고 기온 예보 | `MidFcstInfoService/getMidTa` |

### 전국 단위 / 영향예보

| Tool | 설명 | 호출 API |
| --- | --- | --- |
| `get_active_warnings` | 현재 발효 중인 기상특보 (전국 또는 `regId` 필터) | `wrn_now_data.php` |
| `get_impact_forecast` | 폭염(`hw`)/한파(`cw`) 영향예보 위험수준 | `ifs_fct_pstt.php` |

### 구역코드 검색 도우미

| Tool | 설명 | 호출 API |
| --- | --- | --- |
| `lookup_forecast_zone` | 단기/중기 예보용 `regId` 검색 (이름/코드) | `FcstZoneInfoService/getFcstZoneCd` |
| `lookup_warning_zone` | 특보용 구역코드 검색 (이름) | `WethrBasicInfoService/getWrnZoneCd` |

> 단기 육상 `regId`(예: `11B10101` 서울)와 중기 육상 `regId`(예: `11B00000` 서울/인천/경기)는 **체계가 다릅니다.** 어떤 `regId`를 써야 할지 모르면 `lookup_forecast_zone` 을 먼저 호출하세요.

## 설치 및 빌드

```bash
npm install
npm run build      # tsc → dist/
```

개발 중에는 빌드 없이 실행할 수 있습니다.

```bash
npm run dev        # tsx src/index.ts
```

## 환경변수

`.env` 파일 또는 프로세스 환경에 다음 값을 설정합니다 (`.env.example` 참고).

| 이름 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KOREA_WEATHER_API_KEY` | O | - | [기상청 API 허브](https://apihub.kma.go.kr/)에서 발급받은 인증키. 모든 호출의 `authKey` 쿼리 파라미터로 전달됩니다. URL 인코딩된 키여도 자동으로 디코딩됩니다. |
| `MCP_API_KEY` | HTTP 모드에서 O | - | HTTP 요청 인증에 사용되는 `x-api-key` 헤더 값. HTTP 모드 실행 시 필수. |
| `HOST` | X | `127.0.0.1` | HTTP 서버 바인딩 호스트 |
| `PORT` | X | `8081` | HTTP 서버 포트 |
| `TRANSPORT` | X | `http` | `stdio`로 지정하면 stdio 모드로 실행 |

## 실행

### Stdio 모드 (MCP 클라이언트 직접 연동)

```bash
node dist/index.js --stdio
# 또는
TRANSPORT=stdio node dist/index.js
```

Claude Desktop 등 MCP 클라이언트의 설정 예시:

```json
{
  "mcpServers": {
    "korea_weather": {
      "command": "node",
      "args": ["/absolute/path/to/dist/index.js", "--stdio"],
      "env": {
        "KOREA_WEATHER_API_KEY": "발급받은-기상청-API-허브-인증키"
      }
    }
  }
}
```

### HTTP 모드 (Streamable HTTP)

```bash
npm start
# [korea_weather] MCP server listening on http://127.0.0.1:8081/mcp
```

`/mcp` 엔드포인트는 `x-api-key` 헤더 인증을 요구합니다. `MCP_API_KEY`가 설정되어 있지 않으면 서버가 시작되지 않으며, 헤더 비교는 `crypto.timingSafeEqual`로 수행됩니다.

```bash
curl -X POST http://127.0.0.1:8081/mcp \
  -H "Content-Type: application/json" \
  -H "x-api-key: $MCP_API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 발표 시각 자동 계산

각 좌표 기반 도구는 호출 시점에 발표 스케줄을 자동 보정합니다.

- 초단기실황: 매시 40분 이전이면 직전 시간의 정시 자료
- 초단기예보: 매시 45분 이전이면 직전 시간의 30분 발표 자료
- 단기예보: `02/05/08/11/14/17/20/23`시 발표 중 가장 최근(발표 후 10분 경과). 새벽 02시 이전이면 전일 23시 발표
- 중기예보: 매일 06시·18시 발표 중 가장 최근. 새벽 06시 이전이면 전일 18시 발표

## 좌표 변환

기상청 좌표 기반 API는 위경도가 아닌 격자 좌표(nx, ny)를 입력으로 요구합니다. `src/grid.ts`는 기상청에서 제공하는 Lambert Conformal Conic 파라미터(원점 126°E / 38°N, 표준위도 30° / 60°, 격자 간격 5km)를 그대로 적용해 위경도를 격자 좌표로 변환합니다.

## 출력 포맷

모든 도구는 `content: [{ type: "text", text: ... }]` 형태로 한국어 텍스트를 반환합니다.

- 강수형태(PTY): 비/비눈/눈/소나기/빗방울/빗방울눈날림/눈날림
- 하늘상태(SKY): 맑음/구름많음/흐림
- 풍향: 16방위로 변환 (초단기 예보는 영문 약어, 단기 예보는 한글)
- 기상특보 종류: W=강풍·R=호우·C=한파·D=건조·O=해일·N=지진해일·V=풍랑·T=태풍·S=대설·Y=황사·H=폭염·F=안개
- 영향예보 위험수준(ILVL): 0=영향없음, 1=관심, 2=주의, 3=경고, 4=위험

## 오류 처리

- 네트워크 오류, 타임아웃(15초), HTTP 비정상 응답은 `API 요청 중 오류 발생: ...` 메시지로 반환
- 응답 본문이 JSON이 아닌 경우 `JSON 파싱 중 오류 발생: ...` 메시지와 응답 앞부분 200자 포함
- 기상청 API의 `resultCode`가 `00`이 아닌 경우 `API 오류: <code> - <msg>` 형태로 반환
- `KOREA_WEATHER_API_KEY` 미설정 시 명시적인 한국어 오류 메시지 반환

오류는 도구 호출이 실패(throw)하지 않고 텍스트 응답으로 전달되므로 클라이언트가 그대로 사용자에게 표시할 수 있습니다.

## 프로젝트 구조

```
src/
├── index.ts          # MCP 서버 부트스트랩 (stdio / HTTP transport, 인증 미들웨어, 도구 등록)
├── grid.ts           # 위경도 → 기상청 격자 좌표 변환 (Lambert Conformal Conic)
├── format.ts         # PTY/SKY/특보/영향예보 코드 매핑, 풍향 변환, 한국어 포매팅 헬퍼
└── api/
    ├── client.ts     # fetch 래퍼: authKey 주입, 타임아웃, JSON·CSV 파서, 한국어 오류 핸들러
    ├── short-term.ts # 단기/초단기 6개
    ├── mid-term.ts   # 중기 2개
    ├── warnings.ts   # 기상특보 현황 (CSV)
    ├── impact.ts     # 폭염/한파 영향예보 (CSV)
    └── zones.ts      # 구역코드 lookup 2개
```

## 라이선스 / 데이터 출처

- 코드: MIT License ([LICENSE](LICENSE))
- 날씨 데이터: 기상청 API 허브 (`apihub.kma.go.kr/api/typ02/openApi`, `apihub.kma.go.kr/api/typ01/url`)
