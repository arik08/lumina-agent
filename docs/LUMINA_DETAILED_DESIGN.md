# Lumina Agent 통합 상세 설계안

> 문서 상태: 통합 기준안
> 작성일: 2026-07-11
> 최종 동기화: 2026-07-17 (현재 source 작업 트리와 migration `0030` 기준)
> 적용 범위: Lumina Agent 제품, Frontend, Backend, Agent Worker, 확장 시스템과 운영 환경
> 구현 상태: 이 문서는 설계 문서의 통합본이며, 각 항목의 실제 구현 완료 여부를 뜻하지 않습니다.

## 1. 문서 목적과 적용 원칙

이 문서는 루트 `README.md`에 있던 초기 설계 내용과 루트 `AGENTS.md`, `docs/project-context/`의 설계·조사·요구사항을 하나의 구현 기준으로 통합합니다. 기존 문서에 반복되어 있던 세션 복구, 공유, Artifact, Agent Loop, Project, Provider, Marketplace와 목적별 UI 요구사항은 여기서 하나의 계약으로 정리합니다. 현재 `README.md`는 제품 구조와 사용법을 안내하는 사용자 진입 문서이며 독립적인 상세 설계 원본으로 사용하지 않습니다.

이 문서의 목표는 다음과 같습니다.

1. 제품의 사용자 경험과 내부 아키텍처를 한 문서에서 추적할 수 있게 합니다.
2. 같은 개념에 사용된 서로 다른 용어와 범위를 명확히 구분합니다.
3. Frontend, Backend와 Agent Worker가 공유해야 할 데이터·상태·이벤트 계약을 구체화합니다.
4. 개발용 단일 장비에서 운영용 PostgreSQL·Redis·Object Storage·Kubernetes 구성으로 확장 가능한 경계를 고정합니다.
5. 보안, 권한, 복구, 감사와 실제 브라우저 검증을 기능 구현의 일부로 취급합니다.

### 1.1 기준 문서 우선순위

요구사항이 겹치면 다음 순서로 해석합니다.

1. 시스템·조직 보안 정책과 법적 요구사항
2. 루트 `AGENTS.md`의 프로젝트 불변 조건
3. 이 통합 상세 설계안
4. 기능별 상세 문서
5. 루트 `README.md`의 제품 개요와 사용 안내
6. `.examples/`의 참고 구현

기능별 상세 문서는 배경, 조사 근거와 세부 수용 기준을 보존하는 원문입니다. 이 문서는 그 내용을 삭제하거나 대체하지 않고 구현 시 사용할 통합 구조를 제공합니다. README와 상세 설계가 충돌하면 이 문서를 기준으로 README의 요약이나 사용 안내를 갱신합니다. `.examples/`는 참고 전용이며 import, build, test, package 또는 deployment 대상이 아닙니다.

### 1.2 통합한 원문

| 문서 | 이 문서에 통합한 핵심 내용 |
|---|---|
| [`README.md`](../README.md) | 초기 제품 개요와 저장소·Provider·다중 사용자·DB·배포 방향. 현재는 제품 구조와 사용법을 요약하는 진입 문서로 유지 |
| [`PRODUCT.md`](../PRODUCT.md) | 사용자, 제품 목적, 절제된 Brand Personality, 상태·권한을 숨기지 않는 UI와 접근성 원칙 |
| [`AGENT_LOOP.md`](project-context/AGENT_LOOP.md) | Run 상태, Tool Loop, Queue, replay, streaming, steer, pause·resume·retry |
| [`AUTH_AND_CONVERSATION_SHARING.md`](project-context/AUTH_AND_CONVERSATION_SHARING.md) | ID/PW 인증, 관리자, 사용자 격리, 대화 snapshot 공유, 감사 |
| [`COWORK_FEATURE_REQUIREMENTS.md`](project-context/COWORK_FEATURE_REQUIREMENTS.md) | Project, Plan, Workspace, 전문 산출물, 예약 작업, Live Artifact |
| [`EXTENSION_MARKETPLACE.md`](project-context/EXTENSION_MARKETPLACE.md) | Skill·MCP·Plugin 카탈로그, 불변 버전, 설치·검토·폐기 |
| [`HERMES_USER_FEATURES.md`](project-context/HERMES_USER_FEATURES.md) | 세션 UX, 검색·분기·내보내기, 알림, 사용량, `@`·`$` Composer |
| [`MANUS_DESIGN_LESSONS.md`](project-context/MANUS_DESIGN_LESSONS.md) | 실행 환경, 복원 가능한 Context, Batch Fan-out, 승인형 학습, 권한 Lease |
| [`myharness_feature_requiorements.md`](project-context/myharness_feature_requiorements.md) | 답변 Action Bar, Artifact 패널, Renderer, 편집·버전·다운로드 |
| [`PGPT_CORPORATE_NETWORK.md`](project-context/PGPT_CORPORATE_NETWORK.md) | P-GPT 인증, 회사 CA, HTTP Client, Web Search, 설치 진단 |
| [`PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md`](project-context/PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md) | 교체 가능한 Agent Frontend와 공통 Frontend 계약 |
| [`INSTALLATION_AND_DIAGNOSTICS.md`](project-context/INSTALLATION_AND_DIAGNOSTICS.md) | Windows 설치, 조건부 Artifact renderer, 진단 CLI, PostgreSQL 호환성, 개발 검증과 격리 포트 |
| [`lumina_skill_management_design.md`](lumina_skill_management_design.md) | 개인 작업본, Creator·Owner 분리, Merge·Change Request·Publish·Rollback과 Skill Evolution 방향 |
| [`2026-07-12-general-document-rag-design.md`](superpowers/specs/2026-07-12-general-document-rag-design.md) | 조직 전용 GraphRAG를 일반 로컬 문서 RAG MCP로 전환하는 목표 계약 |
| [`2026-07-12-login-development-account-icon-design.md`](superpowers/specs/2026-07-12-login-development-account-icon-design.md) | 개발 build 전용 Bootstrap 계정 입력 helper의 절제된 접근성 UI |

### 1.3 문서 분류와 구현 상태 판정

문서가 존재한다는 이유만으로 현재 지원 기능으로 간주하지 않습니다. 상태 판정은 다음 순서를 사용합니다.

1. 이 문서와 루트 `AGENTS.md`는 제품 계약의 원본입니다.
2. 실제 route, model, migration, Frontend와 통과하는 회귀 test가 있으면 `Implemented`입니다.
3. 승인된 기능 상세 문서가 있지만 source가 아직 이전 계약이면 `Target`입니다.
4. 평가 보고서, 조사 문서와 구현 plan은 근거·Roadmap이며 현재 지원을 주장하지 않습니다.

2026-07-17 동기화 시점의 주요 상태는 다음과 같습니다.

| 영역 | 상태 | 근거와 해석 |
|---|---|---|
| 가입 신청·관리자 승인 | Implemented | `POST /api/auth/register`, `invited` 상태, 관리자 알림·승인 UI와 Backend test가 존재 |
| Skill 사용자별 WorkingDraft·복수 Owner | Implemented | migration `0019`, `SkillOwnership`, Draft 생성·저장·활성화 API와 회귀 test가 존재 |
| 동적 업무 계획·Codex OAuth·prompt cache | Implemented | `update_plan`, `work_plan_updated`, Codex App Server catalog와 Provider별 cache payload test가 존재 |
| 대화 좋아요·Composer 중단·예약 작업 삭제·복원 loading | Implemented | 현재 Backend·Frontend와 UI 계약 test에 반영되어 있으며 삭제는 물리 삭제가 아닌 보관 처리 |
| 일반 문서 RAG MCP | Target | 새 설계는 일반 문서·자연 위치 계약이지만 현재 `vector_db` source와 Skill은 아직 Markdown 조직 문서·`explore_org` 계약 |
| Skill Change Request·Blob/Tree CAS·자동 Eval | Target | 개인 Draft·복수 Owner 기반은 구현되었으나 진화 pipeline과 저장 최적화는 후속 단계 |

`lumina_agent_assessment_report_2026-07-12.html`은 해당 날짜의 정적 평가 snapshot입니다. 이후 source·test로 해소된 항목의 현재 상태를 이 보고서의 수치로 다시 판정하지 않습니다.

### 1.4 현재 구현 상세 인벤토리

아래 표는 2026-07-17의 migration `0001`~`0030`, 현재 route·service·Frontend source와 회귀 test로 확인한 실제 구현 범위입니다. `Implemented`는 source가 존재하고 해당 계약 test가 있다는 뜻이며 운영 규모·보안 심사·실사용 품질까지 완료되었다는 뜻은 아닙니다.

| 영역 | 구현된 세부 기능 | 주요 source·test 근거 |
|---|---|---|
| 인증·가입 | idempotent Bootstrap admin과 기본 catalog seed, login ID 정규화, 사용자별 Default Project 자동 생성, 로그인 실패 count·잠금 복구, 다음 Asia/Seoul 자정 만료 server session, CSRF, production secure cookie, idempotent logout, `invited` 가입 신청과 관리자 승인 알림 | `auth/service.py`, `routes/auth.py`, `test_auth_core.py`, `test_registration_approval.py` |
| 관리자 | 사용자 생성·조회·수정·비밀번호 reset·role/status 변경, 마지막 active admin 보호, 조직 범위 사용량 통계, 다른 사용자 대화·Turn Set 감사 조회, audit event 검색, 공유 링크 목록과 token 비노출 강제 revoke, 조직 Run 안전 한도 설정과 비상 전체 중단 | `routes/admin.py`, `test_admin_api.py`, `test_admin_share_revoke.py`, `test_run_safety.py` |
| Project·지침 | Project CRUD와 Default 삭제 방지, owner·editor·viewer membership 생명주기와 조직 격리, Organization→Agent default→Project→Personal 지침 합성, 관리자용 고정 system·Agent 기본 프롬프트 override와 기본값 복원, Run snapshot 고정, 사용자에게 노출하지 않는 revision·digest·ETag 동시성, 프로젝트 쓰기 구성원의 지침 편집, 조직 지침 과거 revision label·내용 수정, Secret 패턴 차단 | `projects/`, `routes/project_memberships.py`, `instructions/`, `test_project_memberships.py`, `test_instruction_hierarchy.py` |
| Project File·Workspace | Project 파일 upload·목록·상세·rename·새 version·download·삭제, 안전한 상대 경로, content hash와 immutable version, DB commit 실패 시 storage cleanup, Composer와 Run의 exact file version 고정, `read_file`·`write_file`·`glob` Project scope 강제 | `project_files/`, `tools/workspace.py`, `test_project_workspace.py`, `test_workspace_tools.py` |
| Conversation | favorite 우선 cursor 목록, 좋아요 filter·보존, whitespace-tolerant 제목 검색, Message 본문 검색과 snippet, Turn Set 역방향 pagination·이전 묶음 선행 로딩, revision CAS와 no-op PATCH 차단, first Run 임시·모델 제목, Project 이동과 Session-owned asset 이동, 특정 Message 기준 분기, JSON·Markdown 내보내기, builtin Agent Frontend contract 저장·fallback | `routes/conversations.py`, `conversations/service.py`, `agent_frontends/`, `test_conversation_listing.py`, `test_conversation_branch_export.py`, `test_agent_frontend_contract.py` |
| 공유·Message 상호작용 | 특정 Message까지의 immutable snapshot 공유, attachment·Artifact version 고정, token hash 저장, owner·admin revoke와 공유 download 권한, Message reference 조회, like/dislike upsert·취소, 문제 신고, 선택 문장 Comment CRUD와 stale anchor | `routes/sharing.py`, `routes/messages.py`, `test_conversation_sharing_api.py`, `test_message_memory_interactions.py` |
| Agent Run·Plan | Conversation 단위 single active Run과 다른 Conversation 병렬 실행, durable Queue와 `queue_next` 승격, SSE snapshot·Last-Event-ID replay, worker restart 복구, pause·resume·cancel·retry, 계정별 확인 질문 mode와 `awaiting_input` checkpoint·재개, model Turn·총 Token·경과 시간·예상 비용 한도, 모델 `update_plan`, stable Step ID, Tool Subtask, 독립 Tool 병렬 실행, approval 대기·승인·거부 | `runs/`, `agent/executor.py`, `test_run_concurrency_replay.py`, `test_worker_recovery.py`, `test_plan_lifecycle.py`, `test_tool_approvals.py`, Frontend clarification tests |
| Context·Memory | recoverable compaction, Tool Call/Result pair·side effect 보존, 실패 시 원 Context 유지, 모델별 Context budget, 사용자 Memory 후보·자동/확인/끔 mode, 민감정보 차단, relevant subset recall, LLM 최적화와 provenance 병합, Project learning proposal approve·reject·apply·rollback | `context/`, `memories/`, `project_memories/`, `test_context_compaction_memory_learning.py`, `test_project_memory_learning.py` |
| Provider | Mock·P-GPT·OpenAI Responses·Anthropic·Gemini·OpenAI Compatible adapter, multimodal image 입력, Tool roundtrip, typed·redacted 오류, 공통 base URL·Retry-After 검증, 관리자 Model discovery·명시 활성화·공식 Context와 실측 입력 상한 분리, revision 기반 사용자·Project 실행 선택 저장, Codex ChatGPT OAuth App Server·warm client·transport retry·API key 제거, 사용자 hash prompt-cache routing | `providers/`, `routes/providers.py`, `routes/admin_providers.py`, `test_provider_http.py`, `test_model_output_limits.py`, `test_settings_revision_cas.py` |
| Web Search·인용 | DuckDuckGo 기본 search와 교체 가능한 Backend 경계, readable HTML fetch, 최신·고위험 질의의 필수 조사 정책, query 목적·상위 검색 이력, search snippet→fetched evidence 승격, source hash·번호 안정화, cited·reviewed·search-only·미검증 UI 상태 | `tools/web.py`, `citations.py`, `test_web_tools.py`, `test_citations.py`, `source-evidence-status.test.mjs` |
| Attachment·Artifact | TXT·Markdown·HTML·CSV·TSV·PDF·DOCX·PPTX·XLSX extraction과 자연 locator, fake Office 거부와 OpenXML 관계 XML 안전 파싱, Artifact immutable version·restore, 사용자별 Draft·current version ETag/CAS, stale·provenance 보호, DB 실패·경합 시 새 storage blob 보상 정리, 손상되거나 누락된 원본의 명시 오류, Preview·download, HTML 원문 보존, DOCX·XLSX·PPTX·PDF·HTML·Markdown 생성, Codex image와 복합 asset embedding | `attachments/`, `artifacts/`, `test_attachment_extraction.py`, `test_artifact_draft_cas.py`, `test_artifact_storage_cleanup.py`, `test_artifact_render_validation.py` |
| Artifact 검증 | binary signature·재개봉, OpenXML macro·외부 hyperlink 차단, PDF link·page geometry 검사, LibreOffice 격리 profile과 Poppler page render, blank·비정상 크기·page count mismatch·timeout 실패 판정, renderer 미설치 시 `structural_passed`와 pending 구분 | `artifacts/render_validation.py`, `test_artifact_validation.py`, `test_artifact_render_validation.py` |
| Skill Marketplace | Private Skill 생성, 사용자별 WorkingDraft checkout·revision·activate와 atomic revision CAS, stale base version save 차단, immutable version save·publish, account별 installation, catalog tag, Folder CRUD·move, creator와 복수 Owner·Maintainer 분리, primary Owner 제거 방지, exact draft/version digest를 Run·예약 Run에 고정, 설치 Skill Markdown 기본 보기·상세 history navigation | `extensions/`, migration `0019`, `test_extensions_schedules.py`, `test_composer_run_references.py`, Marketplace Frontend tests |
| MCP | 관리자 definition·revision·approval·status, 사용자·Project installation, Secret reference bind/unbind, repository-relative manifest와 literal Secret 금지, stdio lifecycle·Tool allowlist·schema drift 차단, streamable HTTP session/SSE/timeout, exact host·DNS pinning·rebind 검사와 명시 private range | `mcp/`, `routes/mcp.py`, `test_mcp_catalog.py`, `test_mcp_runtime.py`, `test_mcp_manifests.py` |
| Scheduler·알림 | hourly·daily·weekly·weekdays·manual과 timezone, enable·disable·run-now·archive, `(task, scheduled_for)` claim과 중복 dispatch 경합 복구, frozen/latest Skill snapshot, timeout retry와 restart 후 interrupted retry, terminal Artifact 동기화, 사용자별 persistent·idempotent in-app 알림, unread count·read one/all·delete·deep link | `schedules/`, `notifications/`, `test_extensions_schedules.py`, `test_notifications.py` |
| Frontend 내구성·상세 UI | `crypto.randomUUID` fallback, Backend readiness 연속 확인 뒤 reload, top-level React Error Boundary, Session 복원 loading, 부가 화면 lazy loading, Composer stop, Turn renderer 분리, 확인 질문 card, Plan 자동 open/terminal close, Tool group·duration·model exchange·write progress, source evidence, 공용 body Portal tooltip, Artifact panel·공유 viewer·clipboard fallback, 사용자별 채팅 폭·글꼴 설정 | `AppErrorBoundary.tsx`, `BackendConnectionGuard.tsx`, `ConversationTurn.tsx`, `GlobalTooltip.tsx`, `client-id.ts`와 `apps/web/tests/` |
| 설치·운영 | installer validate-only/offline, Node version 검사, Windows `npm.cmd`, optional·required company CA 분리, 성공·실패 창과 exit code 보존, staged diagnostics와 Secret redaction, health live/ready, SQLite→PostgreSQL offline migration compile, SQLite worker lock의 platform 경계, 격리 QA port, supervisor identity 기반 종료와 실행기 hard reset | `devtools/install_lumina.ps1`, `devtools/run_lumina.ps1`, `devtools/stop_lumina.ps1`, `diagnostics/`, `test_operational_diagnostics.py`, `test_database_worker_lock.py` |

현재 명시적으로 구현하지 않은 경계도 함께 고정합니다.

- Run당 model Turn·총 Token·경과 시간·예상 비용은 생성 시 조직 설정을 snapshot으로 고정하고 한도 도달 시 `limit_reached`로 종료합니다. 기본값은 각각 400, 4,000,000, 10,080분, $100이며 관리자 화면에서 조정합니다.
- multi-worker lease·heartbeat, Redis queue, Object Storage, hosted document RAG, Local Workspace Bridge와 Skill Change Request·자동 Eval은 Target입니다.
- 조건부 LibreOffice·Poppler·PostgreSQL test가 skip되면 해당 외부 실행 환경까지 검증되었다고 주장하지 않습니다.

### 1.5 2026-07-16~17 source 정합화 결과

최근 source 변경을 설계에 반영할 때 단일 commit의 화면 모양을 장기 계약으로 과장하지 않고, 같은 동작을 보호하는 service·migration·회귀 test가 함께 있는지를 기준으로 삼았습니다. 현재 source에서 확정된 추가 계약은 다음과 같습니다.

| 영역 | 현재 구현 계약 |
|---|---|
| 원자 갱신 | Conversation, 사용자·Project 설정, Help 문서, Skill Draft·version pointer와 Artifact Draft·current version은 expected revision 또는 ETag 기반 compare-and-swap을 사용합니다. 누락·`null`·no-op PATCH는 구분하고 stale writer가 최신 값을 덮어쓰지 못하게 합니다. |
| 저장 보상 | Attachment, Project File, Artifact version과 Agent가 생성한 파일은 storage write 뒤 DB commit·pointer 갱신이 실패하면 이번 시도에서 새로 만든 blob만 정리합니다. 기존 version과 다른 요청의 blob은 보존합니다. |
| Project Workspace | Project Folder Context reference는 현재 ProjectFile·ProjectFileVersion query 결과에서 만들고 선택 시점의 folder content hash를 Run에서 다시 검증합니다. 파일 record 갱신과 논리 folder 갱신 경계를 분리하며, 손상·누락된 저장 원본은 빈 정상 응답으로 위장하지 않고 복구 가능한 오류 계약을 반환합니다. |
| 대화 복원 | 최근 Turn Set을 먼저 열고 위쪽 경계 접근 전에 이전 묶음을 선행 로딩합니다. live event와 과거 page를 ID·sequence로 합치며, 아직 load하지 않은 대화를 신규 welcome으로 오인하지 않습니다. |
| 확인 질문 | 계정 설정 `autonomous | balanced | confirming`을 Run snapshot에 고정하고, `request_user_input`은 한 Run에서 한 번의 질문 묶음으로만 호출합니다. Run은 `awaiting_input`에서 checkpoint를 보존하며 `submit_user_input` 후 Queue를 거쳐 재개합니다. |
| 실행 Timeline | Plan은 실제 모델 계획과 Tool 순서에 맞춰 갱신하고 terminal 전에 완료로 보이지 않게 합니다. 모델 처리 시간과 Tool interval을 분리하며 보고서·`write_file` 진행은 실제 출력 시작과 누적량을 기준으로 표시합니다. |
| Renderer | Mermaid는 label 문법을 안전하게 보정하고 authored style을 보존하며 fit·zoom·pan·drag scroll·keyboard close를 제공합니다. ECharts는 제한된 chart preset이 아니라 검증된 전체 option을 renderer 경계에서 처리합니다. |
| Marketplace | 설치된 Skill은 frontmatter와 Markdown 본문을 구분한 기본 읽기 화면을 제공하고 browser history로 catalog/detail을 오갑니다. MCP의 `미사용`은 단순 표시가 아니라 해당 scope installation 해제로 이어지며 destructive action은 같은 버튼의 2단계 확인을 사용합니다. |
| MCP wrapper | MCP definition payload와 상세 화면은 `source: skill-mcp:<slug>` wrapper 적용 여부를 함께 표시합니다. wrapper가 없으면 사용 지침이 Context에 들어가지 않음을 경고하며, 실제 연결이 없는 POSCO placeholder manifest·stub·wrapper는 builtin catalog처럼 남겨 두지 않습니다. |
| 사용자 표현 설정 | 채팅 본문 폭과 UI·사용자·assistant·code 글꼴 크기는 서버 설정 revision과 함께 저장합니다. 첫 답변에는 비교할 이전 누적량이 없으므로 Session 누적 usage 비교를 숨깁니다. |
| 조용한 정상 흐름 | 일상적인 저장·복사·읽음·실행 성공은 toast를 남발하지 않고 화면의 상태 변화로 확인합니다. 오류·부분 실패·복구·guard 상태는 명시적으로 알립니다. |
| Runtime 호환성 | Run 복구는 누락된 과거 Context·Plan field를 안전한 기본값으로 정규화하고, version 고정 source 문서는 원본 reference로 복구 가능해야 합니다. Provider `Retry-After`, Tool schema와 관리자 집계값은 외부·DB 경계에서 타입을 검증합니다. |
| Agent Frontend 경계 | Conversation과 Run은 builtin Agent Frontend ID·version·contract snapshot을 보존합니다. 등록되지 않았거나 호환되지 않는 Frontend는 `general-chat`으로 열되 원래 ID와 Artifact·Run 기록은 버리지 않습니다. |

## 2. 제품 정의

Lumina Agent는 여러 사용자가 브라우저로 접속하여 대화, 파일과 장시간 Agent 작업을 안전하게 관리하는 사내 AI Agent 서비스입니다. 사용자에게는 하나의 서비스로 보이지만 내부적으로 다음 세 경계를 유지합니다.

```text
Frontend application
→ Backend API and durable state
→ Agent Worker and execution environments
```

핵심 제품 특성은 다음과 같습니다.

- React와 TypeScript 기반의 다중 사용자 웹 UI
- Python과 FastAPI 기반의 인증·권한·대화·Run API
- Harness가 관리하는 반복형 Agent Loop와 장시간 Background Run
- Codex, OpenAI, OpenAI Compatible, P-GPT, Claude와 Gemini Provider
- Plugin, Skill, MCP와 Connector 기반 확장
- `Organization → Project → Session → Run` 업무 계층
- `@파일명` Context 연결과 `$Skill`·`$MCP` 명시 호출
- 구조화된 Plan, 병렬 Subtask, steer, Queue, pause, resume, cancel과 retry
- DOCX, XLSX, PPTX, PDF, HTML과 기타 Artifact의 생성·Preview·편집·검증
- 회사 CA, proxy와 P-GPT를 포함한 사내 네트워크 지원
- 서버 상태를 원본으로 하는 재접속·세션 전환·다중 기기 복구

### 2.1 설계 불변 조건

1. 브라우저 연결은 Run의 생명주기를 소유하지 않습니다.
2. 상태의 원본은 Backend DB와 관리 Storage이며, Frontend cache나 stream이 아닙니다.
3. 실행 lock은 사용자 전체가 아니라 Session 단위입니다.
4. 같은 Session에는 기본적으로 Run 하나만 실행하고 추가 요청은 Queue에 둡니다.
5. 서로 다른 Session의 Run은 사용자·서버 한도 안에서 병렬 실행할 수 있습니다.
6. Run 시작 후 Provider, Model, Effort, Agent, Tool, Skill, MCP, 권한과 Context 구성을 snapshot으로 고정합니다.
7. Frontend가 보낸 사용자 ID, role, 경로, Project ID, 확장 이름과 권한을 신뢰하지 않습니다.
8. 파일과 Artifact는 안정적인 ID와 불변 version으로 추적합니다.
9. 공유 링크 열람, Project 공동 작업과 Run 조작 권한을 서로 다른 권한으로 관리합니다.
10. TLS 오류를 `verify=False`로 우회하지 않습니다.
11. 비밀값, 인증서 원문, 비밀번호, token과 개인 credential을 저장소·일반 로그·Run event에 기록하지 않습니다.
12. 생성 성공과 품질 검증 성공을 구분합니다.
13. 실제 사용자 화면이 중요한 기능은 실제 브라우저로 검증합니다.

### 2.2 초기 범위에서 제외하거나 후순위인 항목

- Telegram·Discord 등 다수 메시징 채널
- 전용 Deep Research mode. 일반 Agent Loop가 필요에 따라 `web_search`·`web_fetch`를 반복 호출하고 Plan·진행 상태·검증 가능한 인용을 제공하는 것으로 통합합니다.
- 음성 대화, 카메라 입력과 화면 공유를 포함한 실시간 멀티모달 통신
- Gmail·Calendar·Drive·Slack 같은 소비자 SaaS의 builtin Connector. 회사에서 승인한 내부 API나 MCP는 별도 확장으로 연결합니다.
- Project 대용량 지식을 위한 builtin RAG. 초기에는 명시적으로 첨부·선택한 파일을 사용하고, 대규모 검색은 승인된 MCP로 도입합니다.
- 여섯 종류 이상의 Terminal backend
- 승인·감사·rollback이 없는 자동 Skill 자기개선
- 게임화와 Achievement
- 모든 Tool schema의 상시 Context 노출
- Agent가 매 요청마다 제품의 전체 React/HTML UI를 자유 생성하는 방식
- Local Bridge 없는 브라우저에서 사용자 PC 임의 폴더에 직접 접근하는 기능
- 익명 외부 대화 공유

### 2.3 구현 전 리팩터링 검토 결과

이 문서의 모든 장기 개념을 초기부터 별도 table, service, process와 설정으로 만들면 제품보다 framework를 먼저 구현하게 됩니다. 따라서 논리 계약은 유지하되 물리 구현은 다음과 같이 단순화합니다.

| 검토한 문제 | 리팩터링 결정 |
|---|---|
| `Session`과 `Conversation`의 1:1 중복 | DB에는 `conversations` 하나만 두고 UI 용어만 Session으로 사용 |
| Frontend·Backend·Worker를 처음부터 microservice로 분리 | 하나의 repository와 Python package 안의 modular monolith로 시작하고 process만 필요할 때 분리 |
| 모든 entity마다 Repository와 Service 생성 | transaction·권한·외부 I/O 경계가 있는 vertical module에만 명시적 service 사용 |
| 매 token delta를 영구 event로 저장 | 일정 시간·문자 수로 합친 text chunk와 canonical draft checkpoint만 저장 |
| 개발팀 채팅 공유를 위해 전역 shared mode 추가 | 개발팀은 동일한 `admin@posco.com` principal로 로그인해 같은 채팅·설정을 사용하고 별도 shared query 분기를 만들지 않음 |
| Tool Call과 Tool Result를 별도 생명주기로 관리 | 기본 1:1 `tool_executions` record로 묶고 큰 결과만 Artifact reference로 분리 |
| manual autosave마다 immutable Artifact version 생성 | 임시 draft와 committed version을 분리하고 명시 저장·AI 완료·복원만 version 생성 |
| Skill·MCP·Plugin을 동시에 범용 Marketplace로 구현 | Skill부터 구현하고 MCP·Plugin authoring은 실제 공통점이 확인된 뒤 확장 |
| Agent package·remote Frontend를 미리 DB화 | 첫 Frontend는 code registry와 typed contract로 시작하고 두 번째 Frontend PoC 때 registry persistence 추가 |
| Permission Lease·Execution Environment를 초기부터 완전 일반화 | 격리된 `local_worker`는 기본 `on_risk`로 실행하고 위험 Tool은 one-shot 승인, 반복 Lease와 후속 실행 환경은 실제로 필요할 때 확장 |
| Redis·Object Storage·Kubernetes를 초기 개발 필수로 사용 | SQLite·managed local storage로 수직 기능을 먼저 완성하고 multi-process·multi-node 요구에서 교체 |

리팩터링의 기준은 “나중에 분리할 수 있는 경계”와 “지금 분리해야 하는 구성요소”를 구분하는 것입니다. 초기 구현은 한 프로세스에서도 전체 핵심 흐름을 검증할 수 있어야 하지만, DB가 Run과 파일 상태의 원본이라는 불변 조건은 완화하지 않습니다.

### 2.4 단순화가 지켜졌는지 확인하는 기준

1. 초기 개발 환경은 React, FastAPI, SQLite와 선택한 Provider credential만으로 핵심 채팅을 실행할 수 있습니다.
2. Redis, MinIO, Kubernetes, Plugin loader와 remote Frontend가 없어도 Phase 0~2 사용자 흐름을 검증할 수 있습니다.
3. UI Session과 Backend Conversation 사이에 ID 변환 table이나 동기화 code가 없습니다.
4. Provider 하나를 추가할 때 Agent Loop, Queue와 Frontend event reducer를 수정하지 않습니다.
5. local executor를 sibling Worker로 분리할 때 API와 event schema가 바뀌지 않습니다.
6. 개발팀이 동일한 admin 계정을 사용해도 별도 shared mode나 Conversation·Artifact query 예외 분기가 늘어나지 않습니다.
7. text streaming 중 생성되는 DB row 수가 Provider token chunk 수에 비례하지 않습니다.
8. 수동 편집 autosave를 여러 번 해도 사용자가 확정 저장하기 전에는 Artifact version이 증가하지 않습니다.
9. 아직 구현하지 않는 Phase의 table, empty service, generic factory와 설정 화면이 존재하지 않습니다.

### 2.5 외부 챗봇 기능 비교에서 확정한 제품 경계

2026년 7월 기준 공식 제품 문서를 기능 기준으로 다시 비교했습니다. ChatGPT Deep Research는 계획 검토·진행 추적·중단·업로드 파일·검증 가능한 인용과 사용 출처 목록을 제공하고, Gemini Deep Research도 검색 계획과 출처 선택·파일 입력을 제공하며 일반 응답에는 inline 또는 별도 source panel이 있습니다. Claude Research는 여러 검색을 이어 가는 agentic research와 inline citation을 제공하고, Claude의 일반 채팅은 문서·이미지 업로드와 clipboard image paste를 지원합니다. Lumina는 이들을 그대로 복제하지 않고 회사 사용 환경에 필요한 공통 부분만 채택합니다.

| 비교 기능 | Lumina 결정 |
|---|---|
| 별도 Research 진입점 | 만들지 않음. 동일 Agent Loop 안에서 검색 계획, 반복 검색, fetch, 중단·steer와 진행 상태를 제공 |
| 검증 가능한 출처 | 채택. 주장 근처 번호 각주, 근거 문장 hover, 클릭 가능한 URL, 답변 하단의 전체 검색어·참고 링크 목록 제공 |
| 파일 기반 질의 | 채택. PDF·문서·표·이미지를 chat attachment와 Project file로 지원 |
| Project 대용량 RAG | builtin 구현하지 않음. 승인된 MCP가 검색 결과와 source reference를 반환하는 방식으로 확장 |
| 음성·카메라·화면 공유 | 제외 |
| Gmail·Calendar·Drive·Slack 제품 통합 | 제외. 회사 승인 시스템만 Connector/API 또는 MCP로 추가 |

비교 근거: [OpenAI Deep Research](https://help.openai.com/en/articles/10500283-deep-research-faq/), [OpenAI Projects](https://help.openai.com/en/articles/10169521-projects-in-chatgpt), [OpenAI API Web Search](https://developers.openai.com/api/docs/guides/tools-web-search), [Gemini Deep Research](https://support.google.com/gemini/answer/15719111?hl=en), [Gemini Sources](https://support.google.com/gemini/answer/14143489?hl=en), [Claude Research](https://www.anthropic.com/news/research), [Claude file uploads](https://support.claude.com/en/articles/8241126-upload-files-to-claude)

## 3. 통합 용어와 객체 관계

### 3.1 기본 업무 계층

```text
Organization
└─ Project
   ├─ Members and roles
   ├─ Instructions and memory
   ├─ Files and connected resources
   ├─ Allowed extensions and connectors
   ├─ Scheduled tasks
   └─ Session (stored as Conversation)
      ├─ Messages
      ├─ Queue
      ├─ Artifacts
      └─ Run
         ├─ Plan
         │  ├─ Step
         │  └─ Subtask or Batch item
         ├─ Turn
         ├─ Tool call and result
         ├─ Approval and permission lease
         └─ Event stream
```

### 3.2 Session과 Conversation

- `Session`은 사용자가 사이드바에서 열고 전환하는 채팅 작업 단위입니다.
- `Conversation`은 그 작업 단위를 저장하는 Backend entity와 API 용어입니다.
- 초기 구현에서는 별도의 `sessions` table을 만들지 않습니다. `conversations.id`가 UI Session ID이자 실행 lock key입니다.
- 분기 시 새 Conversation을 만들고 `parent_conversation_id`, `branch_message_id`를 기록합니다.
- 사용자 화면과 문구에서는 Session 또는 채팅으로 표현하고, code·DB·event에서는 `conversation_id` 하나로 통일합니다.
- 향후 하나의 작업 화면에 여러 독립 대화 흐름이 실제로 필요해질 때만 Session aggregate를 별도로 도입합니다.

### 3.3 공유 관련 용어

| 개념 | 의미 | 실행 권한 |
|---|---|---|
| `view_share` | 불투명 링크 token으로 고정된 대화·Artifact snapshot 열람 | 없음 |
| `project_member` | Project의 허용된 파일·세션·Artifact 협업 | Project role에 따름 |
| `run_collaborator` | 특정 Session 또는 Run에 steer·승인·취소 수행 | 명시 범위에 따름 |
| shared admin identity | 개발팀이 동일한 `admin@posco.com`으로 로그인해 동일 상태 사용 | admin 전체 권한 |

개발팀 내부 공유는 별도 `LUMINA_SHARING_MODE`나 `shared-debug` Project를 사용하지 않습니다. 여러 사람이 같은 `admin@posco.com` 계정으로 로그인하면 동일한 `user_id`의 Sidebar, Project, Session, 설정과 Memory를 그대로 공유합니다. 일반 사용자 사이의 공유는 계속 Project membership과 명시적인 share grant를 사용합니다.

### 3.4 UI 계층 용어

- `Agent Frontend`: 범용 채팅, 보고서 편집기, 데이터 분석 화면처럼 교체 가능한 전체 업무 Frontend입니다.
- `UI Profile`: 한 Agent Frontend 안에서 사용할 검증된 layout과 component 구성입니다.
- `Live Artifact`: 지속적으로 갱신·버전 관리되는 업무 산출물입니다.
- `MCP App`: 외부 Tool이 제공하며 sandbox iframe에서 실행되는 확장 UI입니다.
- `HTML Artifact`: 사용자가 열람·다운로드하는 독립 문서이며 제품 UI와 구분합니다.

## 4. 전체 시스템 아키텍처

```text
User Browser
  │
  ▼
Gateway / Reverse Proxy
  ├─ /              → React Frontend
  ├─ /api/*         → FastAPI Backend
  └─ /stream/*      → SSE
                         │
                         ▼
FastAPI Backend
  ├─ Auth and authorization
  ├─ Organization / Project / Session services
  ├─ Run, Queue, Approval and Event services
  ├─ Artifact and Extension services
  ├─ Provider and HTTP configuration
  └─ Scheduler and Notification services
          │
          ├─ SQLite development / PostgreSQL production
          ├─ Local managed storage / S3 or MinIO
          ├─ in-process queue development / Redis production
          └─ Secret Store
                         │
                         ▼
Agent Worker / Harness
  ├─ Agent Loop
  ├─ Provider adapters
  ├─ Tool registry
  ├─ Plugin / Skill / MCP resolver
  ├─ Browser / Computer use adapters
  └─ Execution environment manager
```

### 4.1 Frontend 책임

- 로그인, Session 탐색, 채팅, Artifact와 설정 UI 제공
- Backend가 제공한 상태와 이벤트를 사용자 친화적으로 렌더링
- `@`와 `$` 자동완성, 구조화 payload 생성
- 세션별 UI cache, scroll 상태와 일시 draft 관리
- replay와 live event를 `run_id + sequence` 기준으로 중복 없이 병합
- Backend 권한 판단을 대체하지 않음
- 비밀값을 bundle, local storage 또는 공개 환경변수에 포함하지 않음

### 4.2 Backend 책임

- 인증 principal과 모든 자원 권한 확정
- DB transaction, 상태 전이, Queue, idempotency와 audit 관리
- Session·Run snapshot과 순번 이벤트의 canonical state 제공
- Artifact metadata, version, Storage key와 공유 범위 관리
- Provider·Extension·Connector availability와 정책 계산
- Worker 작업 접수, 취소·재개·승인 명령 전달
- Frontend 전용 layout이나 React component를 business contract에 포함하지 않음

### 4.3 Agent Worker 책임

- 고정된 Run snapshot을 받아 Agent Loop 실행
- Provider별 형식을 공통 event와 usage로 정규화
- Tool schema 검증, permission 확인, 실행 전후 hook 수행
- checkpoint, retry, timeout과 결과 저장
- Browser 연결이 없어도 작업 지속
- 실제 실행 환경과 durable output을 명시적으로 관리

### 4.4 저장소 구조

```text
apps/web/                         Frontend
apps/server/                      Backend and worker code
apps/server/src/lumina/providers/ Provider implementations
extensions/plugins/               Plugin packages
extensions/skills/                Skill packages
extensions/mcp/                   MCP definitions
data/                             Local development runtime data
infra/                            Container and Kubernetes assets
devtools/                         Maintenance and validation tools
tests/backend|frontend|e2e|evals/ Tests
docs/project-context/             Source design and research documents
```

### 4.5 초기 물리 구조: Modular Monolith

Frontend, Backend와 Worker는 책임 경계이지 처음부터 서로 다른 repository나 network service여야 한다는 뜻이 아닙니다.

```text
Initial deployment
├─ apps/web                         React application
└─ apps/server                      one Python package
   ├─ API process
   ├─ Run executor                  same process or sibling process
   ├─ domain modules
   └─ adapters                      Provider, Storage, HTTP, Extension
```

- 개발 초기에는 API process 안의 background executor를 허용합니다. 단, Run 접수와 checkpoint를 DB에 먼저 저장한 뒤 실행하여 browser disconnect와 process restart를 구분합니다.
- 운영에서 장시간 Run이 API latency나 안정성에 영향을 주는 시점에는 같은 Python package의 sibling Worker process로 분리합니다.
- Redis는 여러 API·Worker process 사이의 claim과 wake-up이 필요해질 때 도입합니다. 그 전에는 DB-backed claim과 polling 또는 process-local wake-up을 사용합니다.
- process 분리 전후에 Run command, snapshot, event와 Artifact 계약은 바뀌지 않아야 합니다.
- module은 `auth`, `projects`, `conversations`, `runs`, `artifacts`, `providers`, `extensions`처럼 사용자 기능 단위로 나눕니다. entity마다 기계적으로 Repository·Service·DTO 세트를 만들지 않습니다.
- Repository는 복잡한 query, transaction 또는 storage 교체 경계에만 둡니다. 단순 CRUD wrapper는 추가하지 않습니다.

## 5. 인증, 사용자와 권한

### 5.1 사용자 계정

```text
User
├─ user_id: immutable UUID
├─ organization_id: initial single-company ownership
├─ login_name
├─ login_domain
├─ display_name
├─ affiliation
├─ password_hash
├─ role: user | admin | future delegated roles
├─ status: invited | active | locked | disabled
├─ must_change_password
└─ created_at / updated_at / last_login_at
```

- 모든 소유권은 변경 가능한 로그인 문자열이 아니라 `user_id`를 사용합니다.
- 비밀번호는 Argon2id 또는 조직 기준의 강한 단방향 hash로 저장합니다.
- 로그인 실패 횟수 제한, 지연 또는 일시 잠금과 관리자 해제를 지원합니다.
- 비밀번호 변경·reset, 잠금·비활성화 시 기존 세션을 폐기할 수 있어야 합니다.
- 마지막 활성 관리자는 대체 관리자 없이 비활성화하거나 강등할 수 없습니다.
- 가입 신청은 `invited` 상태로 로그인할 수 없고 활성 관리자의 명시 승인 뒤에만 session을 생성합니다.
- 공개 가입 신청은 email, 표시 이름, 소속, 신청 role과 비밀번호를 받되 즉시 session을 만들지 않습니다. Backend는 정규화한 email 중복을 차단하고 같은 Organization의 활성 Bootstrap admin이 없으면 `registration_unavailable`로 실패합니다.
- 신청 계정은 `invited`로 저장하여 로그인할 수 없게 하고 관리자에게 idempotent `registration_approval` 알림과 Admin deep link를 생성합니다. 관리자는 신청 role·소속을 검토한 뒤 `active`로 전환하며 신청·승인·거부와 role 변경을 audit에 남깁니다.

### 5.2 로그인 UX

```text
아이디       [ login_name ]
주소         [ posco.com  ]
비밀번호     [ password   ]
로그인
```

- 초기 focus는 아이디입니다.
- 아이디에서 `Tab`을 누르면 주소 입력란을 건너뛰고 비밀번호로 이동합니다.
- 주소는 별도 control로 유지하며 `주소 변경` 동작으로 접근할 수 있어야 합니다.
- 비밀번호에서 Enter로 제출합니다.
- 실패 시 비밀번호만 지우고 계정 존재 여부를 드러내지 않는 동일 오류를 사용합니다.
- 공유 링크는 로그인 session을 확인한 뒤 열람자의 sidebar를 유지한 상태에서 중앙 읽기 전용 viewer로 엽니다.
- `회원가입`은 로그인 form과 같은 화면에서 신청 form으로 전환하고, 접수 뒤 `관리자 승인 후 로그인` 상태를 보여줍니다. 비밀번호 확인은 Frontend 편의 검증일 뿐 Backend의 password 정책과 중복 검사를 대체하지 않습니다.
- 개발 build에서만 로그인 form 오른쪽 위에 작은 `UserPlus` helper를 표시합니다. hover·focus tooltip과 `개발 계정 admin@posco.com 채우기` 접근성 이름을 제공하며, 클릭하면 ID·domain만 채우고 비밀번호로 focus를 이동합니다. production build에는 노출하지 않습니다.

### 5.3 Server Session

- 인증 성공 후 `HttpOnly`, `Secure`, 적절한 `SameSite` cookie 기반 server session을 사용합니다.
- 상태 변경 요청에는 CSRF 방어를 적용합니다.
- 절대 만료는 로그인 시점 다음 Asia/Seoul 자정입니다.
- 로그아웃, 비밀번호 변경·reset, 잠금·비활성화 또는 관리자 폐기는 자정 전이라도 즉시 만료합니다.
- 브라우저 local storage에 로그인 여부를 원본으로 저장하지 않습니다.

### 5.4 Bootstrap 관리자

현재 개발 요구사항은 최초 DB에 계정이 없을 때 `admin@posco.com`, 초기 비밀번호 `1`, `role=admin`, `status=active`, `must_change_password=false`를 생성하는 것입니다. 비밀번호 원문은 DB에 저장하지 않고 hash만 저장하며, 기존 계정의 비밀번호를 서버 시작 때 덮어쓰지 않습니다.

`admin@posco.com / 1`은 개발팀 공용 계정의 확정 기본값이며 최초 로그인 시 비밀번호 변경을 강제하지 않습니다. 상용화 준비 시 관리자가 명시적으로 변경하기 전까지 installer와 startup이 임의 비밀번호를 발급하거나 SSO로 바꾸지 않습니다. 비밀번호를 변경하면 기존 server session을 모두 폐기하되 startup이 다시 `1`로 되돌리지 않습니다.

### 5.5 권한 검사 순서

```text
1. 유효한 server session
2. active account
3. admin policy and audit, if admin action
4. direct ownership
5. Project membership and role
6. exact conversation share grant
7. message / attachment / artifact snapshot scope
8. field-level response filtering
```

Frontend가 보낸 `owner_user_id`, `recipient_user_id`, role, organization과 scope는 권한 근거로 사용하지 않습니다.

### 5.6 관리자 기능

- 사용자 생성, 조회, 잠금, 해제, 비활성화, role 변경
- 초기 비밀번호 또는 reset 발급
- 전체 사용자의 Project, 대화, Run과 Artifact 조회
- 일반 사용자의 Message, attachment, Memory metadata와 설정 조회. Memory 원문과 민감정보는 업무상 필요한 범위와 field filtering을 적용
- 공유 grant 조회·강제 취소
- 저장량, 사용량, 최근 로그인과 상태 확인
- 보안·운영 감사 기록 조회
- 조직별 Run당 model Turn·총 Token·경과 시간·예상 비용 안전 한도 설정
- 같은 조직의 활성·대기·중단된 Run과 대기 Message 비상 전체 중단

관리자도 비밀번호 원문, Provider Secret, Connector token을 볼 수 없습니다. 다른 사용자의 대화는 관리자 전용 viewer에서 조회하며 사용자 가장 기능은 초기 범위에서 제외합니다.

## 6. 데이터 격리, 공유와 공동 작업

### 6.1 기본 격리

- 새 Project, Session과 Conversation의 기본 공개 범위는 `private`입니다.
- 목록, 검색과 직접 URL 조회는 현재 principal의 소유권 또는 정확한 membership·grant로 제한합니다.
- 다른 ID로 로그인하면 이전 사용자의 제목, 검색어, draft, 알림과 cache가 잠깐이라도 표시되지 않아야 합니다.
- 로그아웃 시 메모리의 메시지, Run snapshot, Artifact URL과 사용자 cache를 제거합니다.
- 같은 ID로 다른 브라우저에 로그인하면 동일한 서버 상태를 복원합니다.

### 6.2 링크 기반 대화 공유

기본 공유는 답변 아래 공유 버튼을 누르면 링크가 즉시 복사되는 읽기 전용 snapshot입니다. 수신자 지정 form이나 만료 시각 입력을 먼저 요구하지 않습니다.
공유 URL은 생성자의 현재 theme를 포함하며 viewer는 일반 채팅과 같은 본문 typography와 해당 theme를 적용합니다.
링크 열람자의 sidebar와 navigation은 유지하고 중앙 영역만 read-only viewer로 전환하며, 열람자의 session 선택과 history는 변경하지 않습니다.

```text
ConversationShareGrant
├─ share_id
├─ conversation_id
├─ owner_user_id
├─ recipient_user_id optional  # 향후 수신자 제한 공유용
├─ scope: conversation_snapshot | message_snapshot
├─ anchor_message_id
├─ snapshot_through_message_id
├─ permission: view
├─ token_hash
├─ expires_at
├─ revoked_at
├─ created_by / created_at
└─ last_accessed_at
```

- 원본 token은 생성 시 한 번만 반환하고 DB에는 hash를 저장합니다.
- 기본 링크의 resource scope는 불투명 token으로 확정합니다. Frontend는 로그인 session을 요구해 열람자의 sidebar와 함께 표시하며, 원본 token은 저장·로그·감사 metadata에 남기지 않습니다.
- 기본 snapshot은 생성 시점의 `snapshot_through_message_id`까지만 표시합니다.
- 이후 메시지를 자동 공개하지 않습니다.
- 링크 열람자는 수정, 새 Run, steer, 승인, 취소와 Artifact overwrite를 할 수 없습니다.
- 취소, 만료 또는 원본 삭제 후 다음 조회·Preview·다운로드부터 거부합니다.
- 공유 viewer API는 소유자의 sidebar, 전체 Project, 이전·다음 대화와 전체 count를 반환하지 않습니다.
- 내부 private 링크는 권한 없는 placeholder로 렌더링합니다.

### 6.3 Project 공동 작업

- Project membership은 `view_share`와 별개입니다.
- 초기 Project 구성원 관리는 같은 Organization에 등록된 active `login_id`를 Project 설정에서 직접 추가하는 계정 기준 방식입니다. 팀·부서 membership은 인사정보 연동 시 별도 directory 계층으로 추가하고, 현재 Project membership을 대체하지 않습니다.
- active 비소유 membership이 하나 이상이면 `project_type=shared`, `visibility=shared`로 전환하고, 모두 revoked되면 `project_type=personal`, `visibility=private`로 되돌립니다.
- owner·admin은 구성원을 추가하고 role을 변경·회수할 수 있으며 canonical owner는 이 화면에서 변경하거나 제거하지 않습니다.
- Project role이 허용한 범위에서 파일·세션·Artifact를 공동 사용합니다.
- Session 또는 Run 조작은 별도의 `run_collaborator` 권한으로 제한할 수 있습니다.
- 개인 Run을 공동 Run으로 전환할 때 개인 Connector token, browser session과 credential lease를 자동 승계하지 않습니다.
- 공동 Run에서 사용할 연결은 Project service connection 또는 참여자별 delegated connection으로 다시 선택합니다.
- 모든 steer, 승인, 취소와 변경에는 실제 actor ID를 기록합니다.

### 6.4 개발팀 공용 Admin 계정

- 개발팀은 `admin@posco.com` 하나를 공용 principal로 사용하며 이 계정에서 만든 Project, Session, Artifact, 설정과 UserMemory는 같은 계정으로 로그인한 모든 개발팀원에게 동일하게 보입니다.
- 별도 shared mode flag와 `shared-debug` Project를 만들지 않습니다. 동일 계정 공유는 일반 소유권 규칙에서 자연스럽게 처리합니다.
- admin은 관리자 화면에서 다른 일반 사용자의 Project, 대화, Run, attachment와 Artifact를 조회할 수 있습니다. 직접 URL도 admin 권한 검사와 감사 기록을 통과해야 합니다.
- 일반 사용자 대화를 admin 자신의 대화로 복사하거나 소유자를 바꾸지 않습니다. 관리자 조회 화면과 admin 본인의 Sidebar는 구분하며, 관리자가 다른 사용자 대화를 조회·다운로드·변경하면 별도 audit event를 남깁니다.
- 공용 계정에서는 서버가 사람별 신원을 구분할 수 없으므로 감사 기록의 actor는 `admin@posco.com`과 server session·device·request ID까지만 보장합니다. 개발팀원 개인별 책임 추적은 하지 않는다는 trade-off를 수용합니다.
- 비밀번호·Provider Secret·Connector token 원문은 admin에게도 노출하지 않습니다. 향후 관리자 기능은 이 권한 경계와 감사 원칙 안에서 추가합니다.

## 7. Project, Workspace와 Memory

### 7.1 Project 구성

```text
Project
├─ organization_id
├─ owner_user_id / project_type
├─ name / description / icon / color
├─ members and roles
├─ concept and instructions
├─ files and connected folders
├─ allowed connectors / skills / plugins / MCP
├─ project memory
├─ learning proposals
├─ scheduled tasks
├─ sessions
└─ artifacts
```

- Project 지침과 허용 Context는 Project 안의 새 Session에 자동 적용합니다.
- 파일, URL, Connector와 확장을 한곳에서 관리합니다.
- Session과 Artifact를 Project 범위로 검색합니다.
- 다른 Project의 파일, Memory와 Secret을 섞지 않습니다.
- Project를 닫거나 브라우저를 종료해도 Run checkpoint와 작업 이력을 유지합니다.

### 7.2 사용자별 Project Folder

UI의 `Project Folder`는 임의의 서버 filesystem 경로가 아니라 권한과 설정이 적용되는 `Project` 객체입니다. 사용자마다 최초 로그인 시 개인 `Default` Project를 정확히 하나 생성하고, 새 Session은 별도 선택이 없으면 여기에 속합니다.

- 사용자는 Sidebar에서 자신의 Project Folder를 생성·선택·이름 변경·정렬·보관할 수 있습니다. `Default`는 이름 변경은 허용할 수 있지만 삭제할 수 없으며 항상 fallback 대상입니다.
- Project Folder에는 이름, 설명, icon·color, 업무 concept, 기본 지침, 기본 Provider·Model·Effort, 허용 Skill·MCP, 출력 형식·문체와 Artifact style을 설정할 수 있습니다. 실행 승인 mode는 기본 `on_risk`이며 비밀번호·token·일회성 승인은 concept에 저장하지 않습니다.
- Project concept는 해당 Project의 새 Run에 stable instruction snapshot으로 들어가며 기존 Run을 소급 변경하지 않습니다. 사용자의 전역 Memory보다 현재 Project 지침이 우선하지만, 보안·조직 정책보다 우선할 수 없습니다.
- Sidebar는 `Default`, 사용자가 만든 개인 Project, 참여 중인 공유 Project 아래에 Session을 묶어 표시하고 Project 단위 접기·검색을 지원합니다.
- 각 Session 행의 `…` 메뉴에는 `프로젝트로 이동`을 제공하고, 사용자가 접근 가능한 destination만 보여줍니다. 이동은 `conversations.project_id`를 한 transaction에서 변경하고 `conversation_moved` audit/event를 남깁니다.
- Session 이동 시 Session 소유 attachment와 Artifact는 함께 이동할 수 있습니다. 기존 Project 공용 파일·Memory·Secret·MCP binding은 복사하지 않으며, 과거 Message는 당시 source project와 reference snapshot을 유지합니다.
- destination이 공유 Project이거나 공개 범위가 넓어지면 이동 전에 포함될 Session·attachment·Artifact와 노출 범위를 요약해 확인받습니다. 권한 없는 reference는 link metadata만 남기고 다시 읽지 못하게 합니다.
- `running`, `awaiting_approval` 또는 Queue가 남은 Session은 Run snapshot의 Project를 도중에 바꾸지 않습니다. 이동 요청을 terminal state 뒤에 적용하도록 예약하거나, 현재 Run 종료 후 이동하도록 안내합니다.
- Project 삭제는 즉시 hard delete하지 않습니다. 포함된 Session을 `Default` 또는 다른 Project로 이동하거나 함께 휴지통으로 보낼지 선택하게 하며, destination이 없거나 유효하지 않으면 `Default`로 fallback합니다.

### 7.3 지침 우선순위

```text
System security policy
→ Organization policy
→ Agent default instructions
→ Relevant UserMemory
→ Project or folder instructions
→ User AGENTS.md
→ Current request
```

사용자별 `AGENTS.md` 원본은 DB에 저장하고 실행 시 격리된 Workspace에 materialize할 수 있습니다. Kubernetes와 다중 Backend에서는 로컬 파일을 원본으로 사용하지 않습니다. 비밀값은 지침 파일에 넣지 않습니다.

현재 구현은 개인, Project와 Organization 지침의 동시 수정을 내부 revision·digest와 `If-Match`로 보호하되 개인·Project 화면에는 이를 버전 정보로 노출하지 않습니다. 개인 지침은 본인이 직접 관리하고 Project 지침은 owner·admin·member가 즉시 수정하며 viewer는 읽기만 합니다. Organization 지침은 과거 revision의 표시 label과 본문을 별도로 조회·수정할 수 있으며, code resolver는 `Organization → Agent default → Project → Personal` 순서의 snapshot을 Run에 고정합니다. Personal layer는 개인 Project에만 포함하고 공유 Project에서는 명시적으로 제외합니다. Backend는 지침 저장 시 credential·private key·token 패턴을 다시 검사합니다.

### 7.4 Workspace 유형

| 유형 | 위치와 의미 | 초기 지원 |
|---|---|---|
| Server Workspace | Lumina 관리 Storage의 Project 파일 | 필수 |
| Uploaded Files | 브라우저로 업로드한 Project 파일 | 필수 |
| Local Workspace | Local Bridge가 허용한 사용자 PC 폴더 | 후순위 |
| Approved Remote Source | 회사가 승인한 내부 저장소 API 또는 MCP resource | 후순위 |

- Frontend raw path를 신뢰하지 않고 reference ID를 검증합니다.
- path traversal, 절대 경로, symlink 탈출과 다른 사용자 root 접근을 차단합니다.
- 파일 version, checksum, 작성자, 원본 Run과 변경 이유를 저장합니다.
- optimistic concurrency 또는 base version으로 동시 변경을 보호합니다.
- 삭제는 휴지통과 영구 삭제를 구분하며 영구 삭제는 추가 승인 대상입니다.

### 7.5 사용자 Memory와 Project 학습

- `UserMemory`는 한 사용자의 여러 개인 Project와 Session에서 재사용하는 비공개 장기 정보입니다. 선호 언어·말투·형식, 반복 업무 방식, 자주 쓰는 용어, 역할과 명시된 장기 목표처럼 이후 응답에 실제로 도움이 되는 안정된 정보를 자동 학습합니다.
- 각 완료 Turn 뒤 비동기 Memory extractor가 새 후보를 만들고 기존 항목과 중복·충돌을 비교합니다. chat 응답 완료의 critical path를 막지 않으며 extractor 실패가 원래 Run을 실패시키지 않습니다.
- 자동 학습 근거는 사용자가 직접 작성한 Message와 명시적 확인으로 제한합니다. assistant 추측, web·Tool 결과, 업로드 문서의 문장과 다른 사람이 공유한 대화를 사용자 사실로 학습하지 않습니다.

```text
UserMemory
├─ user_id / memory_id
├─ category / normalized_fact
├─ display_text
├─ source_message_ids[] / source_run_ids[]
├─ confidence / evidence_count
├─ status: active | superseded | dismissed | deleted
├─ first_learned_at / last_confirmed_at / expires_at
└─ extractor_version / updated_at
```

- 기본값은 `자동 학습 켜짐`이며 사용자는 전체 기능을 끄거나 `자동 저장 | 저장 전 확인 | 저장 안 함`으로 바꿀 수 있습니다. 설정 변경은 다음 Turn부터 적용하고 기존 Memory를 자동 삭제하지 않습니다.
- password, token, 인증서, 주민·사번 같은 고유식별정보, 건강·정치·노조 등 민감정보, 일회성 코드, 임시 승인, 추측한 감정·성격과 제3자 비밀은 자동 저장하지 않습니다. 사용자가 명시적으로 기억을 요청해도 조직 정책이 금지하면 거부합니다.
- 같은 사실의 반복은 evidence count와 last confirmed만 갱신합니다. 새 정보가 기존 정보와 충돌하면 덮어쓰지 않고 최신 명시 발언을 active로, 이전 항목을 superseded로 연결합니다.
- 개인 Memory 화면의 `LLM 최적화`는 여러 active 항목을 구조화 입력으로 분석해 같은 사실의 표현·파편만 통합합니다. 관련만 있거나 범위가 다른 사실, 충돌 값과 불확실한 항목은 합치지 않습니다. 통합 Memory는 원본 Message·Run·evidence를 모두 승계하고 원본은 삭제하지 않고 `superseded`로 보존하며, Backend는 LLM이 반환한 Memory ID·중복 그룹·민감정보를 다시 검증합니다.
- Run 시작 전 권한이 있는 active Memory 중 현재 요청과 관련된 소수만 token budget 안에서 선택해 stable ID와 함께 Context tail에 넣습니다. 전체 Memory를 매 Turn system prompt에 넣어 cache를 깨거나 token을 낭비하지 않습니다.
- 선택된 UserMemory와 Project Memory의 ID·표시 내용·revision 또는 확인 시각은 Run 생성 시 snapshot으로 고정합니다. Queue 대기 중 Memory가 변경되어도 이미 생성된 Run의 recall 결과는 바뀌지 않으며 replay도 같은 내용을 사용합니다.
- recall block은 명시적으로 `새 사용자 입력이 아닌 하위 우선순위 참고 Context`라고 표시해 현재 사용자 Message tail에 붙입니다. 동적으로 변하는 recall을 system prompt에 추가하지 않아 stable prefix와 Provider prompt cache를 보존하고, recall 내용 안의 지시는 실행 지침으로 승격하지 않습니다.
- 전체 대화 이력은 UserMemory로 요약 복제하지 않습니다. 정확한 과거 결정이나 발언이 필요하면 기존 Session·Message 저장소를 검색하는 읽기 전용 `session_search` Tool을 사용하며 결과에 원본 Session·Message ID를 포함합니다.
- 사용자는 Memory 화면에서 학습 내용, category, 출처 대화, 적용 범위와 생성 시각을 조회·검색·수정·삭제하고 `이 대화에서 학습하지 않기`를 선택할 수 있습니다. 삭제된 항목은 새 학습의 정답처럼 재사용하지 않습니다.
- Lumina의 사용자 삭제 UX는 대상 종류와 화면에 관계없이 인라인 2단계 확인을 사용합니다. 첫 클릭은 해당 삭제 버튼을 경고 상태와 `한 번 더 눌러 삭제` 안내로 전환할 뿐 mutation을 실행하지 않으며, 같은 버튼의 두 번째 클릭에만 삭제합니다. 별도 브라우저 팝업이나 modal은 열지 않고 대상·화면 변경 또는 메뉴 닫힘에는 확인 상태를 해제하며, 실행 중·성공·실패 상태도 같은 위치에서 전달합니다.
- 좋아요·싫어요 한 번만으로 사용자 선호를 확정하지 않습니다. 사용자가 이유를 적었거나 여러 대화에서 같은 선호가 반복된 경우에만 일반 Memory 후보로 승격합니다.
- 개인 UserMemory와 Project 공용 Memory를 분리합니다. 공유 Project는 개인 Memory 원문을 다른 구성원에게 노출하거나 공용 Memory로 자동 복사하지 않습니다.
- 완료 Run이 Project 지침·파일·용어집·예시·Skill 개선을 발견해도 바로 적용하지 않고 `ProjectLearningProposal`을 생성합니다.

```text
ProjectLearningProposal
├─ project_id
├─ source_run_ids[]
├─ target_type
├─ target_id / base_version
├─ proposed_patch
├─ rationale / evidence_refs[]
├─ expected_scope
├─ status: proposed | approved | rejected | stale | applied | rolled_back
└─ proposed_by / reviewed_by / timestamps
```

base version이 달라졌으면 `stale` 처리하며, 승인 후에도 새 version으로 적용하고 rollback할 수 있어야 합니다. 비밀값, 개인 계정, 일회성 승인과 임시 우회책은 학습 후보에서 제외합니다.

## 8. Session, 검색과 대화 생명주기

### 8.1 Sidebar 목록

- 새 Session의 제목이 기본 placeholder(`제목 없음`, `새 작업`)이면 첫 사용자 Message 전송 즉시 Frontend가 입력을 공백 정규화하고 최대 60자로 줄인 임시 제목을 상단과 Sidebar에 먼저 표시합니다. Run 생성 실패 시 placeholder로 rollback하고, 성공 시 첫 Run 생성 transaction 안에서 서버 fallback 제목과 그 revision을 Run snapshot에 고정합니다. 첫 답변의 동일한 LLM 호출은 visible answer·Tool Call보다 먼저 `{"session_title":"..."}` JSON 제어행을 한 줄 출력하고, Backend는 이를 assistant text에서 제거한 뒤 검증된 제목을 `conversation_title_updated` event로 전달합니다. 별도 제목 전용 LLM 호출은 하지 않습니다. 저장 직전 임시 제목 값과 revision이 snapshot과 일치할 때만 교체하여 사용자 수동 수정을 보호하며, JSON 생성·파싱 실패 또는 미지원 Provider에서는 임시 제목을 유지합니다.
- 상태: `queued`, `running`, `approval`, `completed`, `failed`, `cancelled`
- 안정 정렬: `즐겨찾기 우선 → 최근 활동 내림차순 → session_id`
- 초기 요청량은 viewport와 행 높이를 바탕으로 계산하고 Backend가 최소·최대 limit을 적용합니다.
- cursor pagination으로 오래된 Session을 점진 로딩합니다.
- 즐겨찾기, 제목 수정과 삭제를 `…` 메뉴로 제공합니다.
- 즐겨찾기와 좋아요는 서로 다른 사용자 의도입니다. `is_favorite`는 목록 상단 정렬, `is_liked`는 사용자가 보존할 가치가 있다고 표시한 대화와 `좋아요만 보기` filter에 사용합니다. 둘 다 Conversation revision을 검사해 PATCH하고 서버 DB에서 기기 간 복원합니다.
- 대화 좋아요는 assistant Message의 좋아요·싫어요 품질 feedback과 별개입니다. 자동 보존 정리에서는 `is_liked=true` 대화를 제외하지만 모델 Context나 사용자 선호 학습으로 자동 투입하지 않습니다.
- 메뉴 조작은 행 선택과 keyboard focus를 분리하고 scroll 위치를 유지합니다.
- 실행 중 또는 Queue가 남은 Session 삭제는 Run과 Queue 정리 정책을 먼저 안내합니다.

### 8.2 검색

- Sidebar 검색은 제목 전용이며 아직 로딩하지 않은 전체 허용 Session을 서버에서 검색합니다.
- 대소문자를 구분하지 않고 앞뒤 공백과 연속 공백을 정규화합니다.
- 한국어와 부분 문자열 검색을 지원합니다.
- 제목·메시지 통합 검색은 별도 화면과 API로 제공합니다.
- 현재 `GET /api/conversations/content-search`는 권한 있는 Conversation의 user·assistant Message를 검색해 Conversation, Message, role, 생성 시각과 match 주변 snippet을 반환합니다. 이미 열린 Turn만 client에서 훑지 않고 서버의 전체 허용 범위에서 검색합니다.
- SQLite FTS 가능 여부를 검증하고 CJK 환경에서는 적절한 fallback을 둡니다.
- 검색 전에 사용자·조직·Project·공유 권한을 적용합니다.

### 8.3 Turn Set pagination

대화 본문 pagination 단위는 개별 Message가 아니라 다음을 묶은 `Turn Set`입니다.

```text
Turn Set
├─ user request or follow-up
├─ assistant partial output
├─ Plan / Step / Tool / approval events
└─ final assistant message
```

- Session을 열면 최근 Turn Set 3개를 기본으로 가져옵니다.
- 위로 스크롤하면 이전 Turn Set을 원자적으로 추가합니다.
- 현재 구현은 첫 page가 열린 뒤 `has_more_before=true`이면 직전 page를 background에서 선행 요청하고, 사용자가 상단 임계값에 접근했을 때 준비된 page를 즉시 prepend합니다. 선행 요청 실패는 현재 대화를 지우지 않으며 상단 접근 시 다시 시도합니다.
- `before_cursor`, `limit_turn_sets`, `has_more_before`를 사용합니다.
- 과거 항목 삽입 전후 첫 visible Message의 화면 위치를 보존합니다.
- live event와 과거 load는 `message_id`, `run_id`, sequence로 중복을 제거합니다.

### 8.4 분기와 내보내기

- 현재 분기는 완료된 transcript의 특정 Message까지를 새 Conversation에 복제하고 `parent_conversation_id`, `branch_message_id`와 source Message 관계를 보존합니다. 실행 중 draft나 미확정 Tool outcome을 완료 transcript처럼 복제하지 않습니다.
- 현재 내보내기는 JSON과 Markdown을 지원하며 안전한 제목 기반 filename과 canonical Message 순서를 사용합니다. 관련 Artifact를 포함한 재현 bundle은 후속 확장입니다.
- 파일 기반 재현 bundle은 `session.json`, `messages.jsonl`, `runs.jsonl`, `tool-calls.jsonl`, attachments, artifacts와 logs를 포함할 수 있습니다.
- 운영 데이터의 원본은 export folder가 아니라 DB와 Object Storage입니다.

## 9. Agent Run과 Loop

### 9.1 Run 상태

```text
queued
→ preparing
→ model_streaming
→ awaiting_approval
→ tools_running
→ model_streaming
→ completed | failed | cancelled | interrupted
```

Plan의 Step과 Subtask는 `queued`, `running`, `blocked`, `approval`, `completed`, `failed`, `cancelled`를 사용합니다.

Run은 생성 시 조직의 관리자 안전 설정을 snapshot으로 고정하고 model Turn, 총 Token, 경과 시간과 예상 비용을 Run 단위로 계산합니다. 기본값은 400 Turn, 4,000,000 Token, 10,080분(7일), $100이며 같은 Session의 다음 Run은 새 한도로 다시 시작합니다. 모델 Context가 임계치에 가까워지면 원문과 Tool 근거를 영속 저장한 상태에서 이전 진행을 복구 가능한 summary로 압축하고, 최신 대화·현재 Plan·미완료 작업을 유지한 채 같은 Run을 계속 실행합니다. 압축 revision, source message 범위·hash와 전후 추정 token 수는 event와 snapshot에 기록합니다.

Run 상태는 여러 boolean (`is_running`, `is_paused`, `is_failed`)으로 중복 저장하지 않고 하나의 enum과 상태별 timestamp로 관리합니다. 상태 변경은 한 module의 transition function과 DB compare-and-set을 통과해야 하며, 허용되지 않은 전이는 거부하고 audit 대상 오류로 남깁니다. Frontend의 버튼 활성화와 badge는 canonical status에서 파생합니다.

### 9.2 한 Turn의 처리

1. 시스템·조직·Agent·Project·사용자 지침과 대화 Context를 조합합니다.
2. Provider, Model, Effort, Agent, Tool, Skill, MCP와 권한을 snapshot으로 고정합니다.
3. Provider Adapter가 공통 요청을 Provider 형식으로 변환합니다.
4. text delta, usage, stop reason과 Tool Call을 공통 event로 정규화합니다.
5. Tool Call이 없으면 final assistant message와 usage를 저장하고 완료합니다.
6. Tool Call 입력을 schema로 검증하고 `pre_tool_use`와 권한 검사를 수행합니다.
7. Run snapshot의 `approval_mode`를 적용합니다. 기본 `on_risk`는 읽기와 내부 저위험 Artifact 생성을 즉시 실행하되 외부 write·삭제 등 위험 effect를 `awaiting_approval`로 전환합니다.
8. Tool을 실행하고 성공·실패 결과를 원래 Tool Call ID에 연결합니다.
9. `post_tool_use`, Artifact 저장과 checkpoint를 수행합니다.
10. Tool Result를 Context에 추가하고 다음 model Turn을 실행합니다.

### 9.3 Tool 실행 규칙

- Registry에 등록되고 현재 Run snapshot에서 허용된 Tool만 실행합니다.
- 파일 경로, 명령, 네트워크 대상과 effect를 실행 전에 검사합니다.
- 독립 Tool Call은 병렬 실행하되 하나의 실패가 다른 결과를 취소하지 않게 합니다.
- 모든 Tool Call에는 성공 또는 구조화된 오류 Tool Result가 있어야 합니다.
- 큰 출력은 Artifact에 저장하고 요약·참조만 Context에 둡니다.
- Tool별 timeout, retry, output size와 idempotency 정책을 적용합니다.
- 부작용 Tool을 재시도하기 전 이전 완료와 idempotency key를 확인합니다.

### 9.4 종료 제한

- Tool Call 없는 최종 답변
- 사용자 취소
- Run snapshot의 model Turn 한도 도달
- 개별 Provider·Tool 호출 timeout으로 인한 재시도 또는 복구 불가능한 실패
- Run snapshot의 총 Token·경과 시간·예상 비용 한도 도달
- 관리자의 조직 전체 비상 중단
- 복구할 수 없는 Provider·Storage 오류
- Worker 중단 또는 서버 종료

한도 도달 시 기존 Run snapshot, 부분 결과, checkpoint와 usage를 보존하고 `limit_reached` terminal event를 남깁니다. 설정 변경은 진행 중 Run에 소급하지 않고 새 Run부터 적용합니다. 관리자의 비상 전체 중단은 조직 범위의 활성·대기·중단된 Run, 승인·Tool 상태와 대기 Message를 취소하고 실행 중인 local task에 cancellation을 전달하며 감사 이벤트를 기록합니다.

### 9.5 Session별 병렬과 Queue

- Session별 동시 Run 기본값: 1
- 사용자별 동시 Run 권장 초기값: 3
- 서버 전체 동시 Run: 운영 설정
- 사용자 한도 초과 요청은 실패시키지 않고 `queued`로 둡니다.
- 서로 다른 Session은 병렬 실행할 수 있습니다.
- 같은 Session의 추가 요청은 `steer` 또는 `queue_next`로 명확히 분류합니다.

### 9.6 Plan, Step, Subtask

```text
Run
└─ Plan
   ├─ Step A: completed
   ├─ Step B: running
   │  ├─ Subtask B1: running
   │  └─ Subtask B2: running
   └─ Step C: queued, depends_on B
```

- Plan은 UI용 문장이 아니라 Backend가 상태와 dependency를 추적하는 객체입니다.
- Step마다 입력, Context, Provider 옵션, Tool version, 결과, 오류와 Artifact를 저장합니다.
- 독립 Subtask만 사용자·서버 한도 안에서 병렬 실행합니다.
- 실패 Step retry는 완료 Step을 되돌리지 않고 저장된 입력 snapshot을 사용합니다.
- 사용자 화면에는 Backend의 고정 실행 경계 대신 모델이 `update_plan`으로 작성한 요청별 업무 계획을 표시합니다. 이 계획은 실제 대상과 결과가 드러나는 단계, `pending | in_progress | completed` 상태와 안정적인 ID를 Run snapshot과 `work_plan_updated` event에 저장합니다.
- Timeline은 model turn이 아니라 사용자가 이해하는 업무 단계 중심으로 표시하며, 상세 Tool log는 별도 활동 영역에 둡니다.

### 9.7 Batch Fan-out

동형 항목 다수를 독립 fresh context로 처리할 때 일반 병렬 Subtask와 별도로 사용합니다.

```text
BatchFanoutStep
├─ input_dataset_artifact_id
├─ item_selector
├─ shared_instruction_snapshot
├─ per_item_context_policy: fresh
├─ output_schema / evaluation_rules
├─ concurrency_limit / item_budget
├─ synthesis_strategy
└─ partial_failure_policy
```

- item worker는 공통 지침과 자신의 항목만 받습니다.
- 결과는 동일 schema, 비용, 출처와 검증 상태로 저장합니다.
- 실패 item만 재시도합니다.
- fan-out 전에 worker 수, 비용 상한과 외부 요청량을 계산합니다.

### 9.8 실행 중 입력

```text
Enter or send button  → steer
Ctrl+Enter            → queue_next
Shift+Enter           → newline
```

`steer`는 현재 Run의 다음 안전한 model Turn 또는 Step 경계에 적용합니다. Provider가 안전한 생성 취소를 지원하면 text streaming을 협력적으로 중단하고 부분 답변을 `interrupted_by_steer`로 보존합니다. 부작용 Tool은 강제 중단하지 않고 Result 저장 후 적용합니다.

`queue_next`는 현재 Run을 변경하지 않으며 terminal state 뒤 새 Run으로 정확히 한 번 승격합니다. 전송 당시 첨부와 실행 옵션 의도는 보존하되 실행 직전에 권한과 유효성을 다시 검사합니다.

필수 상태 이벤트는 다음과 같습니다.

```text
steer_received
steer_waiting_safe_boundary
steer_applied
steer_cancelled
queued_message_added
queued_message_cancelled
queued_message_promoted_to_run
```

확인 질문은 일반 steer와 별도의 durable 입력 대기 흐름입니다.

- 계정 설정은 `autonomous | balanced | confirming`이며 Run 생성 시 `clarification_mode`로 snapshot합니다.
- Agent가 질문하기로 결정하면 visible assistant text에 질문을 흘리지 않고 `request_user_input` Tool을 단독 호출합니다. 한 Run에서 최대 한 묶음, 묶음당 1~10개 질문과 각 2~4개 객관식 선택지를 허용하고 UI가 직접 입력 선택지를 추가합니다.
- Backend는 질문 묶음과 Tool checkpoint를 Run snapshot에 저장하고 `input_requested` event 뒤 상태를 `awaiting_input`으로 바꿉니다. 재시작·재접속에서도 질문 card와 이미 제출한 답을 복원합니다.
- 사용자는 객관식, 직접 입력 또는 `AI가 판단`으로 답할 수 있습니다. `submit_user_input`은 모든 질문의 답과 중복을 검증하고 `input_submitted`를 저장한 뒤 Run을 Queue로 돌려 같은 checkpoint에서 재개합니다.
- `awaiting_input` 동안 모델 작업 시간은 진행 중으로 누적하지 않고 pause·approval과 구분한 `Q&A` 상태를 표시합니다. Tool 승인은 이 흐름으로 대체하지 않습니다.

### 9.9 Pause, resume, cancel과 retry

- pause는 새 Tool 시작을 막고 현재 안전한 작업 종료 후 checkpoint를 저장합니다.
- resume은 저장된 Tool Result와 Context에서 이어가며 임의의 새 사용자 메시지를 삽입하지 않습니다.
- cancel, pause, resume, steer와 retry는 idempotent command API를 사용합니다.
- side-effect Tool 재실행 전 완료 여부를 검사합니다.
- 누가 action을 수행했는지 audit에 남깁니다.
- 활성 Run이 있고 Composer에 새 text·attachment가 없으면 기본 전송 버튼을 명확한 위험색의 중단 버튼으로 바꿉니다. click 또는 Enter는 idempotent `cancel` action을 호출하고 처리 중에는 중복 입력을 막습니다.
- 활성 Run 중에도 Composer payload가 있으면 같은 위치는 중단이 아니라 현재 작업 반영 action을 유지합니다. 중단 상태와 steer 상태를 icon 색상만으로 구분하지 않고 `aria-label`과 tooltip에 함께 표시합니다.

## 10. 실행 환경과 Context 관리

### 10.1 Execution Environment

```text
ExecutionEnvironment
├─ ephemeral_sandbox
├─ persistent_workspace
└─ user_managed
```

| 환경 | 용도 | 내구성·권한 |
|---|---|---|
| `ephemeral_sandbox` | 문서 분석, 일회성 코드 실행 | 선언된 durable output만 보존 |
| `persistent_workspace` | 장기 crawler, Project 개발 서버 | Project 또는 사용자 scope, quota·shutdown 정책 |
| `user_managed` | 로컬 파일, 로그인된 브라우저·앱 | 사용자 presence, path·session 범위 승인 |

Run snapshot에는 `environment_id`, type, 선택 이유, durability·network policy, authorized paths/browser session, 만료 시각과 recovery manifest를 저장합니다. 사용자 로컬 환경으로 자동 승격하지 않습니다.

초기 구현은 `environment_type=local_worker`와 비밀이 아닌 실행 snapshot만 Run에 직접 저장합니다. 별도 `execution_environments` table, scheduler와 lifecycle manager는 persistent 또는 user-managed 환경을 실제로 도입하는 시점까지 만들지 않습니다.

### 10.2 복원 가능한 Context 압축

```text
CompactedContextEntry
├─ compaction_id / version
├─ summary
├─ source_message_range / source_event_range
├─ source_refs[] / source_version_or_hash
├─ retrieval_policy
├─ access_scope
├─ estimated_tokens_before / after
├─ summary_model / prompt_version
└─ compacted_at
```

- 매 model 호출 전 `effective_input_budget = model_context_window - reserved_output_tokens - tool_schema_tokens - safety_margin`을 계산합니다. 추정 입력이 기본 soft threshold인 유효 예산의 75%를 넘으면 선제 압축하고, Provider가 보고한 실제 token 값을 추정치보다 우선합니다. Codex GPT-5.4·5.5·5.6 계열만 서비스 정책상 272K Context와 85% 임계값을 사용합니다. P-GPT·OpenAI·Gemini·Claude API는 Model Catalog에 검증된 각 표준 API Context window를 사용하고 Codex 제한을 상속하지 않습니다. model profile의 상향 임계값은 낮추지 않으며 메시지 개수만으로 압축을 결정하지 않습니다.
- 최근 사용자·assistant Turn과 미완료 Tool Call/Result pair는 그대로 남기고, 오래된 중간 구간을 구조화 요약 하나로 교체합니다.
- 요약에는 목표, 사용자 제약과 선호, 현재 Plan·Step, 완료 작업, 실패·차단 상태, 핵심 결정, 미해결 질문, 승인 상태, 부작용 결과, idempotency key, 관련 파일·Artifact·citation/source ID와 다음 확인 항목을 보존합니다.
- 오래된 Tool 출력은 Artifact 또는 source reference로 전환합니다.
- URL은 재조회 시 달라질 수 있으므로 fetch snapshot 또는 hash를 남깁니다.
- 파일·Artifact 재조회 시 Project와 사용자 권한을 다시 검사합니다.
- 원본 DB가 별도로 없는 정보의 비가역 요약은 피합니다.
- 각 model Turn 직전 `goal + active step + unresolved constraints + next check`의 bounded plan digest를 재주입합니다.
- 과거 image·PDF binary와 base64를 매 Turn 반복 전송하지 않고 첫 분석 뒤에는 권한 검증 가능한 attachment reference와 추출 결과를 사용합니다. 다시 시각 분석해야 할 때만 원본 payload를 재로딩합니다.
- 압축은 새 Context lineage를 만드는 원자적 작업입니다. 요약 생성·저장·검증 중 하나라도 실패하면 기존 Context를 유지하며, 인증·network 오류 때문에 원문을 버린 placeholder 압축으로 진행하지 않습니다.
- 압축 전후 token 절감률과 cache hit 변화를 기록합니다. 절감이 미미한 압축을 반복하지 않도록 cooldown과 연속 ineffective count를 두며, hard limit 직전에는 사용자에게 선택 가능한 복구 경로를 보여줍니다.
- 압축 전후 목표, 승인 상태, 부작용 결과, Tool pair, 인용과 idempotency key 보존을 테스트합니다.

### 10.3 Prompt cache와 token 비용 최적화

Cache hit은 Provider가 자동으로 만들어 주는 부수 효과가 아니라 Context 조립의 품질 지표로 관리합니다.

```text
stable prefix
├─ system security and product instructions
├─ organization / agent / project instructions in deterministic order
├─ stable tool definitions selected for the Run
└─ session-scoped capability and workspace snapshot

append-only tail
├─ conversation messages and tool pairs
├─ current request attachments and references
└─ current-turn volatile context
```

- Run 시작 시 system prompt, 지침, Tool schema, Provider·Model capability와 workspace snapshot을 canonical serialization하고 hash를 저장합니다. 동일 Run 안에서는 바이트 단위로 재사용하며 timestamp, request ID, 경과 시간, 무작위 순서와 live 상태를 stable prefix에 넣지 않습니다.
- 서로 다른 채팅 Session도 같은 인증 사용자와 동일한 고정 prompt prefix라면 캐시 라우팅을 재사용합니다. 정규화한 로그인 ID(email)의 비가역 hash를 사용자 scope로 만들고, Provider·Model·고정 system prompt·정렬된 Tool schema의 내용 hash를 결합한 `prompt_cache_key`를 모델 요청 시 생성합니다. 이메일 원문은 Provider 요청이나 로그에 넣지 않으며, 요청별 output mode·현재 Message·recall 같은 변동 정보는 안정된 system·Tool prefix 뒤에 둡니다. 한 Run이 시작된 뒤에는 Tool schema를 제거하거나 재정렬하지 않고 호출 상한은 실행 단계에서 거부하여 prefix를 유지합니다. Codex는 같은 Run의 App Server thread를 재사용해 후속 Turn에는 새 Tool Result·사용자 지시만 증분 전달합니다. Backend·App Server 재시작, context compaction 또는 prefix 불일치로 thread를 재사용할 수 없으면 snapshot의 전체 요청을 새 ephemeral thread에 재구축합니다.
- OpenAI GPT-5.6 이상은 `prompt_cache_options.ttl=30m`을 사용하고 이전 지원 Model은 `prompt_cache_retention=24h`를 사용합니다. Provider가 지원하지 않는 cache control을 공통 옵션처럼 강제로 전송하지 않습니다.
- Tool·Skill·MCP의 검색과 선택은 Run 시작 전에 끝내고 snapshot으로 고정합니다. 설치·활성화·지침 변경은 기본적으로 다음 Run부터 적용하며, 사용자가 즉시 적용을 선택하면 cache 무효화와 비용 영향을 알리고 새 Run snapshot을 만듭니다.
- 이전 message와 Tool Call JSON은 append-only로 유지하고 key 순서·whitespace·role 배열을 매 호출마다 다시 쓰지 않습니다. Provider 제약에 따른 정규화는 저장 원본이 아닌 전송용 copy에 결정론적으로 적용합니다.
- 변동하는 memory recall, 현재 시각, 검색 결과와 현재 Turn 전용 힌트는 prefix 뒤쪽의 user/context block에 둡니다. 동일 정보를 system prompt에 재주입하지 않습니다.
- Provider adapter는 OpenAI 계열의 cached input, Anthropic 계열의 cache read/write와 Google 계열의 cache usage를 공통 usage로 정규화하되, 지원하지 않는 explicit cache control을 흉내 내지 않습니다.
- 호출별로 `input_tokens`, `cached_input_tokens`, `cache_write_tokens`, `uncached_input_tokens`, `output_tokens`, provider raw usage와 가격표 version을 저장합니다. `cache_hit_ratio = cached_input_tokens / max(1, cached_input_tokens + uncached_input_tokens)`로 표시하고 Provider가 total input에 cached token을 포함하는지 adapter test로 고정합니다.
- 비용은 cache read·write·일반 input의 서로 다른 단가를 반영합니다. 두 번째 이후 Turn에서 prefix hash가 이유 없이 달라지거나 cache hit이 급락하면 변경 원인을 `system_prompt`, `tool_schema`, `instructions`, `compaction`, `provider`로 분류합니다.
- Context 압축은 기존 prefix cache를 끊을 수 있으므로 압축 시점을 event로 남깁니다. 압축 후 새 lineage를 다시 안정된 prefix로 사용하고 매 Turn 재압축하지 않습니다.

### 10.4 위험 기반 실행 승인과 Permission Lease

```text
approval_mode
├─ on_risk      # 기본값, 외부 write·삭제 등 위험 effect만 확인
├─ confirm_all  # read-only를 제외한 effect를 실행 전에 확인
└─ yolo         # 관리자가 명시한 격리 환경에서만 확인 생략
```

- `local_worker`와 `ephemeral_sandbox`의 기본값은 `on_risk`입니다. 검색·조회와 Lumina 내부 Artifact 생성은 즉시 실행하고, 외부 전송·게시·변경·삭제와 분류되지 않은 MCP write Tool은 one-shot 승인을 요구합니다.
- 어떤 mode도 authorization, sandbox와 policy를 우회하지 않습니다. Run snapshot의 Project root, 허용 domain·Tool, quota와 다른 사용자 데이터 경계를 벗어난 요청은 확인창으로 승격하지 않고 거부합니다.
- 실행 mode는 system default → organization policy → Project setting → Run 명시 선택 순서로 결정하고 Run 시작 후 snapshot으로 고정합니다. 더 상위 정책이 금지한 capability를 하위 scope가 `yolo`로 풀 수 없습니다.
- `confirm_all`은 운영자가 특정 Project 또는 capability에 명시적으로 설정했을 때 사용합니다. `on_risk`와 `confirm_all`의 승인 panel은 같은 durable ToolApproval과 `awaiting_approval` 상태를 사용합니다.
- 향후 `user_managed` 환경에서 사용자 PC, 로그인된 browser·app을 제어하게 되면 해당 환경의 별도 기본 mode를 다시 결정합니다. 현재 `local_worker`의 `on_risk` 분류를 실제 사용자 PC 제어 권한으로 자동 승계하지 않습니다.

```text
PermissionLease
├─ actor_id
├─ run_id or session_id
├─ capability
├─ resource_scope
├─ effect_scope
├─ constraints
├─ issued_from_approval_id
├─ expires_at or max_uses
└─ revoked_at
```

- 승인은 현재 Tool Call 한 번에만 유효합니다.
- 반복 허용은 현재 Run, 특정 path read, 특정 domain 조회처럼 좁은 scope로 발급합니다.
- 외부 전송, 공개 게시, 결제, 삭제와 credential 변경은 broad lease에서 제외합니다.
- steer, 공유 전환, 정책 변경과 Run 종료 시 lease를 재평가하거나 폐기합니다.

현재 구현은 one-shot `ToolApproval`을 영속 저장합니다. 같은 승인 범위를 반복 재사용해야 하는 workflow가 확인된 뒤에만 `PermissionLease` table과 reuse policy를 추가합니다.

## 11. 상태 복구와 Event 계약

### 11.1 Event envelope

```text
run_id
conversation_id
sequence
event_type
payload
created_at
```

- sequence는 Run 안에서 단조 증가합니다.
- Backend는 완전한 snapshot과 replay에 필요한 주요 event를 저장합니다.
- Frontend는 Session별 마지막 sequence를 기억합니다.
- 재연결 시 `after_sequence` 또는 `Last-Event-ID`를 전달합니다.
- snapshot 이후 누락 event를 replay한 뒤 같은 cursor 경계에서 live stream으로 전환합니다.
- Frontend reducer는 `run_id + sequence`로 idempotent하게 적용합니다.
- Provider가 반환하는 token·문자 단위 delta를 그대로 모두 DB row로 만들지 않습니다. Backend는 짧은 시간창 또는 문자 수 기준으로 `assistant_text_chunk`를 합치고 sequence를 부여합니다.
- 누적 assistant draft는 주기적 checkpoint와 Run snapshot에 저장하며 완료 시 canonical final Message로 원자적으로 수렴합니다.
- Tool, approval, status, Artifact와 Run terminal event는 durable event로 보존합니다. 세밀한 text chunk는 final Message와 checkpoint가 안전하게 저장된 뒤 retention 정책에 따라 compact할 수 있습니다.
- Frontend로 보내는 canonical `assistant_text_chunk`와 DB에 저장하는 chunk는 같은 durable sequence를 사용합니다. 더 부드러운 표현은 Frontend reveal buffer가 담당하며 별도의 유실 가능한 protocol을 추가하지 않습니다.

### 11.2 Canonical event 유형

```text
run_started / run_status_changed
turn_started
progress_summary
work_plan_updated
assistant_text_delta
assistant_turn_completed / message_completed
approval_requested
input_requested / input_submitted
tool_started / tool_completed
artifact_created
message_feedback_changed / message_comment_changed
conversation_moved
memory_candidate_created / memory_changed
skill_draft_updated / skill_version_saved / skill_visibility_changed / skill_folder_changed
context_compacted
retry_scheduled
run_completed / run_failed / run_cancelled / run_interrupted
```

`progress_summary`는 Provider의 raw reasoning을 그대로 전달하는 이벤트가 아닙니다. Agent가 사용자에게 공개할 수 있는 판단 결과·현재 작업·다음 행동만 간결하게 기록하며, Tool 시작 event와 같은 durable sequence로 저장해 snapshot·replay 후에도 하나의 실행 Timeline 순서를 복원합니다. 사용자 표시 업무 계획은 `update_plan`으로 요청 목적과 산출물에 따라 동적으로 구성하고 `work_plan_updated`로 복원하며, 실제 Tool Call은 Backend 실행 Plan의 Subtask로 별도 추적합니다.

`approval_requested`는 `on_risk`에서 위험 effect가 감지되거나 `confirm_all`에서 read-only가 아닌 effect를 실행할 때 발생합니다. 이벤트 naming은 API version에서 하나로 정규화하되 기존 의미를 모두 보존합니다.

### 11.3 Frontend Session store

- Session마다 Message, canonical assistant draft, Run snapshot, last sequence, scroll 상태를 분리합니다.
- 화면 전환 시 state를 삭제하거나 다른 Session state로 덮지 않습니다.
- cache를 즉시 보여준 뒤 Backend snapshot과 replay로 동기화합니다.
- 경과 시간은 `started_at` 기준으로 계산합니다.
- 현재 보고 있지 않은 Session도 badge와 알림을 갱신합니다.
- `isStreaming`, `isWaitingApproval`, `isPaused` 같은 중복 boolean을 각각 갱신하지 않습니다. Run status, active Tool과 pending command에서 화면 상태를 selector로 파생합니다.
- server entity cache와 panel·scroll·draft 같은 local UI state를 분리합니다. event reducer는 server entity만 갱신하고 component가 별도의 canonical copy를 만들지 않습니다.
- active Conversation을 전환한 직후 `loaded=false`이고 오류가 없으면 이전 대화나 신규 대화 welcome을 잠깐 표시하지 않고 `aria-busy`가 있는 복원 loading을 표시합니다. 빈 대화 welcome은 Conversation이 없거나 선택한 Conversation의 초기 load가 완료된 뒤에만 표시합니다.

### 11.4 Text reveal과 scroll follow

canonical draft, 화면 reveal buffer와 scroll follow를 별도 상태로 둡니다.

- 새 요청 직후의 응답은 `following`으로 시작합니다.
- 사용자가 wheel, touch 또는 scrollbar로 위를 읽으면 즉시 `detached`로 전환합니다.
- `detached` 상태의 새 delta는 위치를 바꾸지 않고 새 응답 affordance를 표시합니다.
- 하단 근처 복귀 또는 `최신 응답으로 이동`으로 `following`을 재개합니다.
- Session 복귀 시 snapshot과 replay는 타자 효과 없이 즉시 적용하고 live delta만 이어서 표현합니다.
- `restoring` 중에는 replay가 끝날 때까지 자동 이동 결정을 보류합니다.
- `prefers-reduced-motion`에서는 보간 animation을 생략합니다.
- Markdown의 불완전 fence, table, link와 HTML은 안전한 pending 표현을 사용합니다.

## 12. Provider 계층

### 12.1 Provider 구조

```text
apps/server/src/lumina/providers/
├─ codex/
├─ openai/
├─ openai_compatible/
├─ pgpt/
├─ anthropic/
└─ google/
```

모든 Provider는 다음 공통 계약을 제공합니다.

- text와 streaming delta
- Tool Call ID, 이름, 입력과 stop reason
- structured output
- image·document input 지원 여부와 허용 MIME·size·page limit
- reasoning·effort option
- token, cached input, cache write와 비용 usage
- server-side conversation 여부
- retry 가능 오류 분류
- capability metadata

지원하지 않는 기능을 흉내 내지 않고 실행 전에 capability를 검사합니다. Provider·Model 변경은 다음 Run부터 적용합니다.

구현은 깊은 base class 상속보다 작은 `ProviderAdapter` Protocol과 composition을 우선합니다. OpenAI와 P-GPT가 공유하는 message·Tool·usage 변환은 `openai_compatible` helper로 재사용하되 P-GPT 인증·진단을 generic adapter의 조건문으로 섞지 않습니다. Provider마다 같은 retry, logging과 stream loop를 복사하지 않고 공통 runner가 adapter 결과를 처리합니다.

### 12.2 Provider 선택값 저장

- 개인 mode: 사용자 설정
- Project shared mode: 공유 Workspace 설정
- Provider별 마지막 Model, Provider·Model별 마지막 Effort를 분리 저장
- Effort의 초기 기본값은 `Auto`입니다. 사용자가 `low`·`medium`·`high`를 명시하면 Run 전체에서 그대로 유지합니다. `Auto`는 별도 분류 모델 호출 없이 `low`를 기본으로 사용하며 일반 조사·복잡 작업·산출물 생성·첨부 또는 참조 3개 이상은 `medium`, 사용자가 심층·철저·전수 조사 범위를 명시한 경우만 `high`를 사용합니다. Agent Turn이 이어졌다는 이유만으로 Effort를 올리지 않습니다. Gemini는 `Auto`일 때 Provider의 동적 thinking 기본값을 사용하고 명시 Effort만 Model 계열에 맞는 `thinkingLevel` 또는 `thinkingBudget`으로 전달합니다.
- 각 Model Turn은 요청 Effort, 실효 Effort, TTFT, 전체 소요 시간, cached·uncached input Token과 cache hit ratio를 `model_turn_completed` event와 Run snapshot에 남깁니다. Prompt·Tool Result 원문이나 cache key는 계측 payload에 넣지 않습니다.
- 계정 메뉴의 Model 후보 체크리스트는 사용자 설정으로 저장하며 Provider별 복수 선택과 0개 선택을 허용합니다. 최초 사용자에게는 `Codex`와 `P-GPT`의 활성 Model만 후보로 제공하고, 이후에는 서버 DB에 저장된 마지막 후보 선택을 복원합니다. Composer의 Model 목록에는 체크된 후보만 표시하고, 현재 실행 Model이 후보에서 해제되면 자동 전환하지 않고 `재설정 필요`를 표시합니다.
- Project Folder에 기본 Provider·Model·Effort가 있으면 해당 Project의 새 Session과 Run에 적용하고, 사용자의 다른 Project 마지막 선택을 덮어쓰지 않습니다.
- 적용 순서: 시스템 강제 정책 → 조직 정책 → 현재 Session 명시 선택 → Project 기본값 → 해당 scope에 저장된 마지막 값 → app default
- 삭제되거나 금지된 값은 허용 기본값으로 fallback하고 사용자에게 알림
- 비밀번호, token, 승인과 임시 Run 상태는 마지막 값으로 저장하지 않음

### 12.3 Provider별 초기 Model Catalog

모델 목록은 Adapter 내부의 조건문이나 Frontend 상수로 흩어 놓지 않고 Backend의 versioned Model Catalog를 원본으로 사용합니다. 사용자가 지정한 P-GPT·Codex·Gemini 목록은 제품 계약으로 고정하고, 나머지 Provider는 2026-07-11 기준 공식 문서에서 확인한 최신 계열 중 품질·균형·속도 역할을 대표하는 소수만 초기 노출합니다.

| Provider | UI 표시명 | `runtime_model_id` 기본값 | 초기 기본 Model | 결정 근거 |
|---|---|---|---|---|
| `pgpt` | `GPT-5.4` | `gpt-5.4` | 예 | 사용자 지정 |
| `pgpt` | `GPT-5.4-mini` | `gpt-5.4-mini` | 아니요 | 사용자 지정 |
| `pgpt` | `GPT-5.5` | `gpt-5.5` | 아니요 | 사용자 지정 |
| `pgpt` | `GPT-5.6-Sol` | `gpt-5.6-sol` | 아니요 | 사용자 지정 |
| `pgpt` | `GPT-5.6-Terra` | `gpt-5.6-terra` | 아니요 | 사용자 지정 |
| `pgpt` | `GPT-5.6-Luna` | `gpt-5.6-luna` | 아니요 | 사용자 지정 |
| `codex` | `GPT-5.5` | `gpt-5.5` | 예 | ChatGPT OAuth App Server 공개 catalog |
| `codex` | `GPT-5.4` | `gpt-5.4` | 아니요 | ChatGPT OAuth App Server 공개 catalog |
| `google` | `Gemini-3.1-Pro` | `gemini-3.1-pro` | 예 | 사용자 지정 |
| `google` | `Gemini-3.5-flash` | `gemini-3.5-flash` | 아니요 | 사용자 지정 |
| `openai` | `GPT-5.6-Sol` | `gpt-5.6-sol` | 예 | OpenAI 최신 flagship |
| `openai` | `GPT-5.6-Terra` | `gpt-5.6-terra` | 아니요 | OpenAI 최신 균형형 |
| `openai` | `GPT-5.6-Luna` | `gpt-5.6-luna` | 아니요 | OpenAI 최신 효율형 |
| `anthropic` | `Claude Opus 4.8` | `claude-opus-4-8` | 아니요 | 복잡한 Agent 작업 |
| `anthropic` | `Claude Sonnet 5` | `claude-sonnet-5` | 예 | 품질·속도 균형 |
| `anthropic` | `Claude Haiku 4.5` | `claude-haiku-4-5` | 아니요 | 고속·저비용 |

OpenAI 항목은 [공식 최신 모델 가이드](https://developers.openai.com/api/docs/guides/latest-model.md), Anthropic 항목은 [공식 모델 개요](https://platform.claude.com/docs/en/about-claude/models/overview)와 [모델 선택 가이드](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)를 기준으로 선정했습니다. 외부 Provider의 `latest` alias는 실행 결과가 예고 없이 바뀔 수 있으므로 Run 재현용 ID로 저장하지 않습니다. 구현 직전과 catalog 갱신 시 공식 문서를 다시 확인하고, 변경은 관리자 검토를 거쳐 catalog revision으로 배포합니다.

Codex text Provider는 OpenAI API Key가 아니라 로컬 Codex App Server의 `chatgpt` 인증 모드만 사용합니다. Backend는 Codex 자식 프로세스에서 `OPENAI_API_KEY`를 제거하여 API 과금 경로로 자동 fallback하지 못하게 하며, OAuth runtime이 보고한 검증 모델만 활성화합니다. `OpenAI` Provider의 API Key와 사용량은 Codex 구독 사용량과 분리합니다. Codex OAuth 경로에서 지원하지 않는 Lumina 전용 Tool은 API Key로 우회하지 않고 명시적으로 unavailable 처리합니다.

Codex OAuth의 실제 과금 방식은 모델명 옆에 ChatGPT 구독으로 표시하되, 운영·관리 목적의 비용 비교를 위해 동일 토큰을 공개 단가표로 환산한 `예상비용`을 다른 Provider와 같은 짧은 원화 열로 표시합니다.

`openai_compatible`은 단일 회사의 모델군이 아니므로 고정 초기 목록을 두지 않습니다. 관리자가 등록한 허용 목록을 기본으로 하고, endpoint가 안전한 `/models` discovery를 제공할 때만 후보를 가져와 관리자 allowlist와 교집합을 계산합니다. discovery 실패가 채팅 시작을 막지 않으며 마지막으로 검증된 catalog 또는 수동 등록 목록으로 fallback합니다.

Model Catalog item은 최소한 `provider_id`, 안정된 `model_key`, `display_name`, 실제 전송할 `runtime_model_id`, `aliases`, `enabled`, `is_default`, `sort_order`, capability, source, catalog revision과 확인 시각을 가집니다. 다음 규칙을 적용합니다.

- UI는 `enabled=true`이면서 사용자·조직·Project 정책이 허용한 항목만 표시합니다.
- 표시명과 런타임 ID를 분리합니다. 예를 들어 Codex의 `GPT-5.6-Terra` pill은 `gpt-5.6-terra`로 전송하되 과거 Message와 Run에는 당시 표시명과 ID를 모두 snapshot합니다.
- P-GPT의 `runtime_model_id`는 실제 사내 deployment name과 다를 수 있으므로 관리자 mapping으로 바꿀 수 있습니다. 사용자에게 보이는 제품명은 mapping 변경 때문에 바뀌지 않습니다.
- Provider capability를 같은 Provider의 모든 Model에 일괄 적용하지 않습니다. Tool Call, image input·generation, structured output, effort, context window와 cache 지원 여부를 Model별로 병합·검증합니다.
- P-GPT의 공식 전체 Context window와 실측 입력 상한을 별도 설정으로 구분합니다. 2026-07-17 VS Code Codex 확장 경로 실측 기준 `gpt-5.4-mini`의 입력 상한은 270,000 Token, `gpt-5.5`는 911,900 Token입니다. `gpt-5.4`는 사용자 관측상 `gpt-5.5`와 같은 계열로 추정하여 911,900 Token을 보수적 상한으로 적용하되, 추후 직접 실측값이 나오면 Model Catalog revision으로 교체합니다. 관리자 Context 화면은 공식 전체 Context와 실측 입력 상한을 각각 저장·초기화하며, `min(전체 Context - 출력 예약, 실측 입력 상한) - 안전 여유 - Tool schema`로 실제 입력 예산을 계산합니다. 실측값을 바꿔도 공식 전체 Context나 출력 한도 값은 변경하지 않습니다.
- 실행 중인 Run은 `provider_id`, `model_key`, `runtime_model_id`, capability snapshot과 `catalog_revision`을 고정합니다. catalog 변경은 다음 Run부터 적용합니다.
- 저장된 Model이 disabled·삭제·권한 회수되면 같은 Provider의 허용 기본 Model로 fallback하고 변경 사실을 알립니다. Provider 자체가 불가능할 때만 전체 app default로 이동합니다.
- 관리자가 명시적으로 추가하지 않는 한 새 출시 Model을 자동 활성화하지 않습니다. 자동 discovery는 후보 갱신일 뿐 권한 부여가 아닙니다.

### 12.4 P-GPT

P-GPT는 `openai_compatible` alias가 아니라 전용 Adapter입니다.

```text
apps/server/src/lumina/providers/pgpt/
├─ profile
├─ auth
├─ adapter
└─ diagnostics
```

기본 endpoint는 `http://pgpt.posco.com/s0la01-gpt/v1`이며 `PGPT_BASE_URL`은 관리자용 선택 override입니다. 일반 사용자는 base URL을 입력하지 않아도 됩니다.

인증 envelope는 다음 필드를 UTF-8 JSON으로 직렬화하고 Base64로 인코딩하여 `Authorization: Bearer <token>`으로 보냅니다.

```json
{
  "apiKey": "<PGPT_API_KEY>",
  "companyCode": "<PGPT_COMPANY_CODE>",
  "systemCode": "<PGPT_EMPLOYEE_NO>"
}
```

Base64는 암호화가 아니므로 credential과 동일하게 취급합니다. 신규 설치와 문서는 `PGPT_EMPLOYEE_NO`만 사용하며 legacy migration에서만 과거 key를 읽을 수 있습니다.

Credential 조회 순서는 다음과 같습니다.

1. 요청 사용자에게 연결된 Secret reference
2. 배포 환경의 조직 service credential
3. Project service credential reference
4. 명확한 설정 오류

지원 환경변수는 `PGPT_API_KEY`, `PGPT_EMPLOYEE_NO`, `PGPT_COMPANY_CODE`, 선택적 `PGPT_BASE_URL`입니다.

### 12.5 Codex 전용 이미지 생성

이미지 생성은 초기에는 `provider=codex`인 Run에서만 지원합니다. Codex가 아닌 Provider에서는 `generate_image` Tool schema 자체를 Run Context에 넣지 않고 UI도 비활성화하며, 사용자가 요청하면 다음 Run의 Provider를 Codex로 바꾸는 선택지를 제공합니다. 실행 도중 Provider를 몰래 전환하지 않습니다.

```text
GenerateImageInput
├─ prompt
├─ reference_attachment_ids[]
├─ size / quality
├─ output_format: png | jpeg | webp
├─ background: auto | opaque | transparent
└─ destination_project_id / destination_artifact_id
```

- Backend는 Codex 인증과 현재 model의 `image_generation` capability를 모두 확인한 뒤 Responses image generation Tool을 호출합니다. UI의 Provider 이름만 보고 capability를 가정하지 않습니다.
- reference attachment는 사용자가 접근 가능한 image만 허용합니다. Codex endpoint가 해당 형태의 image reference 또는 editing을 실제 지원하지 않으면 단순 생성 prompt의 참고 Context로만 사용하거나 명확히 거부하며, 지원하는 척하지 않습니다.
- 반환된 base64·stream payload는 크기와 실제 image MIME을 검증한 뒤 managed Storage에 저장하고, Tool Result에는 raw image data 대신 생성된 `artifact_id`, version, preview URL과 metadata를 넣습니다.
- metadata에는 prompt 또는 redacted prompt hash, Codex Provider·Model, 실제 image backend/model, size, quality, format, background, reference attachment ID, source Run·Tool Call, 생성 시각과 content hash를 기록합니다. UI에 요청 model과 실제 생성 backend가 다르면 둘 다 표시합니다.
- 한 Tool Call은 기본적으로 한 장을 생성합니다. 여러 장이 필요하면 각각 독립 Artifact/Tool Result로 추적하여 일부 실패와 retry를 구분합니다.
- 출력 파일명과 Storage key는 사용자 prompt를 그대로 경로로 사용하지 않고 Backend가 안전하게 생성합니다. 생성 결과도 일반 Artifact와 동일한 Project 격리, 공유, 보존과 다운로드 정책을 적용합니다.

## 13. 회사 CA, HTTP와 Web Search

### 13.1 Trust Manager

```text
Public CA bundle
+ Company CA chain
→ Combined runtime bundle
→ Python SSLContext and subprocess environment
```

탐색 순서는 `LUMINA_CA_CERT`, `data/certs/company-ca.crt`, Windows 호환 `C:/POSCO_CA.crt`입니다. 실제 인증서는 Git에 포함하지 않습니다.

초기화 순서는 다음과 같습니다.

```text
Config and Secret mount
→ CA bundle creation and validation
→ HTTP Client Factory
→ Provider / MCP / Web Tool initialization
→ readiness
```

Python에는 필요에 따라 `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `PIP_CERT`, Node에는 `NODE_EXTRA_CA_CERTS`, `npm_config_cafile`을 전달합니다. 애플리케이션이 생성하는 client에는 SSLContext를 명시적으로 주입합니다.

금지 사항은 다음과 같습니다.

- `verify=False`
- TLS 오류 후 검증 없는 재시도
- 인증서·private key를 저장소나 image에 포함
- token, header와 certificate 원문 logging
- 모든 domain에 전역 약한 TLS 적용

호환 mode는 올바른 CA와 server chain 수정을 먼저 시도한 뒤, 관리자 설정·domain allowlist·경고·audit가 있는 특정 trust profile에만 제한합니다.

### 13.2 HTTP Client Factory

```text
create_http_client(
  trust_profile,
  egress_policy,
  proxy_profile,
  timeout,
  redirect_policy
)
```

- `trust_env=False`가 기본입니다.
- proxy는 관리자가 검증한 명시 profile만 사용합니다.
- redirect는 hop마다 URL, DNS와 대상 IP를 재검증합니다.
- URL embedded credential을 거부합니다.
- public web은 loopback과 private IP를 차단합니다.
- corporate web은 관리자 allowlist의 domain·private range만 허용합니다.
- body size, content type, timeout과 redirect 횟수를 제한합니다.
- 외부 HTML은 instruction이 아닌 untrusted data로 표시합니다.

### 13.3 Web Search 선택

1. DuckDuckGo public backend
2. 회사 승인 Search Connector/API
3. 승인된 proxy 경유 Search API
4. 관리자가 허용한 다른 public endpoint
5. Browser automation fallback

실패 시 임의 endpoint로 조용히 전환하지 않습니다. DNS, proxy, TLS, HTTP status와 content policy 단계로 오류를 분류합니다.

전용 Deep Research 실행기는 만들지 않습니다. Agent Loop가 문제의 복잡도에 따라 검색어 생성 → `web_search` → 필요한 문서의 `web_fetch` → 추가 검색 → 상충 근거 확인 → 최종 합성을 반복합니다. 간단한 최신 정보 확인은 한두 번의 검색으로 끝낼 수 있고, 복잡한 조사는 구조화 Plan·진행 event·steer·cancel·예산 제한을 그대로 사용합니다. 최신성 요청, 사용자 제공 URL과 의료·법률·금융 같은 고위험 질의는 Run snapshot의 `web_research_requirement=required`로 고정하고, fetched 본문을 확보하지 못하면 최종 Message를 `researchVerification=unverified`로 표시하여 모델 기억만으로 현재 사실을 검증한 것처럼 보이지 않게 합니다.

### 13.4 검증 가능한 인용과 검색 이력

검색 도구의 화면용 요약과 인용 근거를 같은 문자열로 취급하지 않습니다. Backend가 Tool 결과에서 출처와 근거 문장을 구조화해 보존하고, 모델은 최종 답변에서 해당 source ID만 참조합니다.

```text
SearchInvocation
├─ tool_execution_id
├─ query / backend / purpose
├─ parent_invocation_id
└─ started_at

SourceEvidence
├─ source_id
├─ original_url / normalized_url
├─ title / domain
├─ verbatim_excerpt
├─ query_ids[] / tool_execution_ids[]
├─ fetched_at / content_hash
├─ content_type / extraction_status / search_backends[]
└─ evidence_kind: search_snippet | fetched_content | uploaded_document

MessageCitation
├─ message_id / source_id
├─ marker_number
├─ claim_block_id
└─ status: cited | reference_only
```

- URL은 fragment, 불필요한 trailing slash와 추적 parameter를 정규화하여 중복을 제거하되, 사용자가 여는 original URL은 보존합니다.
- `web_search` snippet을 최초 근거로 저장하고, 같은 URL을 `web_fetch`해 더 정확한 본문을 얻으면 해당 근거로 승격합니다. fetched content와 hash를 저장해 나중에 페이지가 바뀌어도 당시 근거를 설명할 수 있게 합니다.
- 근거 문장은 Tool output에서 그대로 추출한 짧은 구간이어야 합니다. 모델이 hover용 인용문을 새로 작성하게 하지 않으며, 근거가 없으면 문장을 발명하지 않고 `근거 문장 없음` 상태로 표시합니다.
- 최종 답변의 각주 번호는 source가 처음 등장한 순서로 결정하고 같은 source는 같은 번호를 재사용합니다. ①~⑳ 뒤에는 동일한 badge 형태의 일반 숫자를 사용합니다.
- inline marker는 주장 또는 문단 바로 뒤에 놓습니다. hover·keyboard focus 시 첫 줄에 출처 URL, 다음 줄에 따옴표로 감싼 근거 문장을 표시하고, click하면 새 tab에서 원문을 엽니다. tooltip은 screen reader가 읽을 수 있어야 합니다.
- 최종 답변 아래의 `검색 및 참고 출처`에는 Run에서 실제 실행한 검색어를 실행 순서로 중복 제거해 표시하고, 방문·참고한 모든 링크를 번호·제목·domain·URL과 함께 표시합니다. 최종 본문에 직접 인용된 링크와 참고만 한 링크를 구분하되 둘 다 숨기지 않습니다.
- 검색어·출처 목록은 inline citation을 대체하지 않습니다. 답변 복사 시 canonical Markdown에는 번호 각주와 URL을 보존하고, hover 전용 근거 문장은 중복 출력하지 않아 token과 본문 소음을 줄입니다.
- streaming 중에는 번호를 임시로 재배열하지 않습니다. final message와 citation mapping을 원자적으로 확정한 뒤 marker를 붙이고, 확정 전에는 `출처 정리 중` 상태만 보여줍니다.
- HTML·Markdown·PDF 보고서 Artifact도 같은 source ID와 evidence snapshot을 재사용하여 답변과 산출물의 번호·링크·근거가 추적 가능해야 합니다.

## 14. Extension과 Marketplace

Skill·MCP 관리 구현의 제품 참고 기준은 `docs/project-context/EXTENSION_MARKETPLACE.md`와 `.examples/AI_Skill_MarketPlace/`입니다. 예제에서 카탈로그 탐색, 상세 파일 조회, 설치 상태, Fork·작성·수정·삭제 UX를 참고하되 Lumina의 다중 사용자 권한, Project scope, 불변 package version, 검토·감사와 MCP Secret binding 계약으로 재해석합니다. `.examples`의 source·data를 Lumina runtime에 직접 import하거나 배포하지 않습니다.

### 14.1 자원 역할

| 자원 | 역할 |
|---|---|
| Connector | 외부 서비스의 인증된 데이터·작업 API |
| MCP | 표준 Tool·Resource 연결 |
| Skill | 업무 절차, 템플릿, script와 품질 기준 |
| Plugin | Skill·MCP·Provider·UI·설정을 묶는 설치 단위 |

초기 Marketplace 구현 단위는 Skill입니다. MCP는 승인된 definition 설치와 Secret binding부터 지원하고, browser UI·Backend code를 포함하는 Plugin authoring은 Skill과 MCP 흐름을 실제로 운영해 공통 lifecycle이 확인된 뒤 추가합니다. 세 종류를 처음부터 하나의 거대한 form·validator·runtime switch로 구현하지 않습니다.

### 14.2 카탈로그와 설치 분리

```text
Catalog ExtensionVersion
→ exact version installation
→ enabled and authorized scope
→ Session / Run extension snapshot
```

- 카탈로그 공개 범위와 설치 권한은 별개입니다.
- 설치 범위는 user, project, organization입니다.
- Composer의 `$` 검색은 현재 사용자의 활성 WorkingDraft와 현재 Project·사용자에 설치·활성화된 항목만 반환합니다.
- update는 명시적으로 설치 pointer를 새 version으로 바꾸며 자동 update는 기본적으로 끕니다.
- uninstall은 scope 연결만 제거하고 package나 다른 설치를 삭제하지 않습니다.
- Harness 대화에서 만든 Skill WorkingDraft는 기본적으로 생성한 사용자에게 즉시 활성화합니다. catalog publish나 immutable version 저장 전에도 다음 Run에서 실제 Skill로 resolve할 수 있습니다.
- Draft resolver는 `draft_id`, current `draft_revision`과 package digest를 고정합니다. Draft 변경은 이미 실행 중인 Run에 영향을 주지 않고 다음 Run부터 응답에 반영합니다.
- Marketplace의 설치 상태는 단순 badge가 아니라 scope installation의 실제 상태입니다. `미사용`으로 전환하면 해당 사용자 또는 Project installation을 해제하고, 다시 설치할 수 있는 catalog action으로 돌아갑니다.
- 설치 Skill 상세는 `SKILL.md` frontmatter를 metadata로 분리하고 Markdown 본문을 기본 읽기 화면으로 렌더링합니다. raw source는 보조 view이며, catalog→detail→이전 detail 이동은 browser history와 동기화합니다.
- repository builtin Skill의 한국어 설명과 검색 tag 원본은 `extensions/skills/catalog.json` 한 파일의 slug별 `{description, tags}` entry로 관리합니다. 설명·tag를 별도 sidecar로 나누지 않고 repository sync와 Frontend test가 같은 catalog를 읽으며, 모든 builtin entry는 비어 있지 않은 설명과 tag를 가져야 합니다.

### 14.3 불변 version

- Skill은 최소 `SKILL.md`를 가지며 선택적으로 manifest, references, scripts, examples와 assets를 포함합니다.
- 새 Skill은 version 없는 WorkingDraft로 시작하고 대화·편집 변경은 내부 `draft_revision`만 증가시킵니다.
- Published Skill을 수정하는 사용자는 공용 Draft를 공유하지 않고 `(skill_id, owner_user_id)`로 격리된 개인 WorkingDraft를 가집니다. Owner의 Draft와 Contributor의 Draft는 서로 덮어쓰지 않습니다.
- 사용자가 명시적으로 `저장`하면 현재 Draft 전체 package snapshot으로 첫 `v1`을 만들고, 이후 수정한 Draft를 다시 저장할 때 `v2`, `v3`를 만듭니다.
- Draft autosave와 실제 Skill 사용은 `v1`, `v2` 번호를 소비하지 않습니다. 저장된 version은 절대 덮어쓰지 않습니다.
- version이 없는 활성 Draft는 `Draft · rN · 저장 안 됨`과 `v1로 저장` action을 표시합니다. 저장 version을 기반으로 다시 수정 중이면 `Draft · rN · base vN`과 `새 버전으로 저장`을 표시합니다.
- 과거 version에서 분기해도 표시 번호는 최신 번호 다음 값이며 `parent_version_id`로 계보를 기록합니다.
- Draft 수정은 expected revision과 ETag를, version save는 `draft_id`, expected revision, `base_version_id`와 digest를 요구합니다.
- Run은 SkillVersion 또는 WorkingDraft revision, package digest, MCP config revision과 permission grant를 snapshot으로 고정합니다.
- `vPublish.Merge.Feedback`는 사용자에게 진화 상태를 설명하는 계산된 표시값으로 사용합니다. Feedback은 DraftRevision, Merge·Publish·Rollback은 immutable SkillVersion으로 저장하고, 선택·정렬·재현에는 표시 문자열이 아니라 UUID와 digest를 사용합니다.

Fork는 원본과 다른 새 `extension_id`와 Private WorkingDraft를 만들고 `forked_from_extension_id`, `forked_from_version_id`를 기록합니다. Fork도 명시 저장 때 첫 `v1`을 만들며 원본의 이후 변경을 자동 병합하지 않습니다. 적법한 권한으로 만든 Fork의 package snapshot은 원본이 비공개 또는 삭제 상태가 되어도 보존합니다.

삭제는 다음 의미를 구분합니다.

- 사용자 삭제 기본 동작: 자신의 installation 해제
- Draft 삭제: 카탈로그 숨김과 보존 기간이 있는 tombstone
- Published version: 사용·부모·dependency 참조가 있으면 물리 삭제 금지
- 보안 사고: `Revoked`로 신규 Run 즉시 차단, 과거 감사 snapshot 유지
- 보존 기간이 지난 미사용 Draft: background lifecycle에서만 물리 삭제 가능

### 14.4 상태와 역할

```text
WorkingDraft revision N, owner-executable
→ explicit save
→ Private Version vN
→ InReview → Verified / Beta / Published → Deprecated → Revoked
```

Official은 상태가 아니라 publisher trust 표시입니다. 역할은 User, Author, Publisher, Reviewer, Organization Admin과 Operator로 분리할 수 있습니다. 작성자가 자신의 Organization 공개 version을 단독 승인하지 못하게 정책으로 분리할 수 있어야 합니다.

Skill의 `creator_user_id`는 최초 기여 기록으로 고정합니다. 현재 관리 책임은 `SkillOwnership`의 복수 Owner·Maintainer로 분리하고, Owner 추가·제거·이전과 primary Owner 복구는 Audit 대상입니다. Creator가 퇴사하거나 권한을 잃어도 기록은 보존하며 Owner는 사용자·팀·조직 principal로 이전할 수 있습니다.

- 새 Draft와 저장 version의 기본 visibility는 `Private`이며 소유 사용자만 검색·사용·수정합니다.
- `공용으로 공개`는 인터넷 공개가 아니라 Organization 구성원에게 catalog와 설치를 허용하는 의미입니다. 일반 사용자의 공개 요청은 admin 검토를 거쳐 `Published`로 전환합니다.
- `admin@posco.com`은 공용 version을 직접 게시하거나 다른 사용자의 공개 요청을 승인할 수 있습니다.
- `marketplace_permission_mode`는 Organization setting에 `auto | admin_review`로 저장합니다. 개발 profile 기본값은 `auto`, 그 밖의 profile 기본값은 `admin_review`이며 startup/bootstrap에서 복원하고 알 수 없는 값은 안전한 `admin_review`로 fallback합니다. `auto`는 Skill 작성·개인 활성화·공용 게시 permission을 자동 처리하되 모든 action을 audit에 남깁니다.
- Marketplace Auto permission은 Agent Tool의 `approval_mode=on_risk`와 별개입니다. Auto mode에서도 package schema, path, Secret, digest와 compatibility 검사를 생략하지 않습니다.

### 14.5 MCP와 Plugin 보안

- MCP 카탈로그 정의와 사용자 credential binding을 분리합니다.
- Secret 값은 manifest, API response, log와 Run event에 넣지 않습니다.
- arbitrary command·URL 등록과 Organization 공개는 관리자 또는 publisher 검토가 필요합니다.
- Plugin은 dependency, 최소 Lumina version, Backend·Frontend entrypoint와 권한을 선언합니다.
- code가 포함된 Plugin은 static check, signature/digest, compatibility와 sandbox test 후 활성화합니다.
- Revoked version은 신규 Run에서 금지하되 과거 Run 재현 snapshot은 보존합니다.
- 현재 stdio runtime은 shell 문자열이 아니라 argument 배열로 process를 실행하고 repository-relative `cwd`, command allowlist, environment template와 Secret resolver를 검증합니다. literal Secret이 manifest에 있거나 선언한 Tool schema가 runtime `tools/list`와 달라지면 호출 전에 실패합니다.
- streamable HTTP runtime은 session header와 SSE response를 지원하되 exact scheme·host·port, redirect, DNS 결과와 실제 socket address를 검증합니다. loopback·link-local은 금지하고 private range는 관리자가 명시한 범위만 허용하며 request 직전 재해석으로 DNS rebinding을 막습니다.
- 설치 snapshot은 definition revision, configuration digest, Tool allowlist, transport와 Secret binding reference를 고정합니다. runtime 결과·오류에는 Secret 원문, 전체 remote body와 내부 header를 넣지 않습니다.
- 모든 MCP definition은 `extensions/skills/<wrapper>/SKILL.md`의 `source: skill-mcp:<mcp-slug>`와 1:1로 대응해야 합니다. Backend catalog payload는 wrapper 적용 여부와 이름을 반환하고 상세 UI는 `적용 | 누락`을 표시합니다. 누락 상태에서는 Tool 연결 자체를 성공처럼 설명하지 않고 Run Context에 사용 지침이 주입되지 않는다는 경고를 제공합니다.
- 실제 endpoint·Tool schema·운영 책임이 정해지지 않은 placeholder manifest, 성공만 반환하는 stub process와 빈 wrapper 묶음은 builtin MCP로 배포하지 않습니다. 삭제하더라도 DB의 과거 revision·Run snapshot은 감사 원본으로 보존하고 신규 catalog seed와 설치 후보에서만 제외합니다.

### 14.6 Skill Folder 계층

Skill 수가 많아질 때 flat list로만 관리하지 않고 논리적 `SkillFolder` tree를 사용합니다. Folder는 package의 Storage path가 아니며 Skill의 stable ID와 version 계보를 변경하지 않습니다.

```text
SkillFolder
├─ folder_id
├─ scope_type / scope_id
├─ parent_folder_id
├─ name / sort_order
├─ is_system / archived_at
└─ created_by / created_at

SkillFolderPlacement
├─ folder_id
├─ skill_id
├─ scope_type / scope_id
└─ moved_by / moved_at
```

- user, Project, Organization scope마다 독립 tree를 가지며 각 사용자에게 Root와 삭제 불가능한 `미분류` Folder를 제공합니다.
- Folder path는 표시용으로 parent에서 계산하고 raw path를 ID로 사용하지 않습니다. 같은 parent의 정규화된 동명 Folder, cycle과 descendant 아래로의 이동을 차단합니다.
- Skill의 Folder 간 이동은 placement만 transaction으로 변경합니다. Skill ID, 활성 WorkingDraft revision, immutable `vN`, digest, installation, `$` reference와 Run snapshot은 그대로 유지합니다.
- version 없는 WorkingDraft도 stable Skill ID를 가지므로 별도 Draft Folder entry를 만들지 않습니다. 한 Skill은 같은 scope tree에서 한 placement만 가집니다.
- Folder는 정리 metadata이며 하위 Skill에 권한을 상속하거나 부여하지 않습니다. visibility, installation과 Project·Organization policy를 별도로 검사합니다.
- Folder 이동은 subtree parent를 원자적으로 변경합니다. 삭제할 Folder에 item이 있으면 destination을 선택하거나 `미분류`로 이동하며 Skill 자체를 삭제하지 않습니다.
- 공용 Skill은 Organization catalog Folder와 별개로 각 사용자가 자신의 개인 Folder에 배치할 수 있습니다. 한 사용자의 정리가 다른 사용자의 tree를 바꾸지 않습니다.
- 개인 scope에서 Project·Organization scope로 옮기는 것은 Folder 이동이 아니라 `Project에 배치` 또는 `공용 공개 요청`입니다. Backend는 drag-and-drop payload의 scope 변경을 그대로 신뢰하지 않습니다.
- Frontend는 tree 접기, breadcrumb, descendant 검색, item count, drag-and-drop과 `… → 폴더로 이동`을 제공하며 keyboard destination picker도 지원합니다.
- `$` candidate에는 Folder breadcrumb를 보조 정보로 표시하고 Folder filter를 제공하되, 선택 pill과 Run reference의 canonical identity는 Skill stable ID입니다.

### 14.7 작성·검토 흐름

```text
Harness conversation: "이 작업을 Skill로 만들어"
→ Private WorkingDraft 생성·사용자에게 즉시 활성화
→ 대화 수정마다 autosave revision·digest 생성
→ 다음 Run에서 Draft 사용과 응답 변화 확인
→ 명시적 "저장"으로 immutable v1, v2... 생성
→ 선택적 공용 공개 요청
→ admin 또는 Auto permission publish decision
```

Harness가 Skill Draft를 생성·수정한 Turn에는 채팅에 `Skill Draft` 결과 card를 표시합니다. card는 Skill 이름, current draft revision, base version, 실제 적용 여부, 마지막 수정 시각과 `버전으로 저장` action을 가집니다. Draft가 활성화된 동안 Composer 근처에도 compact `Draft 사용 중` indicator를 유지하되 매 요청마다 확인 modal을 띄우지 않습니다.

### 14.8 Skill Merge, Change Request와 Evolution

초기 구현의 명시 저장 `v1`, `v2`, `v3`와 stable UUID·digest가 canonical version입니다. `vPublish.Merge.Feedback`는 Draft revision과 공식 변경 이력을 설명하는 계산된 보조 표시이며 API identity, 정렬 key 또는 Run 재현 key로 사용하지 않습니다.

```text
Published Skill 사용
→ 사용자별 WorkingDraft에서 수정·테스트
→ 변경사항 정리(Merge)와 선택적 Comment
→ Owner면 정책에 따라 직접 Publish
→ Contributor면 Change Request
→ Owner 검토·일부 채택·수정 요청·거절
→ 새 immutable version Publish
→ 문제 발생 시 과거 snapshot을 기반으로 새 rollback version 발행
```

- Creator는 최초 기여 기록으로 고정하고 Owner·Maintainer는 현재 관리 책임으로 이전할 수 있습니다. 일반 변경은 Owner 한 명의 승인으로 처리할 수 있지만 외부 통신, write 권한, 개인정보 접근, 결재·대외 발송과 조직 기본 Skill 변경은 Organization 정책으로 보안 또는 복수 승인을 추가합니다.
- Change Request는 base 공식 version, 제안 version·digest, 구조적 diff, 변경 목적, test·Eval 결과, 비용·시간 변화, Tool·MCP·외부 domain·permission diff와 관련 Run을 고정합니다. 제안 내용이 바뀌면 기존 승인을 무효화합니다.
- 비교는 직전 version, 최신 공식 version, 임의의 두 version과 개인 Draft 대 공식 version을 지원합니다. line diff 외에 package file, 지침, script, reference, dependency, Tool·MCP, 외부 통신과 권한 변화를 별도 표시합니다.
- 동시 수정은 `base_version_id`, expected draft revision과 content digest로 감지합니다. 서로 다른 위치의 변경만 자동 rebase 후 전체 test를 다시 실행하고 같은 지침·파일 충돌은 별도 Draft branch로 보존한 채 사용자 또는 Owner 결정을 요구합니다.
- Rollback은 version 번호를 과거 값으로 되돌리거나 기존 row를 덮어쓰지 않습니다. 선택한 과거 package snapshot을 부모로 하는 새 immutable version과 release note를 발행하고 현재 공식 pointer만 원자적으로 전환합니다.
- Merge·Publish 후보에는 evaluation suite version, pass/fail, 품질, 시간, token·비용, Tool 오류, 사용자 개입과 안전 정책 결과를 연결할 수 있습니다. 실패 Run을 회귀 case로 승격할 때는 개인정보와 Secret을 제거하고 원본 Run 접근 권한을 유지합니다.
- 현재 package snapshot 저장을 먼저 신뢰성 있게 운영합니다. 반복 수정 용량이 실제 병목이 되면 파일 content hash 기반 Blob과 version Tree를 도입하고, diff는 복원의 원본이 아니라 Tree에서 계산하는 review 표현으로 유지합니다. 미참조 Blob은 유예 기간과 감사·Run reference 확인 뒤에만 GC합니다.

### 14.9 승인된 로컬 일반 문서 RAG MCP

Project 대용량 RAG를 Lumina Backend builtin으로 만들지 않는 원칙은 유지합니다. `vector_db`는 사용자가 명시적으로 설치·활성화하는 local MCP와 `vector-db-rag` Skill로 제공하며, 목표 계약은 조직 hierarchy 전용 `explore_org`, `org_unit`, `org_path`를 제거한 일반 문서 검색입니다.

초기 지원 형식은 Markdown, TXT, PDF, DOCX, PPTX, XLSX, CSV와 HTML입니다. extractor는 형식별 자연 위치를 보존한 공통 `ExtractedSection`을 만들고 shared chunker와 local SQLite store가 document, section, chunk, 관계와 결정론적 local embedding을 증분 저장합니다. 변경 파일은 원자 교체하고 삭제 source record는 제거하며 source 문서가 복구 가능한 원본입니다.

| Tool | 계약 |
|---|---|
| `retrieve_context` | 전체 또는 지정 문서를 hybrid 기본 mode로 검색하고 자연 위치가 있는 근거 반환 |
| `explore_document` | 지정 문서의 section tree, 인접·하위 section 탐색 |
| `list_sources` | indexed file, 형식, section·chunk 수, index 시각과 extraction 상태 조회 |
| `store_status` | DB 위치, 지원 형식, 전체 count와 준비 상태 조회 |

검색 결과는 `document_id`, `document_name`, `source_path`, `file_type`, `section_path`, `location_kind`, `location_start/end`, `source_label`, `citation`, `source_chip`, `excerpt`, `score`를 반환합니다. line, page, slide, worksheet row 또는 section처럼 원본 형식의 자연 단위를 citation에 사용하고 DB 내부 ID를 사용자 label로 노출하지 않습니다.

- 문서 directory 밖 path와 traversal을 거부하고 generated DB와 source 문서를 Git에서 제외합니다.
- 추출 text는 지침이 아닌 신뢰할 수 없는 데이터로 취급하며 검색 결과 자체를 실행 권한이나 사실의 진위로 간주하지 않습니다.
- malformed·unsupported file 하나의 실패는 구조화된 per-file 오류로 격리합니다. 암호화·password 보호 문서, legacy binary Office와 image-only PDF OCR은 초기 범위 밖입니다.
- 이 MCP는 별도 upload UI, hosted vector DB, external embedding, background indexer, cross-Project 공유 index와 접근 제어 model을 제공하지 않습니다. Lumina에서 Project file을 연결하려면 별도 authorization·index lifecycle 설계를 먼저 완료합니다.
- 현재 source가 일반 문서 계약으로 전환되기 전에는 기존 조직 문서용 Skill 설명을 Target 기능으로 홍보하지 않습니다. 전환 완료 조건은 8개 형식 fixture, 자연 위치, 문서 filter, hierarchy 탐색, 증분 변경·삭제, malformed 격리와 기존 조직 전용 계약 제거 test 통과입니다.

## 15. Composer의 Context와 명시 호출

Composer 하단의 `$` 호출 버튼 오른쪽에는 `자동 | 채팅 | 파일` 출력 방식 선택기를 둡니다. `자동`이 기본값이며 기존 Agent 판단과 명시된 파일 형식 요청을 따릅니다. `채팅`은 사용자가 메시지에서 파일을 명시하지 않는 한 최종 결과를 채팅 답변으로 반환하고, `파일`은 최종 산출물을 Artifact로 생성하며 채팅에는 짧은 요약과 Artifact 연결만 남깁니다.

대화 본문과 Composer·진행 패널은 `ui.conversation_width` 사용자 설정 하나로 같은 최대 폭을 사용하며 기본값은 `900px`, 유효 범위는 `600px`~`1400px`입니다. 대화 본문·Composer·진행 상태 글꼴은 `ui.conversation_font_size`를 기준으로 기존 상대 크기 차이를 유지한 채 함께 커지며 기본값과 최솟값은 `14px`, 최댓값은 `24px`, 조절 단위는 `1px`입니다. 두 값의 원본은 서버 DB의 사용자 설정이고 로그인·새로고침 시 복원하며, 저장값이 없거나 범위를 벗어나면 각각 `900px`, `14px`로 fallback합니다.

선택값은 `composer.output_mode`로 서버 DB에 저장합니다. 개인 Project에서는 사용자 설정, 공유 Project에서는 Project 공용 설정을 원본으로 사용하고 새로고침·재접속 시 복원합니다. 유효하지 않거나 저장되지 않은 값은 `자동`으로 fallback합니다. 각 요청은 전송 시점의 `auto | chat | file` 값을 message metadata와 Run snapshot에 고정하여 이후 설정 변경이 이미 시작된 Run의 출력 계약을 바꾸지 않게 합니다.

### 15.1 사용자 문법

```text
@보고서.pdf 요약해줘
@매출분석.xlsx 표를 수정해줘
$web-research 최신 자료를 조사해줘
$mcp:internal-search 사내 규정을 찾아줘
```

- `@` 초기 종류: file, artifact
- `$` 종류: skill, MCP
- 이름 충돌 시 `$skill:name`, `$mcp:name`
- token 경계에서만 trigger하여 이메일, 통화 기호와 code를 오인하지 않음
- keyboard 방향키, Enter, Tab, Escape 지원
- 선택 항목은 chip으로 표시하고 stable ID·type의 구조화 payload로 전송

`@` 또는 `$`가 cursor가 위치한 활성 token의 시작이면 Composer 입력란 바로 위에 candidate list를 엽니다. MyHarness처럼 현재 token만 교체하며 문장 중간에서도 사용할 수 있습니다.

```text
ComposerSuggestion
├─ kind: file | artifact | skill | mcp
├─ reference_id
├─ version_or_digest
├─ insert_text
├─ display_name / description
├─ icon / status
└─ project_id / scope

PromptReference
├─ reference_id / kind
├─ version_or_digest
├─ display_snapshot
├─ token_start / token_end
└─ validation_status
```

- `@` candidate는 현재 Project에서 접근 가능한 file과 Artifact를 보여주고, `$` candidate는 현재 사용자·Project에 설치·활성화된 Skill과 MCP를 보여줍니다.
- candidate panel은 Composer보다 위에 떠서 입력 text를 가리지 않으며 최대 높이 이후 내부 scroll을 사용합니다. file·artifact와 Skill·MCP는 icon·type label·설명·상태로 구분합니다.
- query는 대소문자를 구분하지 않고 앞뒤·연속 공백을 정규화합니다. 후보가 많으면 Backend 검색을 debounce하고 최근 결과를 짧게 cache하되 권한 결과의 원본은 Backend입니다.
- `ArrowUp`·`ArrowDown`은 활성 후보를 이동하고 `Enter`·`Tab`은 선택, `Escape`는 닫습니다. mouse click과 touch도 같은 선택 동작을 사용하며 활성 항목은 `role=listbox/option`과 `aria-selected`로 노출합니다.
- 후보를 선택하면 활성 token만 교체하고 뒤에 공백을 추가한 뒤 cursor를 복원합니다. 여러 `@`·`$` reference를 한 Message에 사용할 수 있고 같은 reference의 payload는 중복 제거합니다.
- bare `@`, 이메일, `$6.4`, code block과 존재하지 않는 이름은 reference로 변환하지 않고 일반 text로 둡니다. 결과가 없더라도 사용자가 입력한 text를 삭제하지 않습니다.
- 선택 즉시 Composer의 reference tray에도 제거 가능한 pill을 표시합니다. pill에는 `@ 보고서.pdf`, `$ SkillName`, `$ MCP · server-name`처럼 type과 이름을 함께 보여주며 click하면 file Preview 또는 Skill·MCP 상세를 엽니다.
- Skill candidate와 pill은 저장 version이면 `vN`, WorkingDraft이면 `Draft rN` badge를 반드시 표시합니다. 사용자는 pill 또는 상세에서 `v1로 저장`·`새 버전으로 저장`을 실행할 수 있습니다.

### 15.2 파일·이미지와 긴 붙여넣기

Composer는 `@`로 이미 저장된 파일을 참조하는 흐름과 새 파일을 첨부하는 흐름을 모두 제공합니다.

- 초기 문서 입력은 PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV와 TSV를 지원합니다. 이미지 입력은 PNG, JPEG, WebP와 GIF를 지원하며 실제 허용 범위는 Provider capability가 아니라 Lumina upload policy에서 먼저 검증합니다.
- 파일 선택과 drag-and-drop은 동일한 upload pipeline을 사용합니다. clipboard에 image file이 있으면 text paste보다 우선하여 image attachment로 추가하고, thumbnail·filename·size·preview·remove를 제공합니다.
- 짧은 일반 text paste는 현재 cursor 위치에 그대로 넣습니다. **한 번의 붙여넣기가 12줄 이상이면** Composer 본문에 긴 원문을 펼치지 않고 `붙여넣은 텍스트 #n · 12줄` 형태의 별도 context chip으로 전환합니다.
- 긴 붙여넣기는 paste action 하나당 하나의 `pasted_text` attachment로 원문과 줄바꿈을 그대로 보존합니다. 여러 번 붙여넣으면 여러 chip이 되며, 임의의 의미 단위로 재분할하거나 앞부분만 전송하지 않습니다.
- 긴 text chip은 line count, 짧은 preview, 전체 보기와 remove를 제공하며 전송된 user message에도 attachment가 있었다는 사실과 label을 표시합니다. 12줄 미만으로 편집되더라도 이미 만든 chip을 자동으로 본문에 되돌리지 않습니다.
- upload가 완료되기 전에는 전송을 막거나 `업로드 중` 상태를 명확히 표시합니다. 같은 파일의 중복 첨부는 content hash로 알리고 사용자가 유지할 수 있게 합니다.
- Backend는 원본 binary를 managed Storage에 저장하고 MIME sniffing, 확장자 불일치, 압축 폭탄, 크기·page·pixel limit과 악성 콘텐츠를 검사합니다. client가 보낸 MIME과 경로는 신뢰하지 않습니다.
- 문서 추출 결과에는 page/sheet/slide locator와 extractor version을 저장하여 답변 인용이 원본 위치를 가리킬 수 있게 합니다. scanned PDF에서 text가 추출되지 않으면 빈 문서로 처리하지 않고 OCR 필요 또는 미지원 상태를 알립니다.
- Provider가 native image/document input을 지원하면 adapter가 원본 또는 안전한 변환본을 전송합니다. 지원하지 않으면 승인된 parsing·vision Tool 결과를 사용하거나 실행 전에 명확히 거부하며, image를 text로 처리한 척하지 않습니다.

### 15.3 Backend 검증

- 사용자·조직·Project와 공유 scope로 후보를 필터합니다.
- reference ID를 안전한 Storage key로 해석합니다.
- 파일 크기, 형식, token 예산과 악성 콘텐츠 정책을 적용합니다.
- Skill version, MCP 상태와 Tool permission을 확인합니다.
- 명시 호출은 후보를 Run에 노출한다는 의미이며 즉시 실행을 강제하지 않습니다.
- 권한이 사라진 과거 reference는 metadata만 표시하고 content 재조회는 차단합니다.
- 전송된 text를 다시 정규식으로 해석해 reference를 추측하지 않습니다. `PromptReference`의 stable ID·kind·version을 검증하고 Message text와 별도로 `message_references`에 저장합니다.
- display snapshot은 전송 당시 이름·type·version을 보존하여 이후 rename·uninstall 뒤에도 과거 Message pill을 재현합니다. 현재 접근이 불가능하면 `사용 불가` 상태로 렌더링하고 click·실행은 차단합니다.

### 15.4 동적 Tool 접근

```text
Request and Project policy analysis
→ Relevant extension discovery
→ Load only required tools
→ Freeze in Run snapshot
→ Agent Loop
```

사용하지 않는 Tool schema의 Context·비용 낭비와 prompt cache 손실을 측정합니다.

## 16. Frontend 상세 설계

Frontend는 명료하고 절제된 업무 도구를 지향합니다. 장식, 중첩 card와 의미 없는 motion보다 현재 Run, 선택값, 다음 행동, 데이터 scope와 위험 경계를 먼저 드러냅니다. 빈 상태·오류·중단·재접속도 예외 화면이 아니라 정상 흐름으로 설계하며, keyboard, screen reader label, focus 표시, 충분한 대비와 reduced motion을 기본 계약으로 둡니다.

### 16.1 Web Shell

```text
Lumina Web Shell
├─ Login and user context
├─ Agent selector
├─ Notifications
├─ Common settings and permission errors
└─ Agent Frontend Slot
   ├─ GeneralChatFrontend
   └─ Future installed frontend
```

공통 Frontend SDK는 authenticated API, Session, Run event, approval, Artifact와 typed contract를 제공합니다. 모든 Agent Frontend는 이 SDK를 사용하고 Agent Loop·reconnect를 각자 다시 구현하지 않습니다.

### 16.2 Chat Workspace

```text
Chat Workspace
├─ Session Sidebar
├─ Message and Tool Timeline
├─ Plan Timeline
├─ Composer with @, $, upload, paste and attachment tray
├─ Provider / Model / Effort controls
├─ Context and usage status
└─ Right Artifact Panel
```

- 최종 답변과 실행 과정을 시각적으로 분리합니다.
- 반복 Tool Call은 접되 현재 실행 중인 항목은 자동 노출합니다.
- Terminal은 streaming log, 파일 변경은 diff, 검색은 source list, 이미지는 thumbnail로 렌더링합니다.
- web 근거가 있는 답변은 주장 옆에 ① 형태의 inline source marker를 렌더링하고 hover·focus에 URL과 근거 문장을 표시합니다.
- 답변 하단에는 기본 접힘 상태의 `검색 및 참고 출처`를 두고 검색어 chip, 인용된 출처와 참고만 한 링크를 한곳에서 확인하게 합니다.
- Composer attachment tray는 문서, image와 긴 붙여넣기를 동일한 keyboard 순서로 탐색·preview·remove할 수 있어야 합니다.
- `@`·`$` 입력 중 candidate panel은 Composer 바로 위에 표시하고, 선택한 file·Artifact·Skill·MCP는 Composer reference tray의 pill로 유지합니다.
- 전송된 user Message는 raw `@name`·`$name` 문자열만 보여주지 않고 저장된 `message_references` 위치를 기준으로 별도의 inline pill을 렌더링합니다. 일반 문장은 그대로 두고 reference 구간만 file·artifact·skill·MCP별 pill로 바꿉니다.
- 채팅 pill을 누르면 file·Artifact는 권한 있는 Preview를 열고 Skill·MCP는 사용한 version·상태·설명을 보여줍니다. 과거 reference가 삭제·비활성화·권한 상실 상태이면 이름 pill은 유지하되 `사용 불가` tooltip과 disabled 상태를 표시합니다.
- user Message와 Run detail의 Skill pill은 해당 Run이 실제 사용한 `Draft rN + digest` 또는 immutable `vN`을 표시합니다. 현재 Draft head가 달라져도 과거 Message pill의 revision을 최신 값으로 바꾸지 않습니다.
- 내부 event 이름 대신 사용자 행동 중심의 상태 문구를 사용합니다.
- `App.tsx`는 Web Shell, workspace 선택과 화면 orchestration을 담당하고, 한 Turn의 user Message·업무 계획·Tool activity·model exchange·최종 답변·citation·feedback 렌더링은 `ConversationTurn.tsx` 경계에 둡니다. Turn UI test는 이 component를 직접 대상으로 하며 거대한 inline renderer를 `App.tsx`로 되돌리지 않습니다.
- 실행 중인 Run에 Composer payload가 없으면 primary action은 중단 버튼이고, payload가 있으면 steer 전송입니다. active Run 여부는 terminal status 집합에서 파생하며 별도 `isStopping` canonical state를 만들지 않습니다.

### 16.3 답변 Action Bar

완료된 assistant 답변의 본문과 Artifact 카드 아래에 compact action bar를 둡니다. streaming 중에는 완료 전용 action을 표시하지 않습니다.

- canonical Markdown/text 복사
- 답변별·Session 누적 token과 비용 조회
- 답변을 Project 또는 Session Artifact로 저장
- 답변별 대화 공유 링크 즉시 생성·복사
- 연결된 Artifact 열기
- 검색어·참고 출처 panel 열기
- 좋아요, 싫어요와 문제 신고

usage에는 Provider, Model, Input, Cached Input, Uncached Input, Output과 Total을 표시합니다. 가격표 계산은 `예상 비용`으로 표시하고 가격표 version, 통화와 환율 시각을 추적합니다. 알 수 없는 비용을 0으로 표시하지 않습니다.

첫 assistant 답변에는 비교할 이전 답변이 없으므로 Session 누적 사용량 비교를 숨기고 해당 답변 자체의 usage만 표시합니다. 두 번째 답변부터 Turn 순서로 누적한 Session usage를 함께 보여줍니다. 환율 source·cache 내부 metadata는 사용자 popover에 노출하지 않고 `fresh | stale | unavailable`에 따른 계산 가능 여부만 반영합니다.

답변 피드백은 사용자별·Message별로 저장합니다. 좋아요와 싫어요는 상호 배타적이고 다시 누르면 취소할 수 있으며, 최신 상태가 여러 기기에 동기화되어야 합니다. 싫어요는 선택형 이유와 선택적 설명을 받을 수 있지만 입력을 강제하지 않습니다.

`문제 신고`는 부정확함, 출처 문제, 유해·부적절, 개인정보, UI·도구 오류와 기타 category를 제공하고 재현 설명을 받을 수 있습니다. 제출 전에 포함할 정보 범위를 보여주며, 기본 payload에는 Message ID, Provider·Model, Run·Tool 상태와 client version만 넣습니다. 전체 대화, Tool 원문, attachment, secret과 개인 Memory는 사용자의 별도 동의 없이 신고에 포함하지 않습니다. 신고는 일반 좋아요·싫어요와 별도 상태·운영 workflow를 가집니다.

피드백은 작성자 본인과 권한 있는 운영자만 조회합니다. 공유 Session의 다른 구성원에게 누가 좋아요·싫어요 또는 신고를 남겼는지 노출하지 않고, 모델의 다음 Context에도 자동 삽입하지 않습니다.

### 16.4 선택 문장 Comment와 후속 질문

사용자는 assistant 답변의 문장을 drag로 선택한 뒤 selection toolbar 또는 우클릭 context menu의 `Comment`를 눌러 해당 부분에 후속 질문을 작성할 수 있습니다.

```text
MessageSelectionComment
├─ comment_id / message_id / author_user_id
├─ source_message_version
├─ block_id
├─ start_offset / end_offset
├─ selected_text
├─ prefix_context / suffix_context
├─ instruction
├─ status: draft | submitted | resolved | stale | deleted
└─ created_at / updated_at
```

- selection은 렌더링된 DOM 좌표가 아니라 canonical Markdown의 block ID와 text offset으로 변환해 저장합니다. table·code·citation marker처럼 변환이 어려운 경우 selected text와 앞뒤 context를 함께 저장해 재탐색합니다.
- Comment를 만들면 선택 문장을 highlight하고 Composer에 `답변 인용 · “선택 문장…”` context chip을 추가합니다. 사용자가 질문을 전송하기 전에는 draft이며 취소·수정할 수 있습니다.
- 전송 시 전체 과거 답변을 복제하지 않고 structured `message_reference`로 원본 Message, 선택 구간과 comment instruction을 전달합니다. Backend가 Message 접근 권한과 hash를 다시 검사한 뒤 Agent Context에 필요한 구간만 넣습니다.
- 원본 Message는 immutable이므로 Comment가 답변 내용을 바꾸지 않습니다. 분기·삭제·권한 변경으로 anchor를 복원할 수 없으면 `stale`로 표시하되 선택 원문과 작성한 질문은 보존합니다.
- 겹치는 여러 Comment를 허용하되 highlight가 본문 가독성을 깨뜨리지 않게 표시하고, Comment 목록에서 해당 위치로 이동할 수 있게 합니다.
- mouse 우클릭만을 필수 경로로 삼지 않습니다. keyboard selection, selection toolbar와 screen reader용 `선택 부분에 질문` action을 동등하게 제공합니다.

### 16.5 알림과 상태 진단

- 다른 Session 완료, 실패, 승인 대기와 예약 실행 결과를 알립니다. 향후 hard limit이 도입되면 한도 도달도 같은 durable 알림 계약을 사용합니다.
- 클릭하면 관련 Session, Tool 또는 Artifact로 이동합니다.
- 읽음 상태를 서버에 저장하여 기기 간 동기화합니다.
- 현재 알림 API는 사용자별 목록, unread count, 개별 읽음, 전체 읽음, 개별·전체 삭제를 지원합니다. `idempotency_key`로 같은 Run transition·예약 결과·가입 요청 알림을 한 번만 만들고 deep link는 허용된 target ID만 보존합니다.
- 알림 panel은 개인 실행 알림과 운영 공지를 탭으로 분리하며, receipt row는 title 중심으로 compact하게 표시합니다. 다른 사용자의 알림 count·본문·deep link는 반환하지 않습니다.
- Browser notification은 명시 동의 후 사용합니다.
- P-GPT 문제는 DNS, CA, 인증, endpoint, deployment mapping과 streaming 단계로 구분합니다.
- 관리자 조치가 필요한 문제와 사용자가 해결할 수 있는 문제를 구분합니다.

### 16.6 Command Palette

기능 수가 늘어나는 단계에서 새 채팅, Session 검색, Model 변경, Artifact, Usage, Scheduler와 설정 이동을 keyboard 검색 UI로 제공합니다. 권한 없는 관리자 기능은 검색 결과에 표시하지 않습니다.

### 16.7 Frontend 내구성과 실행 상세 표현

- idempotency·client ID는 공용 `createClientId()`에서 만듭니다. `crypto.randomUUID()`가 없는 browser에서는 `getRandomValues`로 UUID v4 version·variant bit를 설정하고, Web Crypto 자체가 없을 때만 `Math.random` 호환 fallback을 사용합니다.
- Backend 연결 실패 화면은 listener가 다시 열린 한 번의 probe만으로 reload하지 않고 연속 readiness 성공을 확인합니다. 재연결 중 spinner와 오류 상태를 구분하고 무한 reload loop를 만들지 않습니다.
- React render 오류는 `AppErrorBoundary`가 white screen 대신 복구 안내와 reload action을 표시합니다. process health와 render crash를 같은 오류로 취급하지 않습니다.
- Agent 외 부가 workspace는 처음 열 때 lazy load하고, 화면별 server data는 짧은 cache를 사용해 재방문 비용을 줄입니다. 목록형 화면은 사용자가 마지막으로 연 항목을 우선 표시하되 서버의 canonical 정렬·권한을 바꾸지 않습니다.
- 사용자 노출 tooltip·popover·파일 context menu는 `document.body`의 공용 Portal layer에서 렌더링해 clipping·theme 경계를 피합니다. native `title`이나 component별 pseudo-element tooltip을 fallback으로 섞지 않습니다.
- 채팅 content width와 UI·user·assistant·code font size는 서버의 사용자 설정과 `settings_revision`으로 저장하며, UI는 허용 범위 안의 1px 단위 조정만 제공합니다. 전역 token을 거치고 화면별 magic number로 복제하지 않습니다.
- 저장·복사·읽음·Run 시작처럼 결과가 화면에 즉시 드러나는 정상 동작은 성공 toast를 생략합니다. 오류, guard, 부분 실패와 자동 복구는 원인과 다음 행동을 알립니다.
- Clipboard API 실패·미지원 시 안전한 DOM copy fallback을 사용하고 두 경로가 모두 실패하면 성공 toast를 표시하지 않습니다.
- 실행 상세는 사용자 업무 계획, 모델 처리, Tool group과 최종 답변을 분리합니다. 반복 Tool은 group으로 접되 최신 실행 group은 답변 작성이 끝날 때까지 열어 두고, Tool별 duration과 group wall time을 중복 합산하지 않습니다.
- 모델 처리 row는 token 합계만 보여주지 않고 권한 있는 persisted model exchange를 펼쳐 볼 수 있게 합니다. 외부 object·array의 바깥 delimiter만 compact하게 표현하고 내부 content line은 보존합니다.
- Artifact 생성 전체 진행은 근거 없는 가짜 token 상한을 표시하지 않는 indeterminate meter를 사용합니다. 반면 실제 streamed token·line 수가 있는 `write_file` Tool은 filename과 누적 진행을 표시합니다.
- source는 `cited`, `reviewed`, `search-only`를 구분하고 Tool 완료 icon, spinner, duration, chevron은 일관된 column에 배치합니다. 내부 UUID와 중복된 `Artifact ID` 문구는 답변·복사 text에서 숨기되 구조화 Artifact action은 유지합니다.

## 17. Artifact와 전문 산출물

사용자가 파일 유형을 지정하지 않고 보고서 작성을 요청하면 기본 산출물은 독립 실행 가능한 HTML 보고서입니다. DOCX, XLSX, PPTX, PDF, Markdown 등 특정 형식을 명시한 요청은 해당 형식을 우선합니다.

### 17.1 Artifact 모델

```text
Artifact
├─ artifact_id
├─ organization_id / project_id / session_id
├─ display_name / kind / mime_type
├─ visibility
├─ current_version
└─ created_by / created_at

ArtifactVersion
├─ artifact_id / version_number
├─ storage_backend / storage_key
├─ content_hash / size
├─ parent_version / source_version
├─ change_type
├─ change_prompt_summary
├─ renderer_manifest
├─ asset_manifest
├─ validation_status
└─ created_by / created_at
```

- version은 저장 후 내용이 바뀌지 않는 immutable snapshot입니다.
- AI edit 완료, 사용자의 명시 저장과 restore는 모두 새 committed version을 만듭니다.
- typing 또는 autosave 중인 내용은 committed version이 아니라 사용자·Artifact·base version에 연결된 임시 draft로 저장할 수 있습니다. draft는 공유·다운로드·Run 입력의 기본 대상이 아니며, 명시 저장 전에는 version number를 소비하지 않습니다.
- 최신이 `v3`일 때 `v1` 복원 결과는 `v4`입니다.
- 선택한 과거 version 열람은 current version pointer를 바꾸지 않습니다.
- Message 연결은 경로 탐지가 아니라 구조화 `artifact_id`를 사용합니다.

### 17.2 저장과 다운로드 구분

- `저장`: Backend 관리 Storage에 Artifact 생성
- `브라우저 다운로드`: 서버 Artifact 사본을 사용자 PC로 전달
- 사용자 PC 다운로드 파일은 서버 원본이나 동기화 원본이 아닙니다.
- 초기 local storage는 Lumina 실행 장비의 `data/files` 또는 `data/artifacts`를 사용합니다.
- 다중 장비 운영에서는 Object Storage가 canonical content source입니다.

### 17.3 Artifact Library

- 이미지, 문서, code, data file과 link type filter
- 이름, 원본 Session, 생성 사용자, 시각과 크기 표시
- Preview, download와 원본 채팅 이동
- cursor pagination과 권한 범위 검색
- 큰 Tool 결과의 원문 보관과 채팅 요약 연결

### 17.4 우측 패널

- 채팅을 유지한 채 Artifact 열기
- resize, fullscreen, restore, close
- Preview와 canonical Source 전환
- version selector와 metadata
- 수동 편집, AI Assist, 저장·취소·dirty 경고
- Artifact deep link와 다운로드
- Session 전환·재접속 후 상태 복구

열린 Artifact, version, Preview/Source, dirty state와 AI edit Run은 서로 다른 상태입니다. canonical content와 metadata는 Backend가 원본이며 panel width 같은 순수 UI 설정만 Frontend에 둘 수 있습니다.

### 17.5 Renderer

초기 Preview는 HTML, Markdown, text, image와 PDF를 지원하고 DOCX, XLSX와 PPTX를 확장합니다.

| 콘텐츠 | 요구 Renderer |
|---|---|
| HTML | sandbox iframe, CSS·SVG·Canvas와 정책상 허용 script |
| Markdown | GFM heading·table·list·quote·task list·link·image |
| Code | language label, syntax highlight, horizontal scroll, copy |
| Math | KaTeX inline/block, 오류 시 원문 fallback |
| Diagram | Mermaid 주요 diagram, SVG zoom·pan·fit |
| Chart | Apache ECharts 6 계열, responsive Canvas/SVG |
| PDF | page render, link와 글자 깨짐 검증 |

HTML iframe은 app origin의 cookie, token, 상위 window, 다른 Project API와 filesystem에 접근할 수 없어야 합니다. network, navigation, popup, download와 clipboard 권한은 신뢰 수준과 정책에 따라 최소 허용합니다.

현재 HTML Artifact는 JavaScript를 포함할 수 있지만 `allow-same-origin` 없이 격리된 sandbox에서만 실행합니다. 따라서 standalone report의 chart·interaction은 유지하되 Lumina cookie·API·parent DOM에는 접근할 수 없습니다. 공유 viewer도 같은 immutable version과 sandbox 정책을 사용합니다.

ECharts는 `option` object 전체를 JSON으로 받아 bar, line, area, pie/donut, scatter, stacked·combination 외의 ECharts 구성도 renderer에 전달하며 resize/fullscreen에서 다시 계산합니다. 함수·무한 depth·비유한 숫자와 `__proto__`·`prototype`·`constructor` key는 거부하고 legacy `categories + series` payload는 안전한 option으로 변환합니다. 검증한 고정 version의 self-hosted asset 또는 관리 proxy를 기본으로 하고 실패 시 source와 retry를 제공합니다.

Mermaid는 완결된 fence만 parse하고 streaming 중에는 placeholder를 표시합니다. flowchart의 괄호가 있는 unquoted label처럼 안전하게 판별 가능한 문법만 renderer 직전 보정하고, 작성자가 이미 인용했거나 의미가 불명확한 source는 임의 수정하지 않습니다. 큰 diagram은 viewport 기준 자동 fit, 단계식 zoom, pointer pan·drag scroll, scroll boundary 연결, reset과 keyboard close를 제공하며 header 전체를 명확한 확대 affordance로 사용합니다. 오류는 다른 본문을 깨뜨리지 않습니다.

Mermaid와 HTML Artifact의 chart·diagram·data accent는 사용자가 MyHarness에서 지정한 `#3288bd`, `#66c2a5`, `#e6f598`, `#d53e4f`, `#9e0142`, `#f46d43`, `#fdae61`, `#fee08b`, `#abdda4`, `#5e4fa2` palette를 기본으로 사용합니다. 별도 brand palette가 명시된 경우에만 이를 대체하며, 제품 UI의 단일 cobalt accent 규칙을 Artifact 시각화에 강제로 덮어쓰지 않습니다. Mermaid의 authored `classDef`는 보존하고, class가 없는 node와 pie·C4·gitGraph·XY chart 계열에는 이 기본 palette를 renderer가 적용합니다.

같은 content는 중앙 채팅, Artifact Preview, 공유 viewer와 다운로드본에서 의미상 같은 결과여야 합니다. renderer 이름과 version을 metadata에 기록하고 upgrade 전 visual regression을 수행합니다.

### 17.6 편집

수동 편집 draft는 base version 또는 ETag를 기억합니다. 사용자가 `수정사항 반영`을 선택할 때 optimistic concurrency를 검사하고 정확히 하나의 새 committed version을 만듭니다. autosave는 draft만 갱신하며 version history를 오염시키지 않습니다. 충돌 시 조용히 덮어쓰지 않고 비교, 새 version 또는 권한 있는 강제 처리 선택지를 제공합니다. 실패 시 draft를 보존합니다.

Artifact content를 먼저 managed Storage에 쓴 뒤 DB commit 또는 current-version CAS가 실패하면 이번 시도에서 생성한 새 blob만 보상 정리합니다. 이미 존재하던 version, 다른 writer가 채택한 blob과 stale Draft는 삭제하지 않습니다. Attachment·Project File·Agent 생성 Artifact에도 같은 원칙을 적용합니다.

AI Assist는 중앙 Agent Run과 같은 Queue, Provider, 권한과 event replay를 사용합니다. source `artifact_id`, source version, 의견·locator와 목표 형식을 snapshot으로 고정합니다. 원본을 덮어쓰지 않고 새 version을 생성하며 저장과 검증이 완료되기 전 current version을 바꾸지 않습니다.

### 17.7 형식별 생성과 검증

| 형식 | 검증 |
|---|---|
| DOCX | 페이지 render, 잘림, 표·header·font |
| XLSX | formula, reference error, cell format, chart, sheet structure |
| PPTX | overflow, overlap, font, image, editability |
| PDF | page render, link, 글자 깨짐, accessibility |
| HTML | browser render, console error, link, responsive behavior |

가능한 경우 선택 문장, 표 영역, cell range와 slide만 수정하며 비대상 영역 회귀를 검사합니다.

현재 `create_report`는 구조화 report model과 별도로 HTML 전용 `html_source`를 받습니다. 완성된 standalone HTML은 서버 template로 다시 평탄화하지 않고 원문을 보존하며, non-HTML 형식에 `html_source`를 보내면 거부합니다. filename은 확장자 중복과 path 문자를 정규화하고 XLSX에서 formula처럼 보이는 모델 text도 문자열 cell로 저장합니다.

검증 결과는 `validation_status`, `renderVerified`, error·warning과 page metadata로 나눕니다. 구조 검증만 통과하고 renderer가 없으면 완전 통과가 아니라 `structural_passed`와 `render_verification_pending`을 기록합니다. 실제 render에서는 blank page, 비정상 크기, 예상 page count 불일치, process 실패·timeout을 명시적 실패로 처리하고 임시 profile·page image를 정리합니다.

### 17.8 첨부·생성 이미지를 포함한 복합 Artifact

사용자가 첨부한 이미지와 Codex가 생성한 Image Artifact는 HTML·Markdown·DOCX·PPTX·PDF 같은 문서 Artifact의 자산으로 사용할 수 있습니다.

```text
ArtifactAssetRef
├─ asset_ref_id
├─ source_type: attachment | artifact_version | generated_image
├─ source_id / source_version
├─ content_hash / mime_type / dimensions
├─ usage: hero | inline | background | figure | thumbnail
├─ alt_text / caption
└─ packaged_path
```

- Agent는 문서 생성 Run snapshot에 사용할 attachment·image Artifact ID를 명시하고 Backend는 Project·사용자 권한을 다시 검사합니다. prompt에 보이는 filename이나 HTML이 지정한 임의 경로를 신뢰하지 않습니다.
- HTML Preview는 권한이 적용된 Artifact asset endpoint로 URL을 rewrite하고, iframe에는 단기 read URL만 제공합니다. app cookie나 다른 Project asset에 접근할 수 없습니다.
- 독립 HTML·ZIP·DOCX·PPTX·PDF 다운로드는 사용한 image를 package 내부의 결정론적 상대 경로로 복사하거나 형식에 맞게 embed합니다. 서버 전용 URL과 만료 URL을 다운로드본에 남기지 않습니다.
- 원본 attachment를 나중에 삭제하거나 이동해도 이미 committed된 ArtifactVersion은 content hash에 고정된 자산 snapshot으로 재현되어야 합니다. 새 version 생성 시에만 최신 원본을 다시 선택할 수 있습니다.
- 이미지의 crop·resize·압축과 색상 변환은 파생 asset으로 기록하고 원본을 덮어쓰지 않습니다. alt text와 caption은 접근성·문서 검증 대상입니다.
- 첨부 이미지와 생성 이미지를 함께 써서 `그림 + 설명/표/본문`으로 구성한 Artifact를 만들 수 있어야 하며, Preview·공유 viewer·다운로드본에서 자산 누락과 layout 차이를 검증합니다.

## 18. Agent Frontend와 Interactive UI

### 18.1 Agent package

```text
Agent Package
├─ Frontend application
├─ Instructions / Workflow
├─ Plugins
├─ Skills
└─ MCP bindings
```

초기에는 범용 Agent와 `GeneralChatFrontend`만 code registry에 builtin 상수로 등록합니다. `agent_id`, `agent_version`과 frontend contract version은 Conversation·Run snapshot에 저장하되, Agent catalog용 DB·installer·remote loader는 만들지 않습니다. 두 번째 Frontend PoC에서 실제 교체 요구를 검증한 뒤 registry persistence를 추가합니다.

현재 Agent Frontend 모듈화의 목적은 사용자가 임의 코드를 설치하는 Marketplace가 아니라 내부 유지보수입니다. 신뢰된 builtin 모듈만 독립 폴더와 명시적 code registry로 등록하며 runtime 자동 탐색·동적 import·설치 UI는 제공하지 않습니다. 선택 모듈은 Core의 공개 API와 event 계약만 사용하고, registry 등록을 제거한 뒤 해당 폴더를 삭제해도 Core와 기존 Run이 계속 동작해야 합니다. 삭제된 module 또는 호환되지 않는 contract를 참조하는 Conversation은 `general-chat`으로 fallback하되 기존 Agent ID·version과 Artifact는 보존합니다.

#### 18.1.1 내부 유지보수용 모듈 불변 원칙

Agent Frontend 모듈화는 외부 생태계나 무제한 확장을 위한 Plugin architecture가 아니라, 업무별 UI를 Core와 섞지 않고 실험·교체·삭제하기 위한 Modular Monolith 경계입니다.

1. Lumina가 검토하고 함께 build한 builtin 모듈만 실행합니다. 사용자 설치, runtime module 탐색, 임의 JavaScript·Python import를 지원하지 않습니다.
2. 각 선택 모듈은 Frontend, 전용 Backend adapter·업무 로직, Tool·MCP binding과 test를 자기 폴더가 소유합니다. Core 파일 여러 곳에 module ID 조건문을 흩뿌리지 않습니다.
3. Core는 인증·권한, Organization·Project·Session·Run, Queue·event replay, File·Artifact, 승인·감사처럼 제품 전체의 일관성과 복구에 필요한 기능만 소유합니다.
4. 둘 이상의 Frontend에서 실제 재사용이 확인된 기능만 UI와 무관한 Core capability로 승격합니다. 아직 하나의 업무 UI에서만 쓰는 기능을 예상만으로 Core에 일반화하지 않습니다.
5. 모듈은 Core의 공개 API, typed Frontend contract와 canonical event stream만 사용합니다. 다른 선택 모듈의 내부 파일을 직접 import하지 않습니다.
6. 화면 배치·필터·표·차트 같은 표현 책임은 Frontend 모듈에 두고, 권한 검사·영속 저장·감사·재접속 복원처럼 신뢰 경계에 속하는 처리는 Backend가 소유합니다.
7. 특수 Backend 기능은 가능하면 같은 모듈 경계에 두되 Core process에 임의 코드를 자동 import하지 않습니다. 신뢰된 builtin adapter 또는 별도 MCP·service의 명시적 등록만 허용합니다.
8. 새 모듈 도입은 Core 계약 변경을 최소화해야 하며, module 전용 DB column, 공용 event type, 전역 CSS와 `App.tsx` 조건문을 추가하는 방식은 기본 선택으로 사용하지 않습니다.

기능의 위치는 다음 기준으로 결정합니다.

| 질문 | 배치 위치 |
|---|---|
| 모든 UI가 동일하게 신뢰해야 하는 인증·권한·Run·복구 기능인가 | Core Backend |
| 둘 이상의 UI가 재사용하며 화면 표현과 무관한 capability인가 | Core Backend의 공용 capability |
| 특정 업무의 계산·workflow·외부 연동인가 | 해당 Agent module의 Backend·Tool·MCP |
| 데이터의 배치·표현·상호작용인가 | 해당 Agent Frontend module |

#### 18.1.2 제거 가능성 기준

선택 모듈은 추가하기 쉬운 것보다 제거하기 쉬운 것을 우선합니다. 모듈 제거 완료 조건은 다음과 같습니다.

1. Backend와 Frontend의 명시적 registry 등록을 제거합니다.
2. 해당 모듈 폴더를 삭제합니다.
3. Core에서 삭제된 module ID, import, route 분기, CSS selector와 전용 type 참조가 남지 않습니다.
4. 해당 모듈 없이 Backend test, Frontend test, typecheck와 build가 통과합니다.
5. 삭제된 모듈을 참조하는 기존 Conversation은 `general-chat`으로 열리고 진행 중이거나 과거인 Run·Artifact는 보존됩니다.
6. 모듈 전용 영속 데이터가 있다면 코드 제거와 데이터 폐기를 분리합니다. 즉시 table을 drop하지 않고 보존·export·정리 migration 정책을 명시합니다.

이 조건을 만족하지 못하고 Core 여러 곳을 함께 수정해야만 제거할 수 있는 기능은 독립 모듈로 간주하지 않습니다.

### 18.2 Frontend type

```text
builtin  → Lumina와 함께 build
package  → 설치 Agent package의 module
remote   → 공통 Backend 계약을 쓰는 독립 app
sandbox  → 신뢰하지 않는 iframe app
```

초기 범위는 builtin입니다. package, remote와 sandbox는 현재 구현 대상이 아니라 장기 contract 유형이며 이를 위한 loader·설정 UI·추상 base class를 미리 만들지 않습니다. 두 번째 Frontend PoC 이후에도 필요한 최소 공통 contract만 추출하고, 모르는 module이나 호환되지 않는 contract는 안전한 범용 화면으로 fallback합니다.

### 18.3 공통 Backend 계약

- authentication and user context
- Agent registry and manifest
- Session, Conversation and Message
- Run start, queue, cancel, pause and resume
- attachment and Artifact
- approval and rejection
- Provider and execution options
- extension availability
- canonical event stream

Frontend 전환은 진행 중 Run의 Provider, Agent snapshot 또는 permission을 바꾸지 않습니다.

### 18.4 선언형 UI와 MCP Apps

- 제품 핵심 화면은 검증된 Component Registry와 제한된 schema를 사용합니다.
- Agent가 전체 제품 UI code를 자유 생성하지 않습니다.
- 외부 전문 UI는 MCP Apps sandbox 경로를 사용합니다.
- typed UI action은 Backend에서 schema와 권한을 재검증합니다.
- Live HTML Artifact와 제품 UI Profile은 서로 다른 trust boundary를 가집니다.

## 19. Connector, Browser와 Computer Use

Lumina core에는 Gmail·Calendar·Drive·Slack용 제품 기능을 넣지 않습니다. 이 장의 Connector는 회사에서 명시적으로 승인한 내부 시스템과 향후 조직별 확장을 뜻하며, 설치되지 않은 Connector를 UI에 기본 기능처럼 노출하지 않습니다.

연결 우선순위는 다음과 같습니다.

```text
Dedicated Connector / API
→ MCP Tool
→ Browser DOM automation
→ screen-based Computer Use
```

- 사용 중인 app·site와 현재 행동을 단계별로 표시합니다.
- 기본 `on_risk`에서는 Run snapshot과 조직 정책이 허용한 조회는 즉시 수행하지만 로그인 상태를 이용한 외부 전송·게시·삭제는 실행 전 승인을 받습니다.
- 결과는 DOM, screenshot, downloaded file 또는 API response로 검증합니다.
- 무한 재시도하지 않고 현재 상태와 필요한 사용자 행동을 안내합니다.
- 사용자가 제어권을 가져오고 다시 Agent에 넘길 수 있게 합니다.
- domain·app allowlist, credential redaction, 외부 전송 정책과 민감 screenshot 보존 정책을 적용합니다.

## 20. 예약 작업

### 20.1 Task와 Run 분리

```text
ScheduleDefinition
├─ schedule
├─ project_id
├─ context_mode: continue_session | new_session_per_run
├─ source_session_id
├─ Provider / Model / Effort
├─ extension snapshot policy: pinned | latest_allowed
├─ execution environment policy
├─ connector binding IDs
├─ target_artifact_id
├─ artifact update mode
├─ approval policy
└─ delivery policy

ScheduledRun
├─ immutable input snapshot
├─ status / attempts
├─ outputs / artifacts
├─ usage / cost
├─ error / approval
└─ timestamps
```

- 시간별, 일별, 주별, 평일과 수동 실행
- 다음 실행, 최근 실행, 상태, pause·resume·수정·즉시 실행
- 중복 실행 방지, retry와 timeout
- 서버 Worker 실행을 기본으로 하여 사용자 PC가 꺼져도 지속
- Local Bridge 의존 시 device offline을 대기 또는 명확한 실패로 처리
- 같은 보고서 갱신은 파일명 추측이 아니라 stable `artifact_id`에 새 version 추가
- `latest_allowed`는 실행 직전 권한·호환성을 검사하고 실제 version을 Run snapshot에 저장
- 예약 작업 삭제는 row 물리 삭제가 아니라 `enabled=false`, `next_run_at=null`, `archived_at`을 원자적으로 기록하는 보관 처리입니다. 이후 목록·due claim에서 제외하되 과거 `ScheduledRun`, Artifact와 audit reference는 보존합니다.
- UI는 별도 modal·browser confirm 없이 같은 삭제 버튼의 첫 click에 `한 번 더 눌러 삭제` 상태를 표시하고 같은 대상의 두 번째 click에만 `DELETE`를 호출합니다. Project나 선택 대상이 바뀌면 확인 상태를 해제하며 삭제 중·실패·재시도 상태도 버튼 위치에서 보여줍니다.
- Scheduler tick은 `(scheduled_task_id, scheduled_for)` idempotency와 DB claim으로 중복 dispatch를 막습니다. 동시 tick이 같은 due slot을 읽었더라도 uniqueness 경합에서 진 쪽은 transaction을 복구하고 이미 생성된 ScheduledRun을 반환하며, timeout·실패는 `max_attempts` 안에서 retry하고 worker restart로 interrupted된 예약 Run도 저장된 attempt·snapshot에서 한 번만 재개합니다.
- `pinned`은 Task 생성 시 Skill snapshot을 고정하고 `latest_allowed`는 실행 직전에 다시 resolve하되 실제 사용 digest를 ScheduledRun과 Run prompt hash에 기록합니다. terminal Run의 Artifact·usage·오류를 ScheduledRun에 동기화한 뒤 사용자별 in-app 결과 알림을 생성합니다.

## 21. 데이터 모델 통합 초안

아래 목록은 제품의 논리 객체와 초기 물리 table을 구분합니다. 문서에 객체가 등장한다는 이유만으로 table을 하나씩 만들지 않습니다.

### 21.1 초기 핵심 table (`0001_initial_core`)

```text
organizations                 # 초기에는 seeded default organization 1개
users                        # 초기에는 organization_id 직접 보유
auth_sessions
projects
project_memberships
conversations                 # UI의 Session, 별도 sessions table 없음
messages
runs
run_commands                  # steer, cancel, pause 등 idempotent command
run_events                    # durable event와 coalesced text chunk
queued_messages
tool_executions               # call 입력과 1:1 result를 한 record에 저장
attachments
artifacts
artifact_versions
artifact_drafts               # autosave, committed version과 분리
conversation_share_grants
user_settings
project_settings
provider_models                # versioned Model Catalog와 runtime ID mapping
audit_events
```

`organization_memberships`는 둘 이상의 Organization 또는 organization role이 실제로 필요해질 때 추가합니다. 초기 single-company 배포에서는 User가 seeded Organization에 속한다고 간주하고 Project membership만 명시적으로 관리할 수 있습니다.

`projects`는 `owner_user_id`, `project_type=personal | shared | system`, concept·instruction version과 `is_default`를 가집니다. `(owner_user_id, is_default=true)`는 사용자마다 하나만 허용하고, 사용자 생성과 Default Project 생성을 같은 transaction 또는 idempotent bootstrap으로 처리합니다.

`message_feedback`는 `kind=rating | report`로 통합하되 rating은 `(user_id, message_id)`당 하나만 활성화하고 `value=like | dislike`를 upsert합니다. report는 category, 설명, 사용자가 동의한 diagnostic scope, 운영 status와 처리 이력을 가지며 rating 취소와 독립적으로 보존합니다.
사용자는 답변 action bar에서 인라인 form으로 report 의견을 게시합니다. 관리 화면의 대화 탭은 feedback 개수를 표시하고 `의견 있는 대화만` 필터를 제공하며, 상세 화면에서 작성자·분류·내용·게시 시각을 읽기 전용으로 보여줍니다.

`message_references`는 Message와 `file | artifact | skill | mcp` reference를 연결하고 stable target ID, exact version·digest, token range, display snapshot과 validation status를 저장합니다. Message를 다시 표시할 때 현재 catalog 이름으로 문자열을 재탐지하지 않고 이 record로 pill을 렌더링합니다.

`user_memories`는 정규화된 사실과 사용자에게 보여 줄 문구, source reference, confidence, status와 만료를 저장합니다. 원문 대화 전체를 복제하지 않고 source Message ID를 참조하며, 사용자 삭제 요청 시 retrieval index와 cache에서도 제거합니다.

`provider_models`는 Provider별 표시명과 실제 `runtime_model_id`, capability, 활성·기본 상태, source와 catalog revision을 저장합니다. `(provider_id, model_key)`는 unique이며 Provider별 `is_default=true`는 활성 항목 하나만 허용합니다. 초기 seed는 12.3의 목록을 idempotent하게 등록하되 관리자가 바꾼 활성 상태·deployment mapping을 startup마다 덮어쓰지 않습니다.

초기 구현에서 검색 기능만을 위해 `sources`, `citations`, `search_queries` table을 각각 만들지 않습니다. `tool_executions.result_json`에 `SearchInvocation`과 `SourceEvidence`를 저장하고 final `messages.metadata_json`에 `MessageCitation`과 source 순서를 저장합니다. 동일 source를 여러 Message·Artifact에서 조회하거나 조직 단위 출처 분석이 실제로 필요해질 때 정규화 table로 승격합니다.

`attachments`는 `kind=file | image | pasted_text`, owner scope, original filename, sniffed MIME, size, line/page/pixel count, content hash, Storage key, extraction status·version, locator map과 생성 경로 `upload | drag_drop | clipboard | paste`를 가집니다. 긴 붙여넣기 원문도 message body에 합쳐 숨기지 않고 접근 통제가 적용되는 attachment content로 저장합니다.

초기 `ArtifactAssetRef`는 `artifact_versions.asset_manifest` JSON에 저장합니다. asset 단위 검색·재사용·license 추적 요구가 실제로 생길 때 별도 table로 승격합니다.

### 21.2 현재 구현된 확장 table과 schema (`0002`~`0030`)

```text
skill_folders / skill_folder_placements            논리 Folder tree와 안정된 Skill 배치
extensions / extension_versions                    immutable Marketplace version
extension_drafts / extension_draft_revisions       사용자별 executable WorkingDraft revision
extension_installations / extension_draft_bindings scope별 설치와 Draft activation
skill_ownerships                                   Creator와 분리된 Owner·Maintainer
scheduled_tasks / scheduled_runs                    예약 정의, attempt와 실행 snapshot
user_memories                                      자동 학습하는 개인 장기 Memory
message_feedback                                   rating·report, user별 상태
message_references                                 file·artifact·skill·mcp stable reference
message_selection_comments                         선택 문장 anchor와 후속 질문
plans / plan_steps / plan_subtasks                  Run의 구조화 Plan
compacted_context_entries                           Context 압축 lineage
mcp_definitions / mcp_configuration_revisions       MCP catalog와 immutable 설정 revision
mcp_installations / mcp_secret_bindings             scope 설치와 Secret reference binding
project_files / project_file_versions               Project Workspace 파일 version
project_learning_proposals / project_memories       검토 가능한 Project 학습
notifications                                      persistent inbox와 read state
tool_approvals                                     one-shot Tool approval 결정
organizations.run_safety_settings_json             조직별 Run 안전 한도 설정
runtime_prompt_overrides                           조직별 고정 prompt override revision·digest
project_folders                                    Project 내부 논리 folder와 tombstone
help_items                                         계층형 Help Markdown과 revision
announcements                                      조직 공지와 작성자·수정 시각
organizations.initial_execution_settings_json      조직별 최초 실행 설정
users.settings_revision / projects.settings_revision 사용자·공유 설정의 atomic revision
provider_models.capabilities_json.max_input_tokens Model별 실측 입력 상한
```

현재 migration head는 `0030_pgpt_input_token_limits`입니다. `0009`, `0013`~`0018`, `0020`~`0030`은 기존 table과 seed data에 MCP runtime header, instruction hierarchy·revision, 공개 share link, 사용자 소속, 알림 compact metadata, Skill 개인 Draft·소유권, 대화 좋아요, Codex OAuth catalog·표시 순서, 조직별 Run 안전 설정·내부 prompt override·최초 실행 설정, Project Folder, Help Center, 공지, 설정 revision과 P-GPT 실측 입력 상한을 증분 추가합니다. `0026`, `0030`처럼 catalog row를 갱신하는 data migration도 schema migration과 같은 Alembic chain에서 재현합니다.

### 21.3 후속 기능에서 추가할 table

```text
extension_permission_grants / reviews                세분화된 Marketplace permission·review
skill_change_requests / skill_version_test_results   Merge·기여·Eval workflow
skill_blobs / skill_version_trees                     package CAS가 실제 병목일 때
permission_leases                                    reusable approval
execution_environments                               persistent or user-managed runtime
batch_items                                          Batch Fan-out
agent_registry                                       second replaceable Frontend 이후
```

위 후속 기능을 구현하기 전에는 빈 table, generic JSON entity와 사용되지 않는 service를 미리 만들지 않습니다. 반대로 Run snapshot에 필요한 Provider, Agent, extension과 environment metadata는 해당 table이 없더라도 versioned JSON snapshot으로 보존합니다.

`tool_executions`는 Tool Call ID, 이름, validated input, status, result summary 또는 error, Artifact reference, started/finished timestamp를 함께 가집니다. 모델 대화에 필요한 Tool Result Message는 이 record를 참조해 생성합니다. 동일 Call에 Result가 둘 생길 수 있는 별도 insert 흐름을 만들지 않습니다.

Provider usage record에는 raw provider usage와 함께 normalized input, cached input, cache write, uncached input, output, prefix hash, Context lineage와 cache invalidation reason을 저장합니다. 초기에는 Run 또는 Message metadata로 시작하고 비용·운영 query가 복잡해질 때 usage table로 분리합니다.

### 21.4 공통 저장 규칙

- 주요 ID는 UUID입니다.
- 시간은 UTC로 저장하고 UI에서 locale로 변환합니다.
- SQLite와 PostgreSQL 양쪽에서 동작하도록 SQLAlchemy와 Alembic을 사용합니다.
- SQLite 전용 SQL 의존을 최소화합니다.
- Repository와 Service는 모든 table에 의무적으로 만들지 않습니다. 여러 aggregate를 묶는 transaction, 복잡한 authorization query, Storage·Provider 같은 교체 경계에만 둡니다.
- content body와 binary는 Storage에, DB에는 opaque key, hash, size와 metadata를 저장합니다.
- secret 값은 Secret Store reference로만 연결합니다.
- soft delete, tombstone과 보존 기간을 사용하고 audit·Run 재현 데이터를 무조건 hard delete하지 않습니다.
- 여러 기기·worker가 수정할 수 있는 aggregate는 `expectedRevision` 또는 `If-Match`로 compare-and-swap합니다. stale·invalid revision은 `409` 또는 명시적 validation code로 반환하고 최신 값을 조용히 덮어쓰지 않습니다.
- PATCH body는 omitted와 explicit `null`을 구분합니다. 필수 값을 `null`로 지우는 요청과 변경 field가 하나도 없는 no-op 요청은 transaction 전에 거부합니다.
- Storage write와 DB transaction이 함께 필요한 작업은 생성한 key의 소유권을 추적합니다. commit·CAS 실패 시 이번 작업이 새로 만든 unreferenced key만 정리하고 기존 canonical content는 보존합니다.

## 22. API 경계 초안

실제 route naming은 구현 convention에 맞추되 다음 의미를 보존합니다.

### 22.1 인증·사용자

```text
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/session
GET    /api/admin/users
POST   /api/admin/users
PATCH  /api/admin/users/{id}
GET    /api/admin/conversations
GET    /api/admin/conversations/{id}
GET    /api/admin/conversations/{id}/turn-sets
GET    /api/projects
POST   /api/projects
PATCH  /api/projects/{id}
DELETE /api/projects/{id}
GET    /api/memories
POST   /api/memories
POST   /api/memories/optimize
PATCH  /api/memories/{id}
DELETE /api/memories/{id}
GET    /api/memory-settings
PATCH  /api/memory-settings
```

### 22.2 Provider·Model

```text
GET    /api/providers
GET    /api/providers/{id}/models
POST   /api/admin/providers/{id}/models/discover
POST   /api/admin/providers/{id}/models
PATCH  /api/admin/providers/{id}/models/{model_key}
```

일반 조회는 현재 사용자·조직·Project 정책까지 적용한 `enabled` 목록과 Model별 capability를 반환합니다. 관리자 discovery는 외부 응답을 즉시 활성화하지 않고 후보와 기존 catalog의 diff만 반환합니다. 생성·수정은 runtime ID 중복, Provider별 기본값 유일성, capability schema와 관리 권한을 검증하며 모든 변경을 audit와 새 catalog revision에 남깁니다.

### 22.3 Conversation(Session)·Run

```text
GET    /api/conversations?cursor=&limit=
GET    /api/conversations/search?title_query=&cursor=&limit=
GET    /api/conversations/{id}/turn-sets?before_cursor=&limit_turn_sets=
GET    /api/composer/suggestions?project_id=&trigger=&query=&cursor=
POST   /api/conversations
PATCH  /api/conversations/{id}
POST   /api/conversations/{id}/move
DELETE /api/conversations/{id}
POST   /api/conversations/{id}/attachments
GET    /api/attachments/{id}
DELETE /api/attachments/{id}
POST   /api/conversations/{id}/runs
POST   /api/runs/{id}/actions
GET    /api/runs/{id}/snapshot
GET    /stream/runs/{id}?after_sequence=
PUT    /api/messages/{id}/rating
DELETE /api/messages/{id}/rating
POST   /api/messages/{id}/reports
GET    /api/messages/{id}/comments
POST   /api/messages/{id}/comments
PATCH  /api/message-comments/{id}
DELETE /api/message-comments/{id}
```

Run action body는 `steer`, `queue_next`, `submit_user_input`, `pause`, `resume`, `cancel`, `retry_step`, `approve`, `reject`를 idempotency key와 함께 표현합니다. `submit_user_input`은 pending input request ID와 질문별 answer를 요구하고 Run이 `awaiting_input`일 때만 적용합니다.

Attachment upload response는 안정된 `attachment_id`, 검사·추출 상태와 preview metadata만 반환합니다. Run 생성 body는 `attachment_ids[]`와 `message_reference_ids[]`를 전달하며 Backend가 Conversation·Project ownership, scan 완료와 현재 권한을 다시 검사합니다. clipboard image와 긴 `pasted_text`도 동일한 attachment 계약을 사용합니다.

Conversation move body는 destination `project_id`, 포함할 Session-owned Artifact 정책과 idempotency key를 받습니다. Backend는 source·destination 권한, 실행 중 Run과 공유 범위 상승을 검사하며 성공 response에 이동하지 못한 reference와 사유를 함께 반환합니다.

Message comment 생성 body는 client DOM Range가 아니라 canonical `block_id`, offsets, selected text, prefix·suffix와 instruction을 전달합니다. Backend는 저장된 Message version에서 anchor를 검증하고 일치하지 않으면 `stale` 또는 보정된 anchor를 반환합니다.

Composer suggestion API는 `trigger=@ | $`에 따라 file·Artifact 또는 Skill·MCP 후보를 반환하고 사용자·Project·설치 상태·공유 scope를 먼저 적용합니다. Run 생성 body는 표시 text와 별도로 `prompt_references[]`를 보내며 Backend는 exact target과 version을 다시 검증합니다.

### 22.4 Artifact·공유

```text
GET    /api/artifacts
GET    /api/artifacts/{id}
GET    /api/artifacts/{id}/versions/{version}
POST   /api/artifacts/{id}/versions
GET    /api/artifacts/{id}/download?version=
POST   /api/conversation-shares
GET    /api/conversation-shares
GET    /api/conversation-shares/{token}
DELETE /api/conversation-shares/{id}
```

독립적인 `POST /api/artifacts/{id}/ai-edits` route는 현재 구현하지 않았습니다. AI의 Artifact 생성·수정은 Run의 Workspace Tool과 Draft/version service를 거쳐 provenance와 optimistic concurrency를 보존합니다.

### 22.5 Extension

```text
GET    /api/extensions
GET    /api/extensions/{id}
POST   /api/extensions
PATCH  /api/extensions/{id}
POST   /api/extensions/{id}/draft
PATCH  /api/skill-drafts/{id}
POST   /api/skill-drafts/{id}/activate
POST   /api/skill-drafts/{id}/save-version
GET    /api/extension-versions/{id}
POST   /api/extension-versions/{id}/publish
GET    /api/extension-installations
POST   /api/extension-installations
PATCH  /api/extension-installations/{id}
DELETE /api/extension-installations/{id}
GET    /api/skill-folders?scope_type=&scope_id=
POST   /api/skill-folders
PATCH  /api/skill-folders/{id}
POST   /api/skill-folders/{id}/move
DELETE /api/skill-folders/{id}
POST   /api/skills/{id}/move-folder
POST   /api/skills/{id}/ownerships
DELETE /api/skills/{id}/ownerships/{ownership_id}
```

대화 중 `create_skill`·`update_skill` Workspace Tool은 위와 같은 Draft service를 직접 사용하고 다음 Run에 활성 revision을 적용합니다. 별도 `/skill-drafts/from-conversation` HTTP route를 현재 구현으로 가정하지 않습니다.

다음 endpoint는 Skill Evolution 단계의 Target입니다.

```text
POST   /api/extensions/{id}/forks
POST   /api/extension-versions/{id}/review-requests
POST   /api/extension-versions/{id}/public-requests
GET    /api/skills/{id}/compare?from=&to=
POST   /api/skills/{id}/change-requests
PATCH  /api/skill-change-requests/{id}
POST   /api/skill-change-requests/{id}/publish
POST   /api/skills/{id}/rollbacks
```

모든 endpoint는 authentication, ownership, scope, current version과 content range를 다시 검사합니다.

### 22.6 예약 작업

```text
GET    /api/scheduled-tasks?project_id=
POST   /api/scheduled-tasks
GET    /api/scheduled-tasks/{id}
PATCH  /api/scheduled-tasks/{id}
DELETE /api/scheduled-tasks/{id}
POST   /api/scheduled-tasks/{id}/enable
POST   /api/scheduled-tasks/{id}/disable
POST   /api/scheduled-tasks/{id}/run-now
GET    /api/scheduled-tasks/{id}/runs
```

삭제 endpoint는 Project write 권한과 CSRF를 검사한 뒤 Task를 archive하고 `204`를 반환합니다. 이미 archive된 ID는 존재 여부를 과도하게 노출하지 않는 `scheduled_task_not_found`로 처리하며 audit에는 `scheduled_task_archived`를 기록합니다.

### 22.7 현재 구현된 보완 API

앞 절의 핵심 경계 외에도 현재 Frontend와 관리 화면이 사용하는 구현 endpoint는 다음과 같습니다.

```text
# 관리자·운영
GET    /api/admin/usage-statistics
GET    /api/admin/users/{id}
POST   /api/admin/users/{id}/reset-password
GET    /api/admin/audit-events
GET    /api/admin/conversation-shares
DELETE /api/admin/conversation-shares/{id}
GET    /api/admin/run-safety
PATCH  /api/admin/run-safety
POST   /api/admin/run-safety/emergency-stop

# Project membership·지침·파일
GET    /api/projects/{project_id}/memberships
POST   /api/projects/{project_id}/memberships
PATCH  /api/projects/{project_id}/memberships/{membership_id}
DELETE /api/projects/{project_id}/memberships/{membership_id}
GET    /api/instructions/personal
PATCH  /api/instructions/personal
GET    /api/projects/{project_id}/instructions
PATCH  /api/projects/{project_id}/instructions
GET    /api/admin/organization/instructions
PATCH  /api/admin/organization/instructions
GET    /api/admin/runtime-prompts
PATCH  /api/admin/runtime-prompts/{prompt_key}
GET    /api/admin/organization/instructions/revisions/{revision}
PATCH  /api/admin/organization/instructions/revisions/{revision}
PATCH  /api/admin/organization/instructions/revisions/{revision}/label
GET    /api/projects/{project_id}/files
POST   /api/projects/{project_id}/files
GET    /api/projects/{project_id}/files/{file_id}
PATCH  /api/projects/{project_id}/files/{file_id}
POST   /api/projects/{project_id}/files/{file_id}/versions
GET    /api/projects/{project_id}/files/{file_id}/download
DELETE /api/projects/{project_id}/files/{file_id}

# Project Memory와 learning proposal
GET    /api/projects/{project_id}/memories
GET    /api/projects/{project_id}/memories/{memory_key}
GET    /api/projects/{project_id}/learning-proposals
POST   /api/projects/{project_id}/learning-proposals
GET    /api/projects/{project_id}/learning-proposals/{proposal_id}
POST   /api/projects/{project_id}/learning-proposals/{proposal_id}/approve
POST   /api/projects/{project_id}/learning-proposals/{proposal_id}/reject
POST   /api/projects/{project_id}/learning-proposals/{proposal_id}/apply
POST   /api/projects/{project_id}/learning-proposals/{proposal_id}/rollback

# Conversation·Run 보완
GET    /api/conversations/content-search
POST   /api/conversations/{id}/branch
GET    /api/conversations/{id}/export?format=json|markdown
GET    /api/runs/{id}/plan
GET    /api/messages/{id}/references
GET    /api/messages/{id}/feedback
GET    /api/settings/current
PATCH  /api/settings/current

# Attachment·Artifact Draft와 Preview
GET    /api/attachments/{id}/content
POST   /api/artifacts/{id}/restore
GET    /api/artifacts/{id}/draft
PUT    /api/artifacts/{id}/draft
GET    /api/artifacts/{id}/preview

# MCP catalog·설치·Secret binding
GET    /api/admin/mcp-definitions
POST   /api/admin/mcp-definitions
POST   /api/admin/mcp-definitions/{id}/revisions
POST   /api/admin/mcp-definitions/{id}/approve
PATCH  /api/admin/mcp-definitions/{id}/status
GET    /api/mcp/catalog
GET    /api/mcp/installations
POST   /api/mcp/installations
PATCH  /api/mcp/installations/{id}
DELETE /api/mcp/installations/{id}
PUT    /api/mcp/installations/{id}/secrets/{secret_name}
DELETE /api/mcp/installations/{id}/secrets/{secret_name}

# 알림·환율
GET    /api/notifications
GET    /api/notifications/unread-count
POST   /api/notifications/{id}/read
POST   /api/notifications/read-all
DELETE /api/notifications/{id}
DELETE /api/notifications
GET    /api/finance/exchange-rate/usd-krw
```

Artifact Draft `PUT`은 ETag·base version을 검사하고 stale write를 `409`로 거부합니다. MCP Secret endpoint는 Secret 원문이 아니라 허용된 reference만 저장합니다. 환율 endpoint는 `fresh`, `stale`, `unavailable` 상태를 반환합니다. 외부 source 갱신이 실패하면 마지막 정상 환율을 `stale`로 유지하고, 정상 환율이 없을 때만 `null`과 `unavailable`을 반환합니다. 실패 후 재시도는 짧은 cache TTL로 제한하여 원화 예상비용 UI가 stale·unknown을 구분하면서 외부 장애를 요청 폭증으로 확대하지 않게 합니다.

Conversation PATCH는 `If-Match` 또는 body의 `expectedRevision`, 사용자·Project 설정 PATCH는 response의 `revision`을 다음 요청의 `expectedRevision`으로 사용합니다. Help·Skill Draft·Artifact도 자기 aggregate의 revision 또는 ETag를 사용하며 서로 다른 종류의 revision을 교차 사용하지 않습니다. Agent Frontend가 포함된 Conversation·Run response는 원래 `id`, `version`과 해석된 `frontendModule`, `frontendContract`, `fallback`을 반환하여 Frontend Host가 server와 같은 fallback 결정을 재현하게 합니다.

## 23. DB와 Storage 전략

### 23.1 개발

```text
SQLite: data/database/lumina.db
Managed files: data/files or data/artifacts
API process with local executor
```

- SQLite WAL, 짧은 transaction과 write conflict retry를 사용합니다.
- 장시간 Run 동안 DB transaction을 유지하지 않습니다.
- Run record와 command를 먼저 commit한 뒤 local executor가 claim합니다. 현재 단일 executor는 graceful shutdown 때 실행 중 Run을 `interrupted`로 기록하고 시작 시 Queue·모델 Turn을 복구합니다. 완료 여부를 모르는 외부 Tool은 자동 재실행하지 않고, approval 대기 Run은 대기 상태로 복원합니다. multi-worker lease·heartbeat·execution epoch는 아직 구현하지 않은 운영 확장입니다.
- backup은 정상 종료 또는 SQLite backup API를 사용하고 실행 중 `.db` 하나만 복사하지 않습니다.

### 23.2 운영

```text
PostgreSQL  → canonical structured state
Redis       → queue and distributed coordination
S3 / MinIO  → canonical binary and artifact content
Secret Store→ credentials and keys
```

- Backend와 Worker가 여러 장비일 때 로컬 disk를 canonical Artifact 원본으로 사용하지 않습니다.
- local storage에서 object storage로 이전할 때 content hash 검증 후 pointer를 원자적으로 전환합니다.
- ownership과 Project scope는 migration 중에도 유지합니다.

## 24. 보안 설계 요약

### 24.1 필수 통제

- 모든 resource에 owner, organization, Project와 visibility metadata
- server-side authorization과 field filtering
- CSRF, secure cookie와 safe return URL
- path canonicalization, symlink와 traversal 차단
- SSRF, redirect hop, DNS와 IP 검증
- sandbox HTML·Plugin·Computer Use
- Secret redaction과 structured audit
- content hash, immutable version과 optimistic concurrency
- 기본 `on_risk`의 sandbox·scope 강제, one-shot ToolApproval과 후속 Permission Lease
- upload size, request·Tool timeout, Project scope와 Conversation 단위 concurrent Run 제한
- 조직별 Run당 model Turn·총 Token·경과 시간·예상 비용 hard limit과 관리자 비상 전체 중단

### 24.2 감사 이벤트

```text
user_created / user_locked / user_unlocked / user_disabled / user_enabled
registration_requested / auth_session_issued
password_reset_issued / role_changed
login_succeeded / login_failed
conversation_share_created / opened / revoked / expired
admin_user_viewed / admin_conversation_viewed / admin_share_force_revoked
admin_run_safety_viewed / admin_run_safety_updated / admin_all_runs_killed
run_action / approval / permission_lease
extension_installed / published / deprecated / revoked
skill_draft_checked_out / skill_draft_updated / skill_draft_binding_changed / skill_version_saved
skill_ownership_added / skill_ownership_removed
skill_folder_created / moved / deleted / skill_folder_placement_changed
artifact_created / edited / restored / downloaded
project_created / project_settings_changed
project_membership_added / project_membership_changed / project_membership_revoked
personal_instructions_changed / project_instructions_changed
organization_instruction_revision_labeled / organization_instruction_revision_content_changed
runtime_prompt_changed / runtime_prompt_unchanged
memory_created / edited / dismissed / deleted
project_learning_proposed / project_learning_approved / project_learning_rejected
project_learning_stale / project_learning_applied / project_learning_rolled_back
scheduled_task_created / changed / enabled / archived / scheduled_run_started
notification_created / read / deleted
message_report_created / status_changed
```

actor, target, action, result, timestamp와 request ID를 기록하되 password, cookie, share token 원문, credential과 대화 원문 전체는 넣지 않습니다.

## 25. 배포와 실행

### 25.1 Windows 진입점

```text
installer.bat
run_lumina.bat
run_lumina_dev.bat
```

최종 구현에서 installer는 dependency, data folder, P-GPT credential, employee number, company code, CA 탐색, combined bundle과 연결 테스트를 처리합니다. 현재 script가 placeholder라면 구현 완료 전 성공처럼 종료하지 않아야 합니다.

`run_lumina.bat`와 `run_lumina_dev.bat`는 `.env`의 `LUMINA_FRONTEND_PORT`, `LUMINA_BACKEND_PORT`를 사용하며 기본값은 각각 `5252`, `5253`입니다. 실행 창의 `r`, `R` 또는 한글 두벌식 `ㄱ` 입력은 Frontend와 Backend를 함께 hard reset합니다. startup 대기 중 입력도 잃지 않고 현재 managed process만 정리한 뒤 전체 재시작하며, 개발 mode에서 평상시 자동 Backend 재시작이 Frontend를 보존하는 최적화와 사용자의 명시적 전체 재시작을 구분합니다.

종료 script는 process 이름이나 port만 보고 임의 process를 죽이지 않습니다. 실행기가 기록한 supervisor identity와 자신이 시작한 child process tree를 확인한 뒤 해당 runtime만 종료하고, identity가 일치하지 않으면 사용자 또는 다른 QA runtime을 보존합니다. SQLite local worker lock도 Windows와 POSIX의 lock primitive 차이를 service 경계에서 흡수하고 같은 DB의 중복 worker만 차단합니다.

### 25.2 개발·운영 topology

```text
Development
├─ React :5252 (격리 QA 기본 :15252)
└─ FastAPI :5253 + local Run executor (격리 QA 기본 :15253)

Initial production
└─ One server
   ├─ Reverse Proxy + React
   └─ FastAPI package
      ├─ API process
      └─ optional sibling Worker process

Scaled production
├─ Frontend
├─ Backend replicas
├─ Worker replicas
├─ PostgreSQL
├─ Redis
└─ Object Storage
```

Windows 개발은 WSL2 + Ubuntu + Podman CLI를 기본 방향으로 하며 Docker Desktop GUI에 의존하지 않습니다. 운영은 회사 Kubernetes를 우선하고 CA와 secret은 read-only volume 또는 Secret reference로 주입합니다. Kind는 개발·배포 검증용이며 운영 cluster로 사용하지 않습니다.

초기 수직 기능을 검증하기 전에 Redis, Kubernetes와 remote Object Storage를 개발 필수 의존성으로 만들지 않습니다. sibling Worker가 하나뿐인 단일 서버는 PostgreSQL 또는 SQLite의 DB-backed claim으로 시작할 수 있으며, 여러 replica가 필요한 시점에 Redis와 PostgreSQL lock 전략을 도입합니다.

## 26. 관측과 운영

- liveness와 readiness 분리
- request ID, Run ID와 actor가 있는 structured log
- Provider·Model별 latency, token, cached input과 비용
- 호출·Run·Session별 cache read/write, uncached input, cache hit ratio, stable prefix hash와 무효화 원인
- user·Project·organization별 quota와 사용량
- Run 성공률, 실패율, 취소, retry와 복구 성공률
- Tool timeout, Browser 재탐색과 Batch item 실패율
- prompt cache hit, prefix 변경 원인과 compaction 영향
- Context 사용률, compaction 전후 token·절감률, ineffective compaction 횟수와 원문 복구 성공률
- web_search query 수, source 수, fetch 승격률, citation 누락·깨진 URL과 evidence snapshot 보존율
- Queue depth, wait time와 worker saturation
- Artifact validation 실패와 renderer version
- 좋아요·싫어요 분포, 신고 category·처리 시간과 diagnostic consent 범위
- Memory 후보 생성·중복 병합·충돌·dismiss·retrieval 수와 prompt 투입 token
- Project별 Session 수, move 성공·보류·권한 거부와 공유 범위 상승 확인
- Codex image generation latency·성공률·실제 backend/model·크기와 Artifact asset 누락률
- TLS, P-GPT, Search와 proxy 단계별 diagnostics

Search 장애가 전체 chat readiness를 막는지, P-GPT가 필수 Provider인지 선택 가능한 Provider인지는 배포 profile로 구분합니다.

## 27. 테스트 전략

### 27.1 테스트 영역

```text
tests/backend   API, DB, Agent, Provider, permission, security
tests/frontend  reducer, component, accessibility, rendering
tests/e2e       actual user flows and browser behavior
tests/evals     Agent quality, recovery and batch consistency
```

### 27.2 Backend 핵심 불변 테스트

- 가입 신청은 중복 email을 차단하고 `invited` 상태·관리자 알림을 만들며 승인 전 로그인과 server session 생성을 거부
- 권한 없는 사용자의 목록·검색·직접 URL·Artifact 차단
- Tool Call마다 정확히 하나의 Tool Result
- Session별 lock과 사용자별 병렬 한도
- Queue action idempotency와 정확히 한 번 승격
- `request_user_input` 단독 호출·질문 schema·한 Run 한 묶음 제한, `awaiting_input` snapshot/replay와 `submit_user_input` 후 정확한 checkpoint 재개
- snapshot·replay의 누락·중복 없음
- Conversation·설정·Help·Skill Draft·Artifact의 stale revision/CAS 거부와 no-op·explicit null validation
- Attachment·Project File·Artifact storage write 뒤 commit·pointer 경합 실패 시 새 unreferenced blob만 정리하고 기존 version은 보존
- immutable Artifact·Extension version
- WorkingDraft 수정이 다음 Run의 Skill 응답에 반영되고 이미 시작한 Run은 draft revision·digest를 유지
- Draft autosave는 version 번호를 만들지 않고 명시적 저장만 `v1`, `v2`를 단조 증가시킴
- 새 Skill Private 기본값, owner 이외 조회 차단, admin 공개 승인과 Auto permission audit
- 사용자별 Draft가 서로 덮어쓰지 않고 복수 Owner 추가·제거에서 primary Owner와 마지막 Owner 보호
- Change Request base version·digest 충돌, approval 무효화, rollback의 새 immutable version 생성과 permission diff 강화 정책
- Skill·Folder move의 stable ID 보존, cycle·동명·scope 검사와 non-empty Folder 삭제 fallback
- 공용 Skill의 사용자별 개인 Folder placement 격리
- base version 충돌의 조용한 overwrite 방지
- Context compaction recovery reference
- soft threshold 선제 compaction, 실패 시 원 Context 보존과 Tool Call/Result pair 유지
- 동일 Run의 system prompt·Tool schema canonical bytes와 prefix hash 안정성
- 기본 `approval_mode=on_risk`에서 read-only·내부 저위험 Tool은 즉시 실행되고 외부 write·삭제는 one-shot 승인을 요구하며 scope 밖 작업은 거부됨
- `admin@posco.com` 동시 로그인에서 같은 Sidebar·Session 상태 복원, 일반 사용자 대화 admin 조회와 audit 기록
- Bootstrap admin의 `must_change_password=false`, startup 재실행 후 password hash 비변경
- Conversation 하나가 UI Session과 동일 ID를 사용하고 별도 sessions mapping이 없음
- SSE sequence replay와 send·cancel·steer HTTP action의 누락·중복 없음
- Provider별 raw usage를 cached input·cache write·uncached input으로 정확히 정규화
- Provider별 초기 Model allowlist·표시 순서·기본값, 표시명과 runtime ID mapping, disabled Model fallback
- OpenAI Compatible discovery 결과가 관리자 allowlist 밖 Model을 자동 활성화하지 않음
- 검색 query·source deduplication, fetched evidence 승격, citation 번호 안정성과 근거 없는 인용 거부
- attachment ownership, MIME sniffing, size·page·pixel 제한과 extraction locator 보존
- Composer suggestion의 Project·사용자 권한 filtering, stable ID·exact version 검증과 중복 reference 제거
- Message text와 `message_references` 분리 저장, rename·uninstall·권한 상실 뒤 display snapshot 보존
- rating user/message unique 상태, 취소·변경과 report diagnostic 최소화
- selection comment의 canonical offset 검증, 변경된 render에서도 quote/context 재탐색과 stale 처리
- UserMemory 민감정보 차단, 중복 병합, 충돌 supersede, 삭제 후 retrieval 제거와 Project 간 비노출
- 사용자 bootstrap의 Default Project 정확히 하나, 이동 transaction·active Run 보류와 권한 상승 확인
- Codex Run에서만 image Tool 노출, non-Codex 실행 거부와 실제 image MIME·Artifact metadata 검증
- committed 복합 Artifact가 원본 attachment 삭제 뒤에도 asset snapshot으로 재현됨
- share grant 취소 후 Preview·download 즉시 거부
- P-GPT token, header와 Secret redaction
- `verify=False` 없는 CA 연결과 SSRF 방어
- 일반 문서 RAG의 형식별 extraction·자연 위치, 문서 filter, 증분 변경·삭제, malformed file 격리, path traversal 차단과 조직 전용 field 제거

### 27.3 Frontend와 실제 브라우저

- 불규칙 streaming delta의 문자 손실 없는 표시
- scroll follow, user detach, latest affordance와 reduced motion
- Session 전환·재연결 후 현재 부분 답변·Tool·Plan 복원
- Sidebar cursor loading, title search, favorite, rename와 delete
- Turn Set 선행 로딩이 현재 scroll 위치를 보존하고 실패 후 재시도하며 live event와 중복되지 않음
- Action Bar, usage popover와 share viewer
- 첫 답변 usage에는 이전 누적 비교를 숨기고 두 번째 답변부터 Session 누적값을 표시
- 좋아요·싫어요 선택·취소·기기 동기화, 문제 신고 category와 diagnostic 동의 확인
- drag selection·우클릭·keyboard로 Comment chip 생성, highlight·전송·stale anchor 표시
- Project Folder 생성·선택·접기, Default fallback과 Session `… → 프로젝트로 이동`
- Project 이동 중 공유 범위 상승 확인, active Run 보류와 완료 후 이동
- Codex에서 image 생성 결과 Preview·다운로드, non-Codex에서 비활성 상태와 Provider 전환 안내
- ① inline marker의 hover·focus URL·근거 문장, click, screen reader label과 전체 검색어·출처 panel
- 12줄 이상 붙여넣기의 별도 chip 전환, 원문 보존·preview·remove와 11줄 paste의 inline 유지
- file picker·drag-and-drop·clipboard image가 동일 attachment tray와 preview·remove 흐름 사용
- `@`·`$`를 문장 처음·중간에서 입력했을 때 Composer 위 candidate panel, keyboard·mouse 선택과 활성 token만 교체
- 선택한 file·Artifact·Skill·MCP의 Composer pill 제거·상세 열기와 전송된 user Message inline pill 렌더링
- 활성 Skill Draft의 candidate·Composer·Message·Run detail `Draft rN` badge, 저장 CTA와 `vN → Draft base vN` 상태 전환
- 이메일·`$6.4`·bare trigger·없는 reference는 pill로 오인하지 않고 일반 text 유지
- Artifact panel resize, fullscreen, Preview/Source, dirty state와 version 전환
- ECharts, Mermaid, Markdown, code, math, image와 PDF 실제 렌더링
- Mermaid label 안전 보정, authored style 보존, fit·zoom·pan·drag scroll·keyboard close와 ECharts option 전달
- 첨부·생성 image를 포함한 HTML·문서 Artifact의 Preview·공유·독립 다운로드 자산 일치
- HTML sandbox 탈출 차단
- download byte, MIME, filename과 독립 HTML 동작
- keyboard-only, focus order, tooltip와 screen reader label
- tooltip·popover·context menu가 body Portal에서 theme·clipping 경계를 지키고 native `title`로 중복되지 않음
- 채팅 폭·글꼴 설정이 revision과 함께 서버에 저장·복원되고 stale 설정 저장이 최신 값을 덮어쓰지 않음
- 정상 동작은 불필요한 성공 toast 없이 상태 변화로 확인되고 오류·부분 실패·guard는 알림을 유지
- active Run에서 비어 있는 Composer의 send action이 stop으로 전환되고 click·Enter가 cancel을 한 번만 전송하며, 입력 payload가 있으면 steer를 유지
- Conversation 전환 중 welcome flash 없이 loading을 표시하고 load 완료 뒤 실제 empty state 또는 Turn을 표시
- 예약 작업 삭제의 동일 버튼 2단계 확인, 대상 변경 시 해제, archive 성공과 실패·재시도 상태
- Marketplace 설치 Skill Markdown 기본 보기·browser history 복귀와 MCP `미사용`의 실제 installation 해제
- builtin Agent Frontend registry 제거·미지원 contract에서 `general-chat` fallback과 원래 Agent ID·Run·Artifact 보존
- 개발 로그인 helper가 production build에는 없고 development build에서 tooltip·접근성 이름·자동 입력 후 password focus를 제공

JSDOM과 API test만으로 UI 완료를 판정하지 않습니다.

개발 검증의 기본 명령은 다음과 같습니다.

```powershell
$env:PYTHONPYCACHEPREFIX = "$PWD\.cache\pycache"
uv run --project apps/server pytest -c apps/server/pyproject.toml
npm --prefix apps/web test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

PDF 실제 렌더는 `pdftoppm`, DOCX·XLSX·PPTX 실제 렌더는 LibreOffice와 `pdftoppm`, PostgreSQL migration 통합 test는 전용 `LUMINA_TEST_POSTGRES_URL`과 `LUMINA_TEST_POSTGRES_ALLOW_MIGRATIONS=1`이 있을 때만 실행합니다. 조건이 없으면 구조 검증을 계속하되 render 검증을 통과로 오인하지 않고 해당 test를 명시적으로 skip합니다. 브라우저 QA는 사용자 port `5252/5253`을 점유·종료하지 않고 `15252/15253` 또는 다른 빈 port에서 해당 작업이 시작한 process만 정리합니다.

### 27.4 Fault injection과 Eval

- Tool timeout 후 대체 경로
- Worker restart 후 checkpoint resume
- Browser selector 변경 후 재탐색
- Batch 일부 실패 후 해당 item만 retry
- Artifact recovery ref 누락 시 복구 선택지
- optional `confirm` mode의 Permission Lease 만료 후 재승인
- Provider optional field 거부 후 안전 fallback
- compaction 전후 목표·승인·부작용 보존

## 28. 단계별 구현 계획

단계는 infrastructure layer를 수평으로 모두 만든 뒤 UI를 붙이는 방식이 아니라, 사용자가 로그인해 질문하고 응답·복구·Artifact를 확인하는 수직 흐름을 매 단계 완성하는 방식으로 진행합니다. 각 phase에서 사용하지 않는 table, service, adapter와 설정은 만들지 않습니다.

### Phase 0. 최소 수직 흐름

1. seeded Organization, User, server session, role과 Bootstrap admin
2. 사용자별 Default Project, Conversation, Message와 소유권 filter
3. SQLite, SQLAlchemy, Alembic, PostgreSQL 호환 test와 managed local storage
4. 하나의 Provider Adapter, Trust Manager와 P-GPT 또는 test Provider
5. 질문 → DB 저장 → model stream → final Message 저장의 실제 browser 흐름
6. structured log, 최소 audit와 Secret redaction

### Phase 1. 핵심 채팅과 Run

1. DB-backed Run claim과 local executor
2. SSE, coalesced text event와 canonical snapshot
3. Conversation별 lock, 사용자별 동시 Run과 Queue
4. snapshot·sequence replay와 세션 전환 복구
5. Provider별 Model Catalog, capability, runtime ID mapping과 Provider·Model·Effort 선택의 서버 저장
6. 첫 Tool 실행, 기본 `on_risk` scope enforcement와 Tool status UI
7. Composer 위 `@file`·`@artifact`·`$Skill`·`$MCP` candidate panel과 Message pill
8. 문서·image upload, clipboard image paste와 12줄 이상 pasted text chip
9. agentic `web_search`·`web_fetch`, evidence 저장, inline citation과 검색어·출처 panel
10. stable prompt prefix, Provider cache usage 정규화와 자동 Context compaction
11. 답변 Action Bar, 좋아요·싫어요·문제 신고와 선택 문장 Comment
12. 자동 UserMemory 추출·조회·수정·삭제와 민감정보 차단
13. 개인 Project Folder 생성·선택과 Session 이동
14. 기본 Artifact 저장

### Phase 2. Plan, Project와 Artifact

1. 구조화 Plan, Step, Subtask와 retry
2. steer, queue_next, pause, resume와 cancel
3. Server Workspace, upload, file version
4. Artifact Library와 우측 panel
5. HTML·Markdown·text·image·PDF renderer
6. Codex 전용 image generation과 Image Artifact
7. 첨부·생성 image asset을 포함한 복합 HTML·문서 Artifact
8. 수동·AI edit와 immutable version
9. 링크 기반 read-only share viewer

### Phase 3. 전문 업무와 확장

1. 실제 다중 사용자 운영 전 PostgreSQL cutover 검증
2. DOCX·XLSX·PPTX·PDF·HTML 생성 및 형식별 검증
3. 대화 기반 실행 가능 Skill WorkingDraft, 명시 저장형 immutable version과 Skill 중심 Marketplace
4. Skill Merge·Diff·Change Request·Publish·Rollback과 위험 기반 검토
5. user·Project·Organization Skill Folder tree와 Skill·Folder 이동
6. 승인된 MCP definition·Secret binding과 일반 로컬 문서 RAG 전환
7. Extension review와 Organization policy
8. Plugin authoring·sandbox는 Skill·MCP 운영 후 별도 검증
9. Project Memory와 승인형 learning proposal
10. Browser automation과 회사 승인 Connector
11. Scheduler와 Background notification

### Phase 4. 확장 플랫폼

1. persistent·user-managed Execution Environment
2. Local Workspace Bridge
3. Batch Fan-out
4. 두 번째 builtin Agent Frontend PoC
5. declarative UI와 MCP Apps sandbox
6. Computer Use
7. Redis·Object Storage·Kubernetes 기반 multi-node scale-out
8. 사용량이 입증된 Skill package Blob/Tree CAS, GC와 자동 Skill Eval

각 phase의 완료 조건은 해당 기능의 table과 API가 존재하는 것이 아니라 실제 사용자 흐름, 재접속 복구, 권한 거부와 실패 복구가 함께 검증되는 것입니다.

## 29. 통합 수용 기준

1. 사용자 A와 B의 개인 Session, 검색, Artifact와 설정이 서로 노출되지 않습니다.
2. 한 사용자의 Session A와 B Run은 병렬 실행되고 같은 Session의 추가 Run은 Queue에 들어갑니다.
3. 사용자가 Session을 떠나거나 브라우저를 닫아도 Run은 계속되고 snapshot·replay로 현재 상태를 복원합니다.
4. replay와 live 전환에서 text, Tool Result와 Artifact가 누락·중복되지 않습니다.
5. 실행 중 Enter, Ctrl+Enter와 Shift+Enter가 각각 steer, queue_next와 줄바꿈으로 동작합니다.
6. Plan과 Step 상태, pause·resume·cancel·retry가 Backend 원본으로 복원됩니다.
7. Context에서 제거한 정보는 권한이 있는 recovery reference로 원문을 다시 찾을 수 있습니다.
8. 모든 Run은 실행 환경, 데이터 위치, 유지 기간과 권한을 설명할 수 있습니다.
9. `@`와 `$`는 stable ID와 exact version을 사용하며 Backend가 권한을 다시 검사합니다.
10. Artifact는 immutable version, 검증 결과, 원본 Run과 stable deep link를 가집니다.
11. Renderer가 실제 브라우저에서 동작하며 악성 HTML이 app context를 탈출하지 못합니다.
12. 링크 기반 share viewer는 snapshot만 보여주고 소유자의 history와 다른 Project를 노출하지 않습니다.
13. view share 수신자는 Run을 조작할 수 없으며 Project member와 Run collaborator 권한이 분리됩니다.
14. Extension update 후에도 과거 설치와 Run이 exact version과 digest로 재현됩니다.
15. P-GPT와 Web Search가 회사 CA를 사용하면서 TLS 검증을 유지하고 실패 단계를 구분합니다.
16. 관리자 action과 민감한 사용자·대화 조회가 audit에 남고 Secret은 표시되지 않습니다.
17. 같은 ID의 여러 기기는 동일한 Session, Run, Artifact, 알림과 설정을 동기화합니다.
18. 전문 Artifact는 생성 성공과 형식별 검증 성공을 별도로 표시합니다.
19. Frontend를 전환해도 진행 중 Run의 snapshot과 생명주기가 바뀌지 않습니다.
20. 실제 브라우저 E2E와 recovery fault test를 통과해야 완료로 판정합니다.
21. 별도 Deep Research mode 없이 Agent Loop가 반복 검색·fetch·상충 근거 확인을 수행하고, 최종 답변의 ① marker에서 URL과 실제 근거 문장을 검증할 수 있습니다.
22. 최종 답변에는 실행한 검색어와 참고한 모든 링크가 중복 없이 표시되고, 직접 인용한 출처와 참고만 한 출처가 구분됩니다.
23. PDF·문서·image를 upload할 수 있고 clipboard image가 attachment로 추가되며, 12줄 이상 text paste는 원문을 잃지 않는 별도 chip으로 표시됩니다.
24. Context가 유효 예산에 가까워지면 실행 중인 목표·Plan·승인·Tool pair·citation을 보존한 채 자동 압축하고, 실패하면 압축 전 Context를 유지합니다.
25. 두 번째 이후 Turn의 cache hit과 cache read/write 비용을 확인할 수 있고, system prompt·Tool schema·과거 message가 이유 없이 바뀌어 prefix cache를 깨지 않습니다.
26. 사용자는 답변에 좋아요·싫어요를 남기거나 취소할 수 있고, 최소 진단정보 범위를 확인한 뒤 문제를 신고할 수 있습니다.
27. assistant 답변의 문장을 drag 또는 keyboard로 선택하고 우클릭·selection action으로 Comment를 작성하면 선택 구간이 후속 질문의 구조화 Context로 전달됩니다.
28. 사용자의 안정된 선호와 반복 정보는 Turn 완료 뒤 개인 UserMemory로 자동 학습되고, 사용자가 출처를 확인하거나 수정·삭제·학습 중지할 수 있으며 다른 사용자·공유 Project에 노출되지 않습니다.
29. 모든 사용자는 Default Project Folder를 가지며 개인 Project를 생성·선택할 수 있고, Session의 `…` 메뉴에서 권한과 실행 상태 검사를 거쳐 다른 Project로 이동할 수 있습니다.
30. Project concept·지침·기본 설정은 새 Run에 snapshot으로 적용되고 다른 Project의 파일·Memory·Secret을 섞지 않습니다.
31. `generate_image`는 Codex Provider와 실제 capability가 있는 Run에서만 노출되고, 결과가 source Run·backend·model·prompt hash를 가진 immutable Image Artifact로 저장됩니다.
32. 첨부 이미지와 생성 이미지를 HTML·문서 Artifact의 본문 자산으로 함께 사용할 수 있고 Preview·공유·독립 다운로드에서 이미지와 layout이 재현됩니다.
33. 여러 개발팀원이 `admin@posco.com`으로 로그인하면 같은 채팅·Project·Artifact·설정을 보고, admin viewer에서는 다른 일반 사용자의 채팅을 audit와 함께 조회할 수 있습니다.
34. Bootstrap admin은 비밀번호 `1`로 로그인한 뒤 최초 변경을 강제받지 않으며 서버 재시작이 관리자가 변경한 비밀번호를 덮어쓰지 않습니다.
35. 기본 `local_worker` Run은 `on_risk`로 동작하여 read-only·내부 저위험 Tool에는 승인창을 띄우지 않고 외부 write·삭제는 one-shot 승인을 요구하며 Project·사용자·sandbox·조직 정책 경계를 넘는 작업은 거부합니다.
36. 채팅 하나는 하나의 Conversation ID만 사용하고 별도 Session table을 만들지 않으며, 답변 stream은 SSE, 사용자 action은 HTTP API로 동작합니다.
37. `@` 또는 `$` 입력 시 권한 있는 file·Artifact·Skill·MCP 후보가 Composer 바로 위에 표시되고 keyboard와 mouse로 선택할 수 있습니다.
38. 선택한 reference는 Composer와 전송된 user Message에서 type이 구분되는 pill로 표시되며, stable ID·version으로 열리고 삭제·권한 상실 뒤에도 당시 이름과 사용 불가 상태를 재현합니다.
39. 대화에서 Skill을 만들거나 수정하면 소유자의 다음 Run이 최신 Draft revision을 실제로 사용하고, 진행 중이거나 과거 Run은 고정 digest로 재현됩니다.
40. Draft autosave 중에는 공개 version이 생기지 않으며 명시적인 저장마다 `v1`, `v2`, `v3`가 생성되고 이전 version은 바뀌지 않습니다.
41. 새 Skill은 본인 전용 Private이고 공용 공개는 admin 승인 또는 개발용 Marketplace Auto permission mode로 처리되며 모든 게시 action이 audit에 남습니다.
42. 사용 중인 Skill이 WorkingDraft이면 candidate, Composer, 채팅 Message, 결과 card와 Run detail에서 `Draft rN · 저장 안 됨`을 확인하고 `v1로 저장` 또는 `새 버전으로 저장`을 실행할 수 있습니다.
43. Draft를 저장하면 `vN`으로 바뀌고 다시 수정하면 `Draft · base vN`으로 돌아가며, 다른 기기와 과거 Run에는 각자 실제 사용한 revision·version이 정확히 표시됩니다.
44. Skill과 Folder를 계층 tree에서 이동해도 Skill ID, Draft·version digest, installation, Composer pill과 과거 Run reference가 바뀌지 않습니다.
45. 개인·Project·Organization Folder scope를 구분하고 cycle·동명 Folder·권한 없는 scope 이동을 차단하며, 공용 Skill은 사용자마다 별도의 개인 Folder에 정리할 수 있습니다.
46. P-GPT·Codex·Gemini에는 12.3의 사용자 지정 Model만 초기 노출되고 OpenAI·Anthropic에는 검증된 최신 소수 Model만 표시되며, 표시명·runtime ID·capability·catalog revision이 Run에 고정됩니다.
47. OpenAI Compatible의 discovery와 외부 Provider의 신규 Model 출시는 관리자 검토 없이 자동 활성화되지 않고, disabled·삭제된 저장 Model은 사용자 알림과 함께 허용 기본값으로 안전하게 fallback합니다.
48. 가입 신청은 `invited` 상태와 관리자 알림으로 접수되고 승인 전 로그인할 수 없으며, 관리자가 신청 role·소속을 검토해 활성화한 뒤에만 server session을 만듭니다.
49. 대화 즐겨찾기와 좋아요가 별도 서버 상태로 복원되고 좋아요한 대화는 전용 filter와 자동 보존 제외에 사용되지만 Message 품질 feedback으로 오인하지 않습니다.
50. 활성 Run에서 빈 Composer의 기본 action은 중단으로 바뀌고 payload가 있으면 steer를 유지하며, Session 전환 중에는 이전 내용이나 신규 welcome 대신 복원 loading을 표시합니다.
51. 예약 작업 삭제는 인라인 2단계 확인 뒤 archive되어 새 실행에서 제외되고 과거 실행·Artifact·audit는 보존됩니다.
52. 일반 문서 RAG MCP는 지원 형식별 자연 위치 citation과 4개 일반 Tool 계약을 제공하고, 조직 전용 field를 제거하며 malformed 문서와 index 변경을 다른 문서에서 격리합니다.
53. Skill 기여는 개인 Draft, immutable version, 구조적 diff, Change Request, Owner 검토와 새 version rollback으로 이어지고 Run은 실제 사용한 UUID·digest를 계속 고정합니다.
54. 관리자는 Run당 400 model Turn, 총 4,000,000 Token, 10,080분과 예상 비용 $100의 기본 안전 한도를 모두 조정할 수 있고, 비상 시 같은 조직의 모든 활성·대기 작업을 인라인 2단계 확인으로 즉시 중단할 수 있습니다.

## 30. 확정된 구현 결정

이 항목들은 더 이상 미결 사항이 아닙니다. 구현 중 별도 ADR로 변경하지 않는 한 아래 값을 기본 계약으로 사용합니다.

### 30.1 개발팀 채팅 공유

별도 전역 shared mode를 만들지 않습니다. 개발팀원이 모두 `admin@posco.com`으로 로그인하므로 같은 계정이 소유한 채팅 Session, Project, Artifact, 설정과 Memory가 자동으로 공유됩니다. admin은 관리자 viewer에서 다른 일반 사용자의 채팅도 조회할 수 있으며 모든 조회·다운로드·변경은 audit에 남깁니다.

### 30.2 Bootstrap 관리자 비밀번호

`admin@posco.com / 1`과 `must_change_password=false`를 유지하며 최초 변경을 강제하지 않습니다. 상용화 시 관리자가 직접 바꾸며 installer와 startup은 자동으로 임의 비밀번호·SSO 정책으로 전환하지 않습니다.

### 30.3 Session과 Conversation

사용자가 UI에서 보는 채팅 하나와 DB의 `Conversation` 하나를 같은 객체로 사용합니다. 별도 `sessions` table은 만들지 않습니다. 쉽게 말하면 채팅 한 개를 표현하는 이름을 UI에서는 Session, Backend에서는 Conversation이라고 부를 뿐 데이터는 하나입니다.

### 30.4 실시간 응답 연결

초기 구현은 SSE만 사용합니다. SSE는 서버가 생성 중인 답변과 Tool 상태를 브라우저로 계속 보내는 단방향 연결입니다. 사용자의 보내기·취소·steer는 일반 HTTP API를 사용합니다. WebSocket은 구현하지 않으며 실제로 SSE로 해결할 수 없는 요구가 확인될 때만 다시 검토합니다.

### 30.5 실행 환경

초기 구현은 Lumina 서버의 격리된 `local_worker` 가상환경만 실행합니다. 장시간 유지되는 별도 workspace와 사용자 PC를 직접 조작하는 `user_managed bridge`는 구현하지 않고 후속 Phase에 둡니다. metadata에는 `environment_type=local_worker`를 저장해 나중에 환경을 추가해도 Run 계약을 바꾸지 않습니다.

### 30.6 Frontend와 위험 기반 실행 승인

초기 Agent Frontend는 Lumina에 포함된 builtin module만 사용하고 외부 package·remote·sandbox Frontend loader는 구현하지 않습니다. 이 결정과 Tool 승인 방식은 별개이며, 격리된 `local_worker`의 Tool 실행은 기본 `approval_mode=on_risk`로 확정합니다. 조회와 Lumina 내부 저위험 생성은 즉시 실행하고 외부 write·삭제 등 위험 effect는 durable one-shot 승인을 받으며, 다른 사용자 데이터·Project root·조직 정책·sandbox 경계를 넘는 작업은 계속 차단합니다.

## 31. 구현 시 문서 유지 규칙

- 이 문서는 통합 구현 기준으로 사용하고 기능별 원문은 조사 근거와 상세 수용 기준으로 보존합니다.
- 중요한 계약 변경은 `docs/project-context/decisions/`에 ADR로 기록합니다.
- 새 옵션에는 저장 scope, default, restore 시점과 invalid fallback을 함께 정의합니다.
- API와 event schema가 바뀌면 Frontend SDK, replay test와 이 문서를 함께 갱신합니다.
- 개발 구현과 이 설계가 충돌하면 조용히 코드를 맞추지 말고 차이, 영향과 선택지를 먼저 기록합니다.
- 최신 외부 제품 동작이나 Provider API에 의존하는 항목은 구현 직전에 공식 문서를 다시 확인합니다.

## 32. 개발 도구와 저장소 위생

- 코드 수정, review, refactoring과 여러 파일의 영향 조사에서는 기존 CodeGraph index를 우선 조회합니다.
- 조회에는 `codegraph_context`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`, `codegraph_impact`를 실제 source 확인과 함께 사용합니다.
- Codex는 코드 작업 전에 `codegraph_status`와 `.codegraph/codegraph.db` 수정 시각을 확인합니다. graph가 없으면 init하고, 마지막 갱신 뒤 source 또는 Git HEAD가 바뀌어 오래된 경우에는 sync한 다음 작업합니다.
- init과 sync는 모두 `powershell -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1`을 사용합니다. script는 DB가 없으면 full build, 있으면 증분 update를 자동 선택하며 CodeGraph 2.x의 첫 index 전에 실제 Git HEAD가 있어야 합니다.
- 갱신 뒤 `codegraph_status`와 DB 수정 시각을 다시 확인합니다. 갱신 실패를 무시하거나 오래된 graph를 최신인 것처럼 사용하지 않습니다. 순수 문서·문구 수정처럼 code 영향 조사가 없는 작업은 이 절차를 생략할 수 있습니다.
- `.codegraph/`, `.examples/`, `data/`, Secret과 생성 산출물은 CodeGraph 또는 Git에 잘못 포함하지 않습니다.
- `.examples/`를 조사할 때는 `.examples/AGENTS.md`를 먼저 따르고, 참고 code를 Lumina source에 직접 import하거나 build·test·package·deploy 대상에 넣지 않습니다.
- 실제 데이터, `.env`, 인증서, API key와 사용자 비밀값은 Git에 commit하지 않습니다.
- Windows와 Linux에서 모두 동작하도록 path와 runtime 환경을 처리합니다.
