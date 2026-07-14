> 생성일: 2026-07-12

# Extension Marketplace 설계

## 목적

이 문서는 `.examples/AI_Skill_MarketPlace/` 목업에서 확인한 카탈로그, 상세 파일 조회, 설치, Fork, 작성, 수정과 삭제 경험을 Lumina Agent의 다중 사용자용 Skill·MCP·Plugin 관리 플랫폼으로 확장한 제품·Backend 계약입니다.

목업 코드는 참고 자료이며 Lumina의 런타임 의존성으로 사용하지 않습니다. 목업의 `accountId` 전달, 관리자 비밀번호와 로컬 JSON 설치 목록은 실제 인증·인가와 DB 모델로 대체합니다.

## 핵심 결정

1. Marketplace의 카탈로그 자원과 사용자·Project에 설치된 자원을 분리합니다.
2. 기본 관리 계층은 `Organization → Project → User`이며 설치 범위는 개인, Project, Organization 중 하나입니다.
3. 대화에서 생성·수정한 Skill Draft는 소유자의 실제 Agent Run에서 즉시 사용할 수 있습니다. Draft 변경은 내부 `draft_revision`과 digest를 갱신하지만 공개 version 번호를 만들지 않습니다.
4. 사용자가 명시적으로 `저장`하면 현재 Draft package 전체를 불변 snapshot으로 복사해 `v1`, `v2`, `v3`처럼 단조 증가하는 새 SkillVersion을 만듭니다.
5. Run은 Draft 사용 시 `draft_id + draft_revision + digest`, 저장 version 사용 시 `extension_id + version_id + digest`를 정확히 고정합니다. Draft가 바뀌어도 이미 시작한 Run은 바뀌지 않습니다.
6. 설치 해제와 Skill 삭제를 구분합니다. Skill 삭제는 30일 보관함 이동이며 그 전에는 복원할 수 있습니다. 보존 기간 뒤 catalog·Draft·version·installation 원본은 정리하되, 이미 완료된 Run의 고정 snapshot과 감사 기록은 유지합니다.
7. Frontend가 보낸 소유자, 조직, 경로, 권한과 비밀값을 신뢰하지 않습니다. Backend가 인증 주체와 정책으로 다시 결정합니다.
8. Skill은 서버에서 직접 실행되는 code가 아닌 지침 package로 취급합니다. Plugin과 MCP는 실행·network 위험이 있으므로 검증과 permission policy를 통과하기 전에는 Worker에 노출하지 않습니다.
9. `creator_user_id`는 최초 기여 기록으로 고정하고, 현재 관리 책임은 복수 `SkillOwnership`의 Owner·Maintainer로 분리합니다. 소유권 변경은 Creator 기록을 바꾸지 않습니다.
10. 공개 Skill의 수정은 공용 WorkingDraft를 공유하지 않고 사용자별 개인 WorkingDraft를 만듭니다. 같은 사용자의 병렬 변경이 충돌하면 기존 head를 덮어쓰지 않고 별도 branch로 보존합니다.
11. 사용자에게 보이는 `vPublish.Merge.Feedback`는 진화 상태를 설명하는 계산된 표시값입니다. 내부 정렬·참조·Run 재현은 immutable `version_id`, Draft `revision_id`와 digest를 사용합니다.

## 목업에서 채택할 사용자 경험

- Skill 이름·설명·Category·tag 통합 검색, Category·tag 필터와 활용도·최근순 정렬
- 카탈로그 카드에는 이름, 짧은 설명, Category·tag, 현재 사용자 설치 수, 실제 적용 Run 수와 좋아요만 표시
- 패키지 파일 트리, README 렌더링과 원문 전환은 `설치됨` 또는 소유·관리 화면에서만 제공
- 내 설치 목록과 내 Draft/Fork 목록
- 설치·설치 해제, Fork, 대화의 Skill Creator 기반 작성, Owner·관리자의 보관함 이동과 복원
- 기본 정보 → 파일 구성 → 입력 계약 → 테스트 → 보안 확인 → 검토/게시의 작성 흐름
- 실제 사용 중인 WorkingDraft에는 `Draft · rN · 저장 안 됨` badge와 `v1로 저장` 또는 `새 버전으로 저장` action 표시

좋아요, 현재 사용자 설치 수와 실제 Skill 적용 Run 수는 선호도와 활용도를 찾기 위한 탐색 보조 지표로만 표시합니다. 누적 다운로드 수, 성공률, QA 점수나 모호한 신뢰도는 카탈로그에 표시하지 않으며 권한이나 품질 보증의 근거로 사용하지 않습니다.

## 자원 유형별 계약

### Skill

Skill package는 최소 `SKILL.md`를 가지며 선택적으로 manifest, references, scripts, examples와 assets를 포함합니다. Marketplace가 관리하는 Skill에는 안정적인 `skill_id`와 별도의 불변 `skill_version_id`를 부여합니다.

```text
Skill
├─ User A WorkingDraft revision 1..N (mutable personal head)
├─ User B WorkingDraft revision 1..N (mutable personal head)
├─ SkillVersion v1 (immutable, explicit save)
   ├─ SKILL.md
   ├─ manifest
   └─ package files
└─ SkillVersion v2 (immutable, parent=v1)
```

- Harness 대화에서 “이 작업을 Skill로 만들어”라고 하면 본인 전용 WorkingDraft를 만들고 현재 사용자에게 활성화합니다. 이 시점에는 `v1`이 없습니다.
- 다른 사용자의 Published Skill에서 `내 버전으로 수정`을 시작하면 최신 설치·공식 version을 기준으로 해당 사용자만의 WorkingDraft를 만듭니다. 원본 Owner의 Draft와 다른 사용자의 Draft는 바뀌지 않습니다.
- Draft는 autosave하며 각 변경에 내부 revision과 package digest를 부여합니다. 다음 Agent Run부터 최신 Draft revision을 실제 Skill로 사용하여 응답 변화가 나타나야 합니다.
- 첫 명시적 `저장`은 현재 Draft snapshot으로 immutable `v1`을 만들고, 이후 다시 수정한 Draft를 저장하면 `v2`를 만듭니다.
- 저장 직후 WorkingDraft의 `base_version_id`를 새 version으로 옮기고 clean 상태로 유지합니다. 이후 대화 수정이 생기면 다시 Draft head를 사용합니다.
- 사용자가 Draft임을 항상 인지할 수 있어야 합니다. version이 한 번도 없으면 `Draft · rN · 저장 안 됨`과 `v1로 저장`, base version이 있으면 `Draft · rN · base vN`과 `새 버전으로 저장`을 표시합니다.
- 과거 버전에서 수정해도 새 번호는 해당 Skill의 최신 번호 다음 값으로 발급하고 `parent_version_id`로 분기 계보를 기록합니다.
- Draft 갱신은 `draft_revision`과 ETag를, version 저장은 `draft_id`, expected revision, `base_version_id`와 digest를 요구합니다. 충돌 시 다른 작업을 조용히 덮어쓰지 않습니다.
- 버전 번호는 표시용 정수 `v1`, `v2`, `v3`를 기본으로 합니다. 호환성 표기가 필요하면 별도 `release_label`에 SemVer를 둘 수 있지만 불변 version ID를 대체하지 않습니다.
- 게시, 검증, 폐기는 version 단위 상태입니다. Skill 전체의 `latest_published_version_id`는 포인터일 뿐 과거 version을 변경하지 않습니다.

### Skill 진화 표시 버전

Skill의 진화 상태는 `vPublish.Merge.Feedback` 형식으로 표시할 수 있습니다. 이 문자열은 내부 식별자가 아니며 다음 정수에서 계산합니다.

```text
v3.2.7
 │ │ └─ 현재 Merge 이후 실제 반영된 Feedback 수
 │ └─── 현재 Publish 세대의 Merge 수
 └───── Marketplace 공식 Publish 세대
```

- Feedback은 최종 package digest가 실제로 달라진 정상 완료 수정 요청에 한 번만 반영합니다. Agent 내부 재시도·테스트·무변경 응답은 증가시키지 않습니다.
- Feedback 변경은 `ExtensionDraftRevision`, Merge·Publish·Rollback 결과는 immutable `ExtensionVersion`으로 저장합니다.
- 동시에 여러 개인 작업본이 같은 `v3.2.7` 표시 상태를 가질 수 있으므로 API와 Run은 표시 문자열만으로 version을 선택하지 않습니다.
- 공식 원복은 과거 Tree를 다시 가리키는 새 Publish version을 만들며 Publish 번호를 감소시키지 않습니다.
- 기존 단조 증가 `v1`, `v2`는 immutable snapshot의 sequence label로 계속 보존하고, 진화 표시값과 분리합니다.

### MCP

MCP 항목은 서버 정의와 사용자가 실제로 연결하는 credential binding을 분리합니다.

- 카탈로그: 이름, transport, command 또는 URL template, 제공 Tool, 필요 권한, 네트워크 대상과 검증 상태
- 설치: 범위, 활성 revision, 허용 Tool, timeout, 승인 정책
- Secret binding: 사용자 또는 Organization의 Secret Store 참조만 저장하며 값은 manifest, 로그와 Run event에 넣지 않음
- 연결 설정 수정은 새 configuration revision을 만들고, health check와 Tool schema 검증 후 활성화
- 일반 사용자는 승인된 MCP 항목을 설치하고 자신의 credential을 연결할 수 있습니다. 임의 command·URL 등록과 Organization 공개는 관리자 또는 별도 publisher 권한 및 검토가 필요합니다.
- MCP runtime은 protocol revision `2025-11-25`의 initialize/initialized, pagination된 `tools/list`, `tools/call`과 cancellation lifecycle을 따릅니다.
- Run은 선택된 installation ID, configuration revision ID, digest와 Tool allowlist를 고정하고, 협상한 `tools/list`와 승인 schema가 정확히 일치하는 Tool만 provider에 namespace 이름으로 노출합니다.
- `stdio`는 승인 executable을 `shell` 없이 제한된 환경·작업 디렉터리에서 실행합니다. `streamable_http`는 Trust Manager, redirect 차단, host allowlist와 요청 전후 DNS/IP 검증을 사용합니다. RFC1918·IPv6 ULA·loopback 주소는 revision의 관리자 승인 `allowedIpRanges` CIDR 안에 있을 때만 허용하고 unspecified·link-local·multicast는 항상 차단합니다.
- credential은 process argument, URL 또는 query에 넣지 않습니다. HTTP revision의 `headerTemplates`는 승인된 header 이름과 단일 Secret placeholder만 허용하며 CR/LF를 거부합니다. 현재 runtime resolver는 `env://`만 지원하고 `secret://`·`vault://`는 resolver 미구성 오류로 종료합니다.
- MCP 응답 본문과 실제 argument, URL, header, stderr는 ToolExecution DB, Run event와 오류 메시지에 남기지 않으며 진행 UI에는 안전한 필드 metadata와 완료·오류 상태만 저장합니다.

### Plugin

Plugin은 Skill, MCP binding, Tool, UI와 기타 자원을 묶을 수 있는 versioned package입니다.

- manifest에 포함 자원, 최소 Lumina version, Backend/Frontend entrypoint, 권한과 dependency를 선언합니다.
- package는 서명 또는 digest로 식별하고 설치 전에 정적 검사와 호환성 검증을 수행합니다.
- Backend 코드, browser UI 또는 Worker code를 포함한 Plugin은 승인된 sandbox/배포 경로에서만 활성화합니다.
- Plugin 삭제 시 포함 Skill·MCP를 무조건 연쇄 삭제하지 않고 dependency와 다른 설치 참조를 먼저 검사합니다.

## 공개 범위와 역할

| 범위 | 조회 | 설치 | 작성·새 버전 | 게시·폐기 |
|---|---|---|---|---|
| Private | 소유 사용자 | 소유 사용자 | 소유자 | 소유자 |
| Project | Project 구성원 | Project 정책상 허용 역할 | 작성자·관리자 | Project 관리자/검토자 |
| Organization | 허용된 조직 구성원 | 조직 정책상 허용 역할 | Publisher | 조직 관리자/검토자 |

기본 역할은 User, Author, Publisher, Reviewer, Organization Admin, Operator로 나눕니다. 한 사람이 여러 역할을 가질 수 있지만 작성자가 자신의 Organization 공개 version을 단독 승인하지 못하도록 정책으로 분리할 수 있어야 합니다.

Skill 자산 자체에는 제품 역할과 별도로 다음 소유권을 둡니다.

- `Creator`: 최초 작성 사용자이며 영구 기여 기록입니다. 계정 비활성화나 조직 이동으로 관리 권한을 잃어도 바꾸지 않습니다.
- `Owner`: 복수 지정할 수 있는 현재 관리 책임자입니다. Merge 검토, Change Request 결정, Publish와 원복 권한을 가집니다.
- `Maintainer`: Draft·metadata와 운영 검토를 지원하며 Publish 권한은 조직 정책으로 제한합니다.
- Owner 추가·제거·이전은 모두 Audit Log에 남깁니다. 마지막 Owner 또는 기존 primary Owner 제거는 명시적 소유권 이전 workflow 없이 허용하지 않습니다.

새 Skill과 Draft의 기본 범위는 `Private`이며 생성한 사용자만 검색·사용·수정할 수 있습니다. UI의 `공용으로 공개`는 인터넷 공개가 아니라 같은 Lumina Organization의 모든 허용 사용자가 카탈로그에서 보고 설치할 수 있는 `Organization` 공개를 뜻합니다.

- 일반 사용자가 공용 공개를 요청하면 현재 Draft를 먼저 immutable version으로 저장하고 `InReview`로 제출합니다. admin 승인 후 `Published`와 Organization visibility를 적용합니다.
- `admin@posco.com` 또는 Organization Admin은 자신이 만든 version을 공용으로 직접 게시하거나 다른 사용자의 요청을 승인할 수 있습니다.
- `marketplace_permission_mode`는 Organization setting에 `auto | admin_review`로 저장합니다. 개발 profile 기본값은 `auto`, 그 밖의 profile 기본값은 `admin_review`이며 startup/bootstrap에서 복원하고 알 수 없는 값은 `admin_review`로 fallback합니다. `auto`에서는 작성·개인 사용·공용 게시 permission을 정책상 자동 승인합니다.
- Auto permission도 schema·path·Secret 검사, package digest, audit와 Run snapshot을 생략하지 않습니다. Runtime Tool의 `approval_mode=yolo`와 Marketplace 게시 permission은 서로 다른 설정입니다.

공개 범위는 카탈로그 조회 권한이고 설치 권한과 동일하지 않습니다. 보이는 항목이라도 Project 정책, 외부 네트워크, 파일 접근, 필요한 Secret과 관리자 전용 여부 때문에 설치가 거부될 수 있습니다.

## 상태 모델

```text
WorkingDraft(revision N, executable by owner)
  └─ explicit save → Version vN: Private | InReview | Verified/Beta/Published | Deprecated | Revoked
```

- `WorkingDraft`: 작성자와 허용된 협업자만 편집 가능하며 소유자의 다음 Run에서 실제 사용 가능
- `InReview`: 검토 snapshot 고정, 새 수정은 별도 version으로 생성
- `Verified`: 자동·수동 검증 통과
- `Published`: 허용 범위에서 설치 가능
- `Deprecated`: 신규 설치는 경고 또는 금지, 기존 설치는 정책에 따라 유지
- `Revoked`: 신규 Run에서 사용 금지. 이미 완료된 Run의 snapshot과 감사 증거는 유지

Official은 상태가 아니라 Lumina 또는 조직이 관리하는 publisher 신뢰 표식으로 둡니다.

## Skill Folder 계층과 이동

Skill Folder는 package의 실제 Storage 경로나 Skill ID가 아니라 많은 Skill을 정리하기 위한 논리적 계층입니다.

```text
Skill Folder Root
├─ 공통
│  ├─ 문서
│  └─ 메일
├─ 재무
│  ├─ 월마감
│  └─ 비용분석
└─ 미분류
```

- Folder는 `user | project | organization` scope별로 독립된 tree를 가집니다. 사용자마다 개인 Root와 삭제할 수 없는 `미분류` Folder를 제공합니다.
- 각 Folder는 stable `folder_id`, `parent_folder_id`, 이름, 정렬 순서, 소유 scope와 archived 상태를 가집니다. 표시 path는 parent 관계에서 계산하고 canonical ID로 사용하지 않습니다.
- 같은 scope와 parent 아래 Folder 이름은 대소문자·공백 정규화 후 중복을 허용하지 않습니다. 자기 자신이나 descendant 아래로 Folder를 이동하는 cycle을 차단합니다.
- `SkillFolderPlacement`는 특정 scope에서 Skill이 어느 Folder에 보이는지 연결합니다. version 없는 WorkingDraft도 stable Skill ID를 가지므로 별도 Draft entry를 만들지 않습니다. 한 Skill은 같은 scope tree에서 한 위치만 가지며 공용 Skill도 각 사용자가 자신의 개인 Folder에 다르게 정리할 수 있습니다.
- Folder는 정리 metadata일 뿐 권한을 상속하거나 부여하지 않습니다. 조회·사용·게시 권한은 Skill visibility, installation과 Project·Organization policy로 계속 검사합니다.
- Skill 이동은 placement의 `folder_id`만 transaction으로 바꿉니다. Skill ID, Draft revision, immutable version, package digest, installation, Composer reference와 진행 중·과거 Run snapshot은 바뀌지 않습니다.
- Folder 이동은 Folder와 descendant의 parent 관계를 원자적으로 바꾸고 cycle·destination 권한·이름 충돌을 검사합니다. 대규모 subtree도 중간 상태가 노출되지 않아야 합니다.
- 개인 Folder에서 Project·Organization Folder로 drag하는 동작은 단순 이동으로 처리하지 않습니다. 공개 범위가 달라지므로 `Project에 배치` 또는 `공용 공개 요청` workflow를 사용합니다.
- Folder 삭제 시 비어 있으면 삭제하고, 내용이 있으면 destination 선택 또는 `미분류로 이동`을 요구합니다. Folder 삭제가 Skill·Draft·version·installation을 삭제하지 않습니다.
- 이동 UI는 tree drag-and-drop과 `… → 폴더로 이동`을 함께 제공하며 keyboard 사용자는 destination picker로 같은 작업을 수행할 수 있습니다.
- Marketplace 목록과 `$` candidate는 Folder breadcrumb, descendant 포함 검색과 Folder별 item count를 제공합니다. Skill pill의 canonical label은 Skill 이름이며 상세 tooltip에 Folder path를 표시합니다.

## 설치와 적용

설치 대상은 `user`, `project`, `organization` 중 하나입니다. 일반 Marketplace의 기본 설치는 로그인한 `user` 계정 범위이며, Project와 Organization 설치는 권한이 있는 협업·관리 workflow에서 명시적으로 선택합니다.

```text
Catalog ExtensionVersion
        ↓ install exact version
ExtensionInstallation(scope, version_id, enabled, policy)
        ↓ resolve and authorize
Session/Run extension snapshot
```

- `Install`: 정확한 version, scope, 권한 grant와 설정을 저장합니다.
- 소유자의 WorkingDraft는 별도 catalog publish 없이 `DraftBinding(user_id, draft_id, active)`으로 활성화할 수 있습니다. Run resolver는 활성 Draft가 있으면 저장 version보다 우선하되 정확한 revision·digest를 snapshot합니다.
- `Enable/Disable`: 설치 기록을 유지하면서 새 Run 노출 여부만 변경합니다.
- `Uninstall`: 해당 scope의 연결을 제거합니다. 카탈로그 package나 다른 사용자의 설치는 삭제하지 않습니다.
- `Update`: 새 version을 검토한 뒤 명시적으로 설치 포인터를 전환합니다. 자동 업데이트는 기본적으로 끕니다.
- Project가 허용한 version 범위와 사용자의 개인 설치가 충돌하면 더 제한적인 정책을 적용합니다.
- Composer의 `$Skill`·`$MCP` 검색은 접근 가능한 카탈로그 전체가 아니라 현재 사용자의 활성 WorkingDraft와 현재 Project/사용자에 설치·활성화된 version만 반환합니다.
- Run 시작 시 실제 Skill 파일 digest, MCP configuration revision, Plugin version과 권한 grant를 snapshot으로 고정합니다.
- Catalog API는 패키지 본문 없이 탐색 metadata와 집계만 반환합니다. Published Skill의 package 조회는 현재 사용자·Project·Organization에 유효한 설치가 있거나 사용자가 해당 Skill의 Owner·Maintainer·관리자인 경우에만 허용하며, 권한이 없으면 존재 여부를 추가로 노출하지 않도록 404로 응답합니다.

## 수정, Fork와 삭제

### 수정

대화와 편집기의 일반 변경은 WorkingDraft autosave이며 published version을 만들지 않습니다. 사용자가 `저장`, `버전 저장` 또는 동등한 명시 action을 실행할 때만 `POST 새 SkillVersion`을 수행합니다. 저장 전 변경 diff, 부모 version과 새 version 번호를 보여주며 성공한 뒤에만 base version을 전환합니다.

MCP와 Plugin도 실행 재현성을 위해 revision/version snapshot을 남기지만, Skill의 `v1 → v2 → ...` 전체 복사 규칙은 필수 불변 조건입니다.

### Fork

Fork는 원본과 다른 새 `extension_id`와 Private WorkingDraft를 만들고 `forked_from_extension_id`와 `forked_from_version_id`를 기록합니다. Fork도 명시적으로 저장할 때 첫 `v1`을 만들며 원본의 이후 변경을 자동으로 합치지 않습니다. 원본이 삭제·비공개 전환되어도 권한이 있을 때 적법하게 만든 Fork의 package snapshot은 유지합니다.

### 삭제

- `미사용`은 현재 계정의 설치 연결만 해제하고, `삭제`는 Owner 또는 관리자가 Skill 전체를 보관함으로 이동하는 별도 동작입니다.
- 삭제한 Skill은 카탈로그, Composer candidate와 신규 Run resolver에서 즉시 제외하지만 Draft·version·installation·Folder placement는 30일 동안 그대로 보존합니다.
- Marketplace의 `삭제됨` 탭에서 보관 항목과 자동 삭제 예정일을 확인하고 30일 안에는 원래 ID와 상태를 유지한 채 복원할 수 있습니다. ⓘ tooltip으로 이 보존 정책을 안내합니다.
- 삭제 control은 같은 자리의 2단계 확인을 사용하며 표시 문구는 `삭제 → 경고`로 짧게 유지합니다.
- 30일이 지나면 catalog·Draft·version·installation과 정리 metadata를 물리 삭제합니다. 완료된 Run에 이미 고정된 Skill snapshot과 Audit Log는 삭제하지 않습니다.
- 보안 사고에는 Revoked 처리로 즉시 신규 실행을 막고, 영향을 받은 설치와 Run을 관리자에게 표시합니다.

## 작성과 검증 흐름

1. 유형 선택: Skill, MCP 또는 Plugin
2. 기본 정보: 이름, 설명, 소유 범위, Category, tag, 공개 범위
3. 내용 작성: package 파일 또는 연결/manifest 구성
4. 계약 검증: schema, dependency, Lumina 호환성, 경로 안전성
5. 실행 검증: 격리된 test fixture, MCP health/Tool schema, Plugin sandbox test
6. 보안 검토: Secret 유출, network/file/process 권한, license와 출처
7. WorkingDraft 자동 저장·개인 실행
8. 명시적 저장으로 immutable version 생성
9. 공용 공개 요청 또는 admin·Auto permission 게시

자동 테스트 결과에는 검사기 version과 artifact를 기록합니다. 테스트 통과가 곧 게시 승인을 의미하지는 않습니다.

## 데이터 모델 초안

```text
extensions
  id, kind, slug, owner_user_id, organization_id, project_id,
  visibility, publisher_id, created_at, archived_at

extension_drafts
  id, extension_id, owner_user_id, base_version_id,
  current_revision, current_digest, package_uri, status,
  source_conversation_id, source_run_ids_json, updated_at

extension_draft_revisions
  id, draft_id, revision_number, package_uri, package_digest,
  change_prompt_summary, created_by, created_at

extension_versions
  id, extension_id, version_number, parent_version_id,
  package_uri, package_digest, manifest_json, status,
  created_by, created_at, published_at, revoked_at

extension_installations
  id, extension_id, version_id, scope_type, scope_id,
  enabled, settings_json, installed_by, installed_at, removed_at

extension_draft_bindings
  id, draft_id, user_id, project_id, enabled, bound_at

skill_folders
  id, scope_type, scope_id, parent_folder_id, name,
  sort_order, is_system, archived_at, created_by, created_at

skill_folder_placements
  id, folder_id, skill_id, scope_type, scope_id,
  moved_by, moved_at

extension_permission_grants
  id, installation_id, capability, constraint_json, granted_by

mcp_secret_bindings
  id, installation_id, principal_type, principal_id, secret_ref

extension_reviews
  id, version_id, reviewer_id, decision, checks_json, decided_at

extension_audit_events
  id, actor_user_id, organization_id, action, target_type,
  target_id, before_ref, after_ref, request_id, created_at
```

SQLite와 PostgreSQL 양쪽에서 동작하도록 주요 ID는 UUID, 시간은 UTC를 사용합니다. package 본문은 Object Storage 또는 content-addressed storage에 두고 DB에는 digest와 위치를 저장합니다. 로컬 개발에서는 같은 Repository 계약 아래 `data/` 저장소로 대체할 수 있습니다.

## Backend 경계와 API 방향

- `CatalogService`: 조회, 검색, 공개 범위와 상태 필터
- `AuthoringService`: 대화 기반 WorkingDraft, revision, Fork와 명시 저장 시 새 immutable version 생성
- `InstallationService`: scope별 설치·활성·업데이트·해제
- `ReviewService`: 자동 검사, 승인, 게시, 폐기와 revoke
- `ExtensionResolver`: Session/Run에 적용할 정확한 version과 permission 계산
- `PackageStore`: package snapshot, digest와 안전한 파일 조회
- `SecretService`: MCP credential reference 연결

대표 명령은 다음처럼 자원과 version을 분리합니다.

```text
POST   /api/extensions
POST   /api/skill-drafts/from-conversation
PATCH  /api/skill-drafts/{draft_id}
POST   /api/skill-drafts/{draft_id}/activate
POST   /api/skill-drafts/{draft_id}/save-version
GET    /api/skill-folders?scope_type=&scope_id=
POST   /api/skill-folders
PATCH  /api/skill-folders/{folder_id}
POST   /api/skill-folders/{folder_id}/move
DELETE /api/skill-folders/{folder_id}
POST   /api/skills/{skill_id}/move-folder
POST   /api/extensions/{id}/versions
POST   /api/extensions/{id}/forks
POST   /api/extension-versions/{version_id}/review-requests
POST   /api/extension-versions/{version_id}/publish
POST   /api/extension-versions/{version_id}/public-requests
POST   /api/extension-installations
PATCH  /api/extension-installations/{id}
DELETE /api/extension-installations/{id}
```

파일명과 package 내부 경로는 allowlist와 canonical path 검사 후 처리하며 symlink와 path traversal을 거부합니다. API body의 `accountId`, owner와 organization은 권한 판단에 사용하지 않고 인증 context에서 가져옵니다.

## Frontend 정보 구조

```text
Marketplace
├─ 탐색
│  ├─ Skill / MCP / Plugin
│  ├─ 검색·필터·정렬
│  └─ 설명·tag·사용자 설치 수·실행 수·좋아요·설치 가능 상태
├─ Skill Folder Tree
│  ├─ 개인 / Project / Organization scope
│  ├─ breadcrumb / count / search
│  └─ drag-and-drop / 폴더로 이동
├─ 내 확장
│  ├─ 개인 설치
│  ├─ Project 설치
│  ├─ 작성한 Draft/Fork
│  ├─ 현재 Agent에 적용 중인 Draft와 revision
│  └─ 업데이트·폐기 경고
├─ 설치됨·소유 Skill 상세
│  ├─ 설명·버전·계보·변경 diff
│  ├─ 파일/manifest·권한·검증 결과
│  └─ 설치·Fork·새 버전 작성
└─ 관리
   ├─ 검토 Queue
   ├─ Marketplace permission mode: auto | admin_review
   ├─ Organization 정책
   └─ 감사·Revoked 영향 범위
```

카탈로그와 Skill 목록의 공용 lifecycle 버튼은 `Install → Installed`, 설치된 상태의 hover·focus에서는 `Delete`로 표시합니다. 모든 상태는 가장 긴 label 기준의 고정 width, 동일 height·padding·border·font와 고정 icon slot을 사용하고 loading은 icon만 spinner로 바꿔 layout shift나 press scale을 만들지 않습니다. 이 `Delete`는 현재 계정의 설치 연결 해제이며, 상세 화면의 한글 `삭제`는 Skill 보관함 이동으로 서로 다른 기존 action을 유지합니다.

WorkingDraft 상태는 Marketplace 안에서만 보이면 안 됩니다.

- `$` 자동완성 candidate와 Composer pill에 `Draft rN` badge를 표시합니다.
- 전송된 user Message의 Skill pill과 Run detail에는 실제 사용한 `Draft rN + digest` 또는 `vN`을 표시합니다.
- Harness가 Skill 생성·수정을 마치면 대화에 `Skill Draft` 결과 card를 남기고 현재 적용 상태, base version, 마지막 수정 시각과 `버전으로 저장` action을 제공합니다.
- 저장되지 않은 Draft가 활성화된 Session에는 Composer 근처에 compact indicator를 유지하되 매 Turn modal을 띄우지 않습니다.
- 명시 저장이 끝나면 indicator와 pill을 `vN`으로 갱신합니다. 이후 Draft가 다시 수정되면 `Draft · base vN` 상태를 즉시 복원합니다.
- 다른 기기에서 저장·수정된 상태는 Backend snapshot/event로 동기화하며 browser local state만으로 badge를 결정하지 않습니다.

## 기존 설계와의 연결

- Composer 호출과 Run snapshot은 `HERMES_USER_FEATURES.md`의 `$` Skill·MCP 계약을 따릅니다.
- Project별 파일·지침·기억·허용 확장 격리는 `COWORK_FEATURE_REQUIREMENTS.md`를 따릅니다.
- Plugin/MCP Tool 실행, 승인, 중단과 복구는 `AGENT_LOOP.md`를 따릅니다.
- 전용 Frontend를 포함한 Agent/Plugin package는 `PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md`의 교체 가능한 Frontend 계약과 연결합니다.
- 회사 CA, proxy와 MCP HTTP 연결은 `PGPT_CORPORATE_NETWORK.md`의 Trust Manager를 사용합니다.

## 단계별 구현 순서

### 1단계: Skill 중심 Marketplace

- DB 기반 카탈로그, Private/Project/Organization 조회 권한
- Harness 대화 기반 Skill WorkingDraft 생성·즉시 개인 실행
- Draft revision·digest snapshot과 명시 저장 시 immutable `v1 → v2`
- 사용자·Project 설치/해제와 Composer 노출
- Private 기본 공개 범위, admin 공용 게시와 개발용 Auto permission mode
- package digest, Run snapshot과 감사 로그

### 2단계: 검토와 조직 운영

- Reviewer Queue, Verified/Published/Deprecated/Revoked
- diff, 업데이트 선택, dependency와 영향 범위
- 조직 정책, Publisher 역할과 보존 lifecycle

### 3단계: MCP와 Plugin

- 승인된 MCP catalog, Secret binding, health와 Tool schema 검증
- Plugin manifest, sandbox 검사, 서명/digest와 compatibility
- 관리자 승인형 외부 package 등록

## 수용 기준

1. Harness 대화에서 Skill을 만들거나 수정하면 다음 Run은 최신 WorkingDraft revision을 실제로 사용하여 응답이 바뀝니다.
2. Draft가 수정되어도 이미 시작한 Run은 고정된 `draft_revision + digest`로 재현됩니다.
3. 첫 명시적 저장은 `v1`, 다음 저장은 `v2`를 만들고 기존 version 파일과 digest를 바꾸지 않습니다.
4. `v1`을 사용 중인 설치와 과거 Run은 `v2` 생성 이후에도 같은 결과를 재현할 수 있습니다.
5. 같은 Draft를 두 기기에서 동시에 편집해도 어느 한쪽이 조용히 덮어쓰지 않습니다.
6. 새 Skill은 기본 Private이고 소유자만 사용하며, 공용 공개는 admin 승인 또는 개발용 Auto permission policy를 통과해야 합니다.
7. 개인 설치·Draft와 credential은 다른 사용자에게 노출되지 않습니다.
8. Project 또는 Organization 설치는 권한 있는 사용자만 변경하며 모든 작업에 실제 actor가 기록됩니다.
9. 설치 해제는 다른 사용자 설치와 카탈로그 package를 삭제하지 않습니다.
10. 사용 중인 version을 폐기하거나 revoke해도 감사 snapshot은 유지되고 신규 Run 적용 여부가 정책대로 통제됩니다.
11. `$` 자동완성에는 현재 사용자의 활성 Draft와 현재 사용자·Project에서 설치되고 허용된 version만 나타납니다.
12. MCP Secret 값은 API 응답, manifest, 로그와 Run event에 나타나지 않습니다.
13. Plugin/MCP package는 permission policy와 검증 없이 Agent Worker에서 실행되지 않습니다.
14. 활성 WorkingDraft는 candidate·Composer·Message·Run detail에서 `Draft rN`으로 식별되고 명시 저장 action을 바로 실행할 수 있습니다.
15. 저장 후 `vN`, 후속 수정 후 `Draft · base vN`으로 상태가 여러 기기에서 일관되게 전환됩니다.
16. Skill과 Folder를 이동해도 Skill ID, Draft·version digest, installation과 과거 Run reference가 바뀌지 않습니다.
17. Folder cycle, 이름 충돌과 scope 밖 이동은 차단되고 Folder 삭제 시 포함 Skill은 사용자가 정한 destination 또는 `미분류`로 안전하게 이동합니다.
18. 같은 공용 Skill도 사용자마다 다른 개인 Folder에 배치할 수 있으며 다른 사용자의 Folder 구조를 변경하지 않습니다.
19. 카탈로그 응답에는 Skill package 파일 본문이 없고, 설치 권한이 없거나 설치하지 않은 일반 사용자는 version package API로 본문을 읽을 수 없습니다.
20. 카탈로그의 설치 수는 누적 다운로드가 아니라 현재 설치된 고유 사용자 수이며, 실행 수는 해당 Skill이 실제 적용된 시작 Run을 Run당 한 번만 집계합니다.
21. 카탈로그 검색·Category·tag 필터·정렬·pagination 중 설치와 해제를 연속 실행해도 검색 조건과 scroll context를 유지하며 카드별 pending 상태가 다른 카드 조작을 막지 않습니다.
