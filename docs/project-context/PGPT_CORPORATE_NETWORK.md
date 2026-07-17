> 생성일: 2026-07-12

# P-GPT와 회사 네트워크 연결 설계

## 목적

이 문서는 `.examples/MyHarness/`에서 실제로 동작한 P-GPT Provider, 회사 CA 인증서와 Web Search 경로를 분석하여 Lumina Agent에 적용할 설계 기준을 정의합니다.

MyHarness 코드를 Lumina의 구성요소로 사용하지는 않지만, 회사 환경에서 실제 연결에 필요한 프로토콜 계약은 Lumina에 구현합니다. 인증 payload 필드, 환경변수, CA 탐색과 HTTP client 동작은 저장소에 포함합니다. 실제 API Key·사번·인증서 원문은 포함하지 않고 설치 과정 또는 Secret으로 주입합니다.

## MyHarness에서 확인한 동작 원리

### P-GPT Provider

MyHarness의 P-GPT 연결은 다음 구조로 동작합니다.

```text
P-GPT Profile 선택
→ API Key + 사용자/시스템 식별자 + 회사 식별자 조회
→ 회사 P-GPT 규격의 인증 envelope 생성
→ Bearer token으로 OpenAI-compatible endpoint 호출
→ 응답을 공통 Agent Stream Event로 변환
```

일반 OpenAI Compatible Client의 message·Tool schema·stream parser를 재사용하되 P-GPT의 인증 생성, 고정 base URL과 진단 label을 별도로 적용합니다.

주요 참고 위치:

- `.examples/MyHarness/src/myharness/api/pgpt_auth.py`
- `.examples/MyHarness/src/myharness/api/openai_client.py`
- `.examples/MyHarness/src/myharness/ui/runtime.py`
- `.examples/MyHarness/src/myharness/config/settings.py`
- `.examples/MyHarness/tests/test_api/test_pgpt_auth.py`

### 회사 CA 인증서

MyHarness는 회사 CA 파일이 존재하면 공개 CA bundle과 회사 CA를 합친 runtime bundle을 생성합니다.

```text
certifi 또는 OS CA bundle
+ 회사 CA certificate
→ combined CA bundle
→ Python·httpx·OpenAI SDK·Node·curl·pip에서 사용
```

Python 관련 CA 환경변수와 Node 관련 CA 환경변수를 프로세스 초기에 설정하고, `httpx`에는 생성한 `SSLContext`를 명시적으로 전달합니다. 이 방식은 회사 TLS inspection 또는 사내 인증기관 때문에 공개 사이트 인증서 검증이 실패하는 문제를 `verify=False` 없이 해결하려는 접근입니다.

주요 참고 위치:

- `.examples/MyHarness/src/myharness/utils/certificates.py`
- `.examples/MyHarness/src/myharness/__init__.py`
- `.examples/MyHarness/tests/test_utils/test_certificates.py`

### Web Search와 Web Fetch

Web Search와 Web Fetch는 공통 HTTP fetch 함수를 사용합니다.

- HTTP/HTTPS scheme만 허용
- URL에 포함된 credential 거부
- DNS 결과가 public 주소인지 검사
- redirect를 자동 추종하지 않고 매 hop을 다시 검사
- 회사 CA가 적용된 `SSLContext` 사용
- timeout과 redirect 횟수 제한
- 외부 페이지를 명령이 아닌 신뢰하지 않는 데이터로 표시

주요 참고 위치:

- `.examples/MyHarness/src/myharness/utils/network_guard.py`
- `.examples/MyHarness/src/myharness/tools/web_search_tool.py`
- `.examples/MyHarness/src/myharness/tools/web_fetch_tool.py`
- `.examples/MyHarness/tests/test_tools/test_web_fetch_tool.py`

## Lumina의 P-GPT Provider

P-GPT는 일반 OpenAI Compatible의 단순 설정 alias가 아니라 별도 Provider Adapter로 유지합니다.

```text
apps/server/src/lumina/providers/pgpt/
├─ profile                 # endpoint·api mode·capability
├─ auth                    # 회사 인증 envelope 생성
├─ adapter                 # 공통 Provider 계약 구현
└─ diagnostics             # 비밀값 없는 연결 진단
```

실제 파일 구성은 구현 시 단순성을 고려해 합칠 수 있지만 책임 경계는 유지합니다.

### Provider Profile

P-GPT profile에는 다음 비밀이 아닌 설정을 둡니다.

- MyHarness와 동일한 P-GPT 기본 base URL 및 선택적 override
- Chat Completions·Responses 등 API mode
- deployment name과 사용자 표시 model name 매핑
- OpenAI-compatible streaming
- Tool Call, Structured Output, 이미지와 usage 지원 capability
- timeout, retry와 rate limit 정책
- 회사 CA bundle과 proxy profile 참조

P-GPT endpoint와 전체 API 경로는 기본적으로 MyHarness와 동일한 Provider 값을 사용합니다.

```text
http://pgpt.posco.com/s0la01-gpt/v1
```

`PGPT_BASE_URL`이 비어 있거나 설정되지 않으면 위 기본값을 자동 사용합니다. 일반 사용자는 입력할 필요가 없으며, 회사 환경 변경이나 테스트가 필요한 경우에만 관리자가 override합니다. 임의의 일반 OpenAI-compatible endpoint는 P-GPT가 아니라 `openai_compatible` Provider로 등록합니다.

### 인증

P-GPT 인증은 다음 실제 envelope 계약을 Adapter 내부에서 생성합니다.

```json
{
  "apiKey": "<PGPT_API_KEY>",
  "companyCode": "<PGPT_COMPANY_CODE>",
  "systemCode": "<PGPT_EMPLOYEE_NO>"
}
```

JSON을 UTF-8로 직렬화한 뒤 Base64로 인코딩하여 다음 header로 전송합니다.

```text
Authorization: Bearer <base64-json-envelope>
```

- 이 Base64 값은 암호화가 아니므로 credential과 동일하게 취급합니다.
- 인증 token을 DB의 일반 설정, session, Run event와 로그에 저장하지 않습니다.
- 사용자별 credential과 조직 service credential을 구분합니다.
- 공유 모드에서 Provider·Model 옵션은 공유해도 개인 credential은 공유하지 않습니다.
- 인증 header와 token은 오류 메시지, trace와 HTTP dump에서 redaction합니다.
- token 생성 함수는 순수 함수로 격리하고 가짜 값만 사용하는 단위 테스트를 둡니다.

### Credential 조회 순서

MyHarness는 P-GPT API Key와 employee/system code를 환경변수에서 읽을 수 있으며, 로컬 credential 파일이 있으면 이를 환경변수보다 우선합니다. Lumina의 회사 서버 기본 배포는 환경변수 또는 Secret mount를 원본으로 사용합니다.

서버형 Lumina에서는 다음 순서로 값을 결정합니다.

```text
1. 요청 사용자에게 명시적으로 연결된 사용자별 Secret reference
2. 배포 환경 Secret / environment variable의 조직 service credential
3. Project에 연결된 별도 service credential reference
4. 없으면 명확한 설정 오류
```

일반적인 회사 공용 P-GPT 운영은 2번 환경변수 경로만으로 동작합니다. 사용자별 과금·권한 분리가 필요한 조직에서만 1번을 사용합니다.

지원 환경변수:

```text
PGPT_API_KEY
PGPT_EMPLOYEE_NO
PGPT_COMPANY_CODE
PGPT_BASE_URL                 # 선택, 비어 있으면 기본 endpoint
```

MyHarness와 동일하게 사용자에게 노출하는 기본 환경변수는 `PGPT_EMPLOYEE_NO`입니다. P-GPT 요청 payload를 만들 때 이 값을 JSON의 `systemCode` 필드에 넣습니다. 즉 `systemCode`는 환경변수 이름이 아니라 회사 API가 요구하는 전송 필드명입니다.

기존 MyHarness 설정을 가져오는 migration에서만 과거 credential key 또는 `PGPT_SYSTEM_CODE`를 호환 입력으로 읽을 수 있습니다. 신규 설치, `.env.example`, 관리자 UI와 운영 문서는 `PGPT_EMPLOYEE_NO`만 사용합니다.

API Key와 사번의 실제 값은 `.env.example`이 아니라 `.env`, OS Secret, Kubernetes Secret 또는 회사 Secret Manager에 저장합니다. P-GPT 기본 endpoint와 회사 코드 `30`은 인증 비밀값이 아니므로 `.env.example`에 안전한 기본값으로 제공합니다.

저장소의 `.env.example`에는 비밀값의 빈 placeholder와 비민감 기본값만 제공하며, `.env`는 `.gitignore`로 제외합니다.

### 구현 가능한 인증 함수 계약

```python
def build_pgpt_auth_token(
    api_key: str,
    employee_no: str,
    company_code: str,
) -> str:
    payload = {
        "apiKey": api_key,
        "companyCode": company_code,
        "systemCode": employee_no,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
```

구현 시 입력값 공백, 누락과 최대 길이를 검증하고 반환 token을 로그에 남기지 않습니다.

### OpenAI 호환 Adapter

공통 OpenAI Compatible 기능을 재사용합니다.

- System·User·Assistant·Tool message 변환
- Tool schema를 OpenAI function 형식으로 변환
- streaming text와 Tool Call delta 누적
- Tool Call ID와 Tool Result 연결
- P-GPT가 거부하는 `response_format`은 제외하고 interactive output은 `max_completion_tokens` 42,000 이하로 제한
- 공식 전체 Context window와 실측 입력 Token 상한을 별도 capability와 관리자 설정으로 관리합니다. 2026-07-17 VS Code Codex 확장 경로 실측 기준 `gpt-5.4-mini`는 270,000 Token, `gpt-5.5`는 911,900 Token까지 입력 가능했습니다. `gpt-5.4`는 사용자 관측상 `gpt-5.5`와 같은 계열로 추정하여 911,900 Token을 임시 상한으로 적용합니다. 관리자 화면에서 실측값을 바꿔도 공식 전체 Context 값은 유지합니다. Lumina 자체 System prompt와 Tool schema도 입력을 소비하므로 실제 대화 Context 예산에서는 두 값 중 작은 한도에서 Tool schema와 안전 여유를 추가로 제외합니다.
- `stream_options.include_usage`, 안정적인 `prompt_cache_key`와 retention 전달
- usage와 cached token 정규화
- retry 가능한 timeout·network·429·5xx 분류
- 인증·권한·rate limit·일반 요청 오류 구분

지원하지 않는 optional parameter가 있을 때는 해당 옵션만 비활성화하고 재시도할 수 있지만, Provider가 거부한 필드와 fallback 결과를 비밀값 없이 기록합니다.

## 회사 CA Trust Manager

회사 인증서는 Provider별 임시 처리가 아니라 Backend와 Worker의 공통 Trust Manager에서 관리합니다.

```text
Corporate Trust Manager
├─ configured company roots
├─ public CA bundle
├─ combined runtime bundle
├─ Python SSLContext
├─ subprocess environment
└─ health diagnostics
```

### 인증서 위치

```text
Windows 개발
├─ data/certs/company-ca.crt
└─ C:/POSCO_CA.crt             # 기존 회사 PC 호환 fallback

Linux 운영
└─ /run/secrets/lumina/company-ca.crt

Kubernetes
└─ read-only Secret 또는 승인된 ConfigMap volume
```

기본 경로는 `LUMINA_CA_CERT`로 설정합니다. 값이 없을 때는 `data/certs/company-ca.crt`, 기존 회사 PC 호환을 위한 `C:/POSCO_CA.crt` 순서로 탐색할 수 있습니다. 실제 인증서는 Git에 커밋하지 않습니다.

### Bundle 생성

1. certifi 또는 OS 기본 CA bundle을 찾습니다.
2. 회사 CA certificate chain을 읽습니다.
3. 중복을 피하고 public CA + company CA를 결합합니다.
4. `data/certs/runtime/` 또는 OS 임시 영역에 atomic write합니다.
5. 파일 권한을 현재 서비스 계정으로 제한합니다.
6. bundle을 사용해 `SSLContext`를 생성합니다.
7. 모든 HTTP Client Factory와 허용된 subprocess에 동일한 trust profile을 전달합니다.

회사 CA만 단독으로 사용하면 일반 공개 사이트 인증이 실패할 수 있으므로 공개 CA와 결합하는 것이 중요합니다.

### 적용 대상

Python process에는 필요에 따라 다음 표준 환경을 제공합니다.

```text
SSL_CERT_FILE
REQUESTS_CA_BUNDLE
CURL_CA_BUNDLE
PIP_CERT
```

Node 기반 도구에는 다음 설정을 제공합니다.

```text
NODE_EXTRA_CA_CERTS
npm_config_cafile
```

Lumina가 지원할 인증서 환경변수:

```text
LUMINA_CA_CERT                 # 회사 CA 또는 chain 파일
LUMINA_CA_BUNDLE              # 미리 생성된 combined bundle 선택값
LUMINA_TLS_COMPAT_MODE        # 회사 CA 설치 시 true, 그 외 기본 false
HTTPS_PROXY                   # 직접 신뢰하지 않고 명시 proxy profile로 가져올 후보
NO_PROXY                      # 관리자 검증 후 적용
```

단, 환경변수만 믿지 않습니다. Lumina가 생성하는 `httpx.AsyncClient`와 Provider SDK의 custom HTTP client에는 동일한 `SSLContext`를 명시적으로 전달합니다. subprocess에는 허용된 CA 관련 환경변수만 명시적으로 전달합니다.

### 초기화 순서

Trust Manager는 Provider, MCP, Web Search와 외부 HTTP client가 생성되기 전에 초기화해야 합니다.

```text
설정과 Secret mount 확인
→ CA bundle 생성·검증
→ HTTP Client Factory 생성
→ Provider·MCP·Web Tool 초기화
→ readiness 성공
```

인증서 설정이 필수인 배포 profile에서 초기화가 실패하면 readiness를 실패시키고 사용자에게 원인을 알립니다. 조용히 TLS 검증을 끄지 않습니다.

## TLS 보안 원칙

### 금지

- `verify=False`
- 인증서 오류를 catch한 뒤 검증 없이 재시도
- 회사 CA 또는 private key를 저장소와 이미지에 포함
- 인증 token·header·certificate 내용을 로그에 출력
- 모든 domain에 무제한으로 약한 TLS 설정 적용

### 구형 회사 TLS 호환

POSCO TLS inspection chain은 OpenSSL 3 strict verification에서 `Missing Authority Key Identifier`로 실패할 수 있습니다. 회사 CA를 발견한 설치에서는 해당 trust profile에 한해 MyHarness와 같은 호환 경로를 활성화합니다.

우선순위는 다음과 같습니다.

1. public CA와 승인된 회사 CA chain을 결합
2. 해당 trust profile의 cipher list를 `DEFAULT@SECLEVEL=1`로 설정
3. `VERIFY_X509_STRICT`만 해제하고 hostname·유효기간·서명 검증은 유지
4. Python HTTP client와 허용된 Node subprocess에 같은 profile 전달

Compatibility mode는 회사 CA가 실제로 구성된 profile에만 적용합니다. 회사 CA가 없는 일반 설치는 public CA 기본 context를 유지하며, 어떤 경우에도 `verify=False`로 재시도하지 않습니다. 진단 결과에는 compatibility mode 활성 여부를 표시합니다.

## Web Search와 Corporate HTTP Client

CA bundle은 TLS 인증 문제를 해결하지만 proxy, 방화벽, DNS와 egress 정책까지 자동으로 해결하지는 않습니다. Web Search는 다음 profile을 구분합니다.

Lumina의 `public_web` 기본 검색 Backend는 DuckDuckGo입니다. 별도 관리자 설정이 없는 일반 개발·운영 환경에서는 DuckDuckGo를 사용하고, 배포 환경의 정책으로 접근할 수 없을 때만 승인된 대체 Backend를 선택합니다. Backend 선택과 무관하게 아래의 TLS, SSRF, redirect와 egress 검증을 동일하게 적용합니다.

```text
public_web
├─ 공개 DNS/IP만 허용
├─ redirect hop별 SSRF 검사
└─ 회사 CA 또는 명시 proxy 사용

corporate_web
├─ 관리자 allowlist의 사내 domain만 허용
├─ 승인된 private IP range만 허용
├─ 회사 CA와 proxy profile 사용
└─ 사용자 임의 URL 접근 금지
```

MyHarness의 public guard는 private IP를 모두 차단하므로 인터넷 검색에는 안전하지만 사내 검색 backend를 호출하려면 별도 allowlist 정책이 필요합니다. private IP 차단을 제거하는 방식으로 해결하지 않습니다.

### HTTP Client Factory

Web Search, Web Fetch, MCP HTTP와 Provider는 공통 Factory에서 client를 받습니다.

```text
create_http_client(
  trust_profile,
  egress_policy,
  proxy_profile,
  timeout,
  redirect_policy,
)
```

- `trust_env=False`를 기본으로 해 예상하지 못한 사용자 proxy 환경 주입을 막습니다.
- 회사 proxy가 필요하면 관리자 설정의 명시적 proxy profile을 사용합니다.
- redirect는 client 자동 추종 대신 애플리케이션이 hop마다 검증합니다.
- DNS rebinding을 줄이기 위해 검증된 주소와 실제 연결 대상을 가능한 범위에서 일치시킵니다.
- response body 크기와 content type을 제한합니다.
- 외부 HTML은 prompt instruction이 아닌 untrusted data로 표시합니다.

### 검색 Backend 선택

기본 선택과 대체 순서는 다음과 같습니다.

1. DuckDuckGo 공개 검색 Backend
2. 회사 승인 Search Connector 또는 API
3. 회사 proxy를 통한 승인된 Search API
4. 관리자가 허용한 다른 공개 Search endpoint
5. Browser automation fallback

DuckDuckGo가 회사 정책, 네트워크 또는 일시적 장애로 실패했다고 해서 임의의 검색 사이트로 조용히 전환하지 않습니다. 대체 Backend는 관리자 정책과 allowlist에 포함되어야 하며, 사용자에게 현재 사용된 Backend 또는 검색 제한 상태를 알립니다.

현재 활성 Backend는 `duckduckgo_html` 하나입니다. 검색 도구는 Backend protocol 경계를 통해 호출하여 공급자 구현을 분리합니다. **Vertex AI 기반 Google 검색은 향후 추가 예정이지만 현재는 미구현·비활성 상태**이며, 이름만 설정하거나 자동 fallback 대상으로 사용하지 않습니다. 추후 Vertex adapter, 인증·과금·조직 egress 정책과 관리자 명시 활성화를 함께 구현한 뒤 별도 Backend로 등록합니다. 기존 Run은 snapshot에 기록된 Backend를 유지하고, 새 Backend 발견이나 코드 배포만으로 자동 전환하지 않습니다.

Web Search 실패 시 “인증서 문제”로 단정하지 않고 DNS, proxy, TLS, HTTP status와 content policy 단계로 진단합니다.

## 사용자·관리자 UX

### 관리자 설정 화면

- P-GPT 고정 endpoint 연결 상태
- 배포명·Model mapping
- 회사 CA 파일 상태와 만료 정보
- public CA와 company CA bundle 생성 상태
- proxy profile
- Web Search backend와 egress allowlist (`duckduckgo` 기본값)
- Provider·Search 연결 테스트

### 연결 테스트 결과

```text
DNS resolution
TCP connection
TLS handshake and certificate chain
Proxy authentication
HTTP authentication
API endpoint and deployment mapping
Streaming
Tool Call capability
Web Search request
```

“연결 실패” 하나로 합치지 않고 실패 단계를 구분합니다. 사용자에게 인증 token이나 내부 응답 전문을 노출하지 않습니다.

### 일반 사용자 UX

- P-GPT 사용 가능 여부와 관리자 조치 필요 여부
- 선택 가능한 deployment/model
- 인증 만료 또는 사용자 식별자 누락 안내
- Web Search가 회사 정책 때문에 제한된 경우 대체 Search backend 안내
- 인증서 오류와 네트워크 차단을 구분한 메시지

## 배포 환경

### Windows 개발

- 실제 CA는 `data/certs/`에 배치하고 Git에서 제외합니다.
- `installer.bat` 또는 관리자 설정을 통해 경로만 등록합니다.
- Backend와 Node 개발 server가 같은 CA chain을 사용하게 합니다.
- Windows certificate store 자동 import는 관리자 동의 없이 수행하지 않습니다.
- `installer.bat`는 P-GPT 사용 여부, employee number, company code와 CA 경로를 입력받고 API Key는 안전한 credential 저장소 또는 `.env`에 저장합니다. Base URL은 고급 설정에서만 선택적으로 변경합니다.
- 설치 완료 후 DNS → TLS → 인증 → model 목록 또는 health endpoint → stream 순서로 연결 테스트를 실행합니다.

### Linux 서버

- CA와 credential을 read-only Secret으로 mount합니다.
- 가능하면 OS trust store를 운영팀 표준 방식으로 구성합니다.
- 앱 전용 bundle도 생성해 Python SDK와 subprocess 동작을 일치시킵니다.
- 서비스 계정의 파일 읽기 권한과 certificate rotation을 확인합니다.

### Kubernetes

- CA, Provider secret과 proxy credential을 image에 넣지 않습니다.
- Secret/ConfigMap volume과 Secret reference를 사용합니다.
- CA rotation 시 새 Pod rollout 또는 안전한 Trust Manager reload를 수행합니다.
- readiness에서 P-GPT와 Search의 필수 의존성을 구분합니다. Search 장애가 전체 Chat을 막아야 하는지는 배포 정책으로 결정합니다.

## 테스트 요구사항

### 인증서

- CA 파일이 없을 때 명확한 상태 반환
- public CA + company CA bundle 생성
- atomic write와 파일 권한
- `SSLContext`가 combined bundle 사용
- Python·Node subprocess 환경 전달
- 만료·잘못된 PEM·불완전 chain 오류
- compatibility mode가 기본적으로 꺼져 있음

### P-GPT

- 가짜 credential로 인증 envelope 생성
- 사용자/시스템 식별자 누락 오류
- base URL path 보존
- Model/deployment mapping
- text stream과 Tool Call delta 정규화
- unsupported optional parameter fallback
- token·header log redaction

### Web Search

- 별도 설정이 없을 때 DuckDuckGo Backend 선택
- DuckDuckGo 제한 시 승인된 대체 Backend만 선택
- 회사 CA가 필요한 TLS test server 연결
- embedded credential 거부
- loopback·private IP 거부
- corporate allowlist만 private target 허용
- redirect hop마다 재검증
- redirect를 이용한 public→private 우회 차단
- timeout·body 크기·redirect 한도
- 외부 콘텐츠 untrusted banner
- proxy 필요·인증 실패·TLS 실패의 오류 분류

## 구현 우선순위

### 1단계

1. 공통 Trust Manager와 combined CA bundle
2. P-GPT 전용 Provider profile과 인증 Adapter
3. OpenAI Compatible text streaming
4. 공통 HTTP Client Factory
5. DuckDuckGo 기본 public Web Search의 CA 적용과 SSRF guard
6. 관리자 연결 진단

### 2단계

1. Tool Call·usage·Structured Output capability
2. explicit corporate proxy profile
3. corporate Search backend allowlist
4. certificate rotation과 Kubernetes Secret 연동
5. Provider별 호환성 profile

### 3단계

1. 조직별 P-GPT deployment 정책
2. 사용자 credential과 service credential 선택 정책
3. 운영 Dashboard와 TLS·Search 상태 모니터링

## 수용 기준

1. 별도 검색 Backend 설정이 없는 환경에서는 DuckDuckGo가 기본 Web Search로 선택됩니다.
2. 회사 CA가 필요한 환경에서도 P-GPT와 승인된 공개 Web Search가 TLS 검증을 유지한 채 동작합니다.
3. 회사 CA를 추가해도 일반 공개 CA 사이트 연결이 깨지지 않습니다.
4. P-GPT 인증 세부 정보와 실제 endpoint가 저장소·로그·Run event에 노출되지 않습니다.
5. `verify=False` 없이 연결됩니다.
6. 공개 Web Tool은 redirect를 포함해 private target 접근을 차단합니다.
7. 사내 private Search는 관리자 allowlist가 있을 때만 별도 corporate profile로 접근합니다.
8. Windows 개발과 Linux/Kubernetes 운영에서 같은 Provider·Trust 계약을 사용합니다.
9. 연결 실패가 DNS·proxy·TLS·인증·endpoint·stream 단계로 구분되어 표시됩니다.

## 회사에서 바로 실행하기 위한 설치 계약

Lumina 구현이 완료되면 회사 Windows PC에서 다음 흐름만으로 실행 가능해야 합니다.

```text
installer.bat
→ P-GPT profile 선택
→ API Key 입력
→ employee number 입력
→ company code 입력
→ CA 파일 자동 탐색 또는 경로 선택
→ combined CA bundle 생성
→ P-GPT 및 Web Search 연결 테스트
→ run_lumina.bat 실행
```

Linux 서버에서는 같은 설정을 환경변수와 Secret mount로 주입합니다.

```text
PGPT_API_KEY=<secret>
PGPT_BASE_URL=http://pgpt.posco.com/s0la01-gpt/v1
PGPT_EMPLOYEE_NO=<service-or-user-employee-number>
PGPT_COMPANY_CODE=30
LUMINA_CA_CERT=/run/secrets/lumina/company-ca.crt
```

이 계약은 “설계 참고”가 아니라 실제 구현과 E2E 테스트의 완료 기준입니다. P-GPT endpoint 기본값은 Provider에 포함하고 `PGPT_BASE_URL`은 선택적 관리자 override로만 사용합니다.
