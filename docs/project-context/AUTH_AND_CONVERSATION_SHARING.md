> 생성일: 2026-07-12

# 사용자 인증, 관리자와 대화 공유 링크 설계

## 목적

Lumina Agent의 사용자를 ID와 비밀번호로 식별하고, 각 사용자의 채팅 기록을 기본적으로 격리합니다. assistant 답변 하단의 공유 링크로 다른 사용자가 특정 대화를 볼 수 있게 하되, 링크를 받은 사용자가 원소유자의 다른 채팅 history까지 탐색할 수 없게 합니다.

관리자 계정은 사용자 관리와 운영·감사를 위해 전체 사용자와 대화를 조회할 수 있습니다. 관리자 권한은 일반 공유 링크와 분리하며 모든 관리자 조회·변경을 감사 기록에 남깁니다.

## 핵심 불변 조건

1. 일반 사용자는 로그인한 `user_id`가 소유하거나 명시적으로 공유받은 데이터만 조회합니다.
2. 대화 공유 권한은 해당 `conversation_id` 또는 더 좁은 message snapshot에만 적용되며 소유자의 사용자 공간으로 확장되지 않습니다.
3. 공유 링크를 열어도 원소유자의 채팅 목록, 검색 결과, 최근 대화, Project 목록과 이전·다음 대화가 노출되지 않습니다.
4. URL의 `user_id`, `conversation_id`, `project_id`와 role은 권한의 근거가 아닙니다. 공유 viewer는 불투명 token의 hash와 DB grant를 기준으로 판단합니다.
5. 관리자는 전체 데이터를 볼 수 있지만 관리자 권한 사용은 최소화하고 조회·변경 대상과 사유를 감사 기록에 남깁니다.
6. 비밀번호 원문은 DB, 로그, Run event, URL과 공유 링크에 저장하지 않습니다.

## 인증 모델

### 사용자 계정

초기 인증 방식은 관리자가 사용자에게 ID와 초기 비밀번호를 발급하는 방식입니다.

```text
User
├─ user_id                 # 서버 발급 UUID, 내부 식별자
├─ login_name              # @ 앞의 사용자 ID
├─ login_domain            # @ 뒤의 주소, 기본 posco.com
├─ login_id                # 정규화된 login_name@login_domain, 고유값
├─ display_name            # 선택 표시 이름
├─ affiliation             # 선택 소속, 사용자 계정 전역 값
├─ password_hash
├─ role: user | admin
├─ status: invited | active | locked | disabled
├─ must_change_password
├─ failed_login_count
├─ last_login_at
├─ created_by / created_at
└─ updated_at
```

- 로그인 화면은 `login_name`과 `login_domain`을 별도 입력값으로 받고 Backend에서 `login_name@login_domain` 형태의 `login_id`로 정규화합니다.
- `login_id`는 대소문자와 Unicode 정규화 정책을 정해 고유성을 검사합니다. 화면에서 분리해 입력하더라도 Backend는 두 값을 함께 검증합니다.
- 소유권과 외래키에는 변경 가능한 `login_id`가 아니라 `user_id`를 사용합니다.
- 비밀번호는 Argon2id 또는 현재 조직 보안 기준에 맞는 강한 단방향 hash로 저장합니다.
- 일반 사용자에게 발급한 초기 비밀번호의 변경 강제 여부는 관리자 정책으로 정합니다. 초기 개발 단계에서는 변경을 강제하지 않을 수 있습니다.
- 로그인 실패 횟수 제한, 지연 또는 일시 잠금과 관리자 잠금 해제를 지원합니다.
- 인증 성공 후에는 `HttpOnly`, `Secure`, 적절한 `SameSite` 속성의 서버 세션 cookie를 기본으로 사용합니다. 상태 변경 요청에는 CSRF 방어를 적용합니다.
- 비밀번호 변경·초기화 시 기존 세션을 폐기할 수 있어야 합니다.
- 계정 비활성화 즉시 신규 로그인, API 호출과 공유 grant 사용을 차단합니다.

### 최초 접속과 로그인 화면

인증되지 않은 사용자가 Lumina 기본 URL 또는 대화 공유 링크에 처음 접속하면 로그인 화면을 표시합니다. 로그인 후에도 공유 URL을 유지해 자신의 sidebar와 함께 읽기 전용 viewer를 엽니다.

로그인 form은 다음 순서와 기본값을 사용합니다.

```text
아이디        [ login_name 입력 ]
주소          [ posco.com       ]   # 별도 입력값
비밀번호      [ password         ]
로그인
```

- 화면에는 `아이디 @ 주소` 관계가 명확하게 보이도록 표시하되 `login_name`과 `login_domain`을 별도 form control로 유지합니다.
- 주소의 기본값은 `posco.com`입니다. 사용자가 다른 허용 주소를 써야 할 때 별도로 변경할 수 있습니다.
- 초기 focus는 아이디 입력란에 둡니다.
- 아이디 입력란에서 `Tab`을 누르면 주소 입력란을 건너뛰고 즉시 비밀번호 입력란으로 이동합니다.
- 이 keyboard 순서를 위해 주소 입력란을 완전히 접근 불가능하게 만들지 않습니다. 주소 옆 `주소 변경` 동작은 비밀번호 다음 tab stop으로 제공하고, 실행하면 주소 입력란을 활성화해 focus를 이동합니다. 주소를 바꾼 뒤에는 비밀번호로 돌아갈 수 있습니다.
- 비밀번호 입력란에서는 Enter로 form을 제출할 수 있습니다.
- 로그인 실패 시 비밀번호만 지우고 아이디와 주소는 유지합니다. 계정 존재 여부를 드러내지 않는 동일한 오류 문구를 사용합니다.
- 공유 링크 token은 브라우저 저장소나 일반 로그에 복제하지 않고 URL에서만 전달합니다.

### 당일 로그인 유지

로그인에 성공하면 같은 브라우저에서는 **Asia/Seoul 기준 다음 자정까지** 다시 ID와 비밀번호를 묻지 않습니다.

- Backend server session의 절대 만료 시각을 로그인 시점 다음 한국 시간 자정으로 계산합니다. 단순히 브라우저 `localStorage`에 로그인 여부를 저장하지 않습니다.
- session cookie는 `HttpOnly`, `Secure`, 적절한 `SameSite` 속성을 사용하고 cookie 만료도 server session보다 길지 않게 합니다.
- 새 날짜가 되면 다음 요청에서 session을 만료시키고 로그인 화면으로 보냅니다.
- 로그아웃, 비밀번호 변경·reset, 계정 잠금·비활성화와 관리자의 session 폐기는 자정 전이라도 즉시 로그인을 해제합니다.
- 브라우저를 닫았다 다시 열어도 cookie와 server session이 유효하면 당일에는 다시 묻지 않습니다.
- 공유 PC 사용자를 위해 항상 보이는 로그아웃 기능을 제공합니다.

### Bootstrap 관리자

최초 설치에는 최소 한 개의 관리자 계정이 필요합니다.

- 최초 설치 시 실제 관리자 계정을 `admin@posco.com`으로 생성하고 비밀번호는 `1`로 설정합니다.
- 이 계정은 `role=admin`, `status=active`, `must_change_password=false`로 생성합니다.
- `admin@posco.com / 1`로 로그인하면 비밀번호 변경 절차 없이 사용자 관리, 전체 대화·Run·Artifact 조회와 공유 관리 등 모든 관리자 기능을 즉시 사용할 수 있습니다.
- 비밀번호 원문 `1`을 DB에 그대로 저장하지 않고 설치·DB 초기화 시 hash로 저장하되, 사용자가 직접 변경하기 전까지 `1`로 계속 로그인할 수 있게 합니다.
- 기존 DB에 `admin@posco.com` 계정이 없을 때만 생성합니다. 계정이 이미 있으면 서버 시작 시 다시 만들거나 현재 비밀번호를 `1`로 덮어쓰지 않습니다.
- 초기 개발 단계에서는 편의성을 위해 이 기본 계정을 사용합니다. 향후 운영 보안 정책은 별도 요구사항으로 추가하며 현재 동작을 자동으로 바꾸지 않습니다.
- 마지막 활성 관리자 계정은 대체 관리자 없이 비활성화하거나 일반 사용자로 강등하지 못하게 합니다.
- 운영 환경에서는 향후 사내 SSO를 추가할 수 있지만, 계정의 내부 `user_id`와 role·소유권 계약은 유지합니다.

## 역할과 권한

### 일반 사용자

일반 사용자는 다음 데이터만 조회·변경할 수 있습니다.

- 자신이 소유한 Project, Session, Conversation, Message, Run, 첨부와 Artifact
- 자신이 구성원인 공유 Project의 허용된 데이터
- 자신에게 명시적으로 부여된 conversation share grant의 대상

다른 사용자의 ID를 알거나 URL을 추측하는 것만으로는 어떤 데이터도 조회할 수 없습니다.

### 관리자

관리자는 운영상 다음 기능을 사용할 수 있습니다.

- 사용자 생성, 조회, 잠금, 비활성화와 role 변경
- 초기 비밀번호 발급 또는 비밀번호 reset link·임시 비밀번호 생성
- 전체 사용자의 대화·Run·Artifact 조회
- 공유 link·grant 조회와 강제 취소
- 사용자별 저장량, 사용량, 최근 로그인과 계정 상태 확인
- 보안·운영 감사 기록 조회

관리자라도 다음 원칙을 지킵니다.

- 사용자 비밀번호 원문, Provider Secret과 Connector token은 볼 수 없습니다.
- 일반 사용자로 가장하는 기능은 초기 범위에서 제공하지 않습니다. 필요해도 별도 승인·표시·감사 계약을 거칩니다.
- 관리자 대화 조회에는 관리자 ID, 대상 사용자, 대상 conversation과 시각을 기록합니다.
- 삭제·role 변경·비밀번호 reset·share 취소 같은 변경에는 action과 결과를 기록합니다.
- 관리자 UI와 API는 `role=admin`을 Backend에서 다시 검사하며 Frontend route 숨김만으로 보호하지 않습니다.

## 대화 소유권과 기본 격리

모든 대화와 관련 객체에는 소유권을 기록합니다.

```text
Conversation
├─ conversation_id
├─ owner_user_id
├─ organization_id optional
├─ project_id optional
├─ visibility: private | project_shared
└─ created_at

Message / Run / Attachment / Artifact
└─ conversation_id 또는 소유 객체를 통해 owner와 scope 결정
```

- 새 대화의 기본값은 `private`입니다.
- 일반 사용자의 채팅 목록과 검색은 항상 `owner_user_id = current_user_id` 또는 자신에게 허용된 별도 공유 scope로 제한합니다.
- 공유받은 대화는 개인 history와 섞지 않고 `나에게 공유됨` 영역에 표시할 수 있습니다.
- 공유받은 대화를 열었더라도 소유자의 프로필, 전체 Project tree와 다른 대화 수 같은 주변 metadata를 노출하지 않습니다.

## 사용자 ID별 채팅 기록과 동기화

채팅 기록의 원본은 브라우저가 아니라 Backend DB와 Artifact storage입니다. 로그인할 때 입력한 `login_name@login_domain`은 인증에 사용하고, 인증 후 발급된 불변 `user_id`를 모든 사용자 데이터의 소유권과 동기화 기준으로 사용합니다.

사용자별로 다음 데이터를 분리해 저장합니다.

```text
UserWorkspace
├─ user_id
├─ Projects and memberships
├─ Conversations / Sessions
│  ├─ Messages
│  ├─ AgentRuns / Plans / ToolCalls
│  ├─ queued messages and approvals
│  ├─ Attachments
│  └─ Artifacts and versions
├─ personal AGENTS.md and memories
├─ Provider / Model / Effort last selections
├─ enabled Skills / MCP preferences
├─ notifications and unread state
└─ non-sensitive UI preferences
```

### 동기화 원칙

- 같은 사용자가 같은 ID로 다른 PC·브라우저에서 로그인하면 서버 DB에서 동일한 채팅 목록, 메시지, Run 상태, Artifact와 사용자 설정을 불러옵니다.
- 한 기기에서 새 채팅을 만들거나 메시지·제목·즐겨찾기·삭제 상태를 변경하면 Backend에 먼저 저장하고 연결된 같은 사용자의 다른 기기에 event 또는 다음 조회로 반영합니다.
- 실행 중인 Run은 브라우저나 기기에 귀속하지 않습니다. 사용자가 다른 기기에서 같은 채팅을 열면 Backend snapshot과 sequence event replay로 현재 답변, Plan, Tool 진행과 경과 시간을 복원합니다.
- sidebar의 최근 채팅, 검색, 정렬과 pagination은 항상 현재 인증 principal의 `user_id`로 필터합니다.
- 브라우저 `localStorage`에는 채팅 원문, 소유권과 인증 상태를 원본으로 저장하지 않습니다. 일시적인 panel 폭, draft와 화면 cache만 둘 수 있으며 서버 데이터와 충돌하면 서버가 원본입니다.
- 로그인 ID가 달라지면 같은 브라우저라도 이전 사용자의 cache를 비우거나 사용자별 namespace로 격리하고, 이전 사용자의 채팅 제목·검색어·draft·알림이 잠깐이라도 표시되지 않게 합니다.
- 로그아웃 시 메모리에 남은 메시지, Run snapshot, Artifact URL과 사용자별 cache를 제거합니다.
- 공유받은 대화는 소유 대화와 별도 scope로 조회하며, 공유 grant가 개인 채팅 목록 전체에 대한 동기화 권한이 되지 않습니다.

### 사용자 변경과 삭제

- `login_name` 또는 `login_domain`이 변경되어도 내부 `user_id`는 유지하므로 기존 채팅과 Artifact 연결이 끊기지 않습니다.
- 계정 비활성화는 데이터를 다른 사용자에게 이전하지 않으며 해당 `user_id`의 로그인을 차단합니다.
- 관리자가 데이터를 다른 사용자에게 이전해야 할 때는 명시적 이전 작업, 대상 확인과 감사 기록을 사용합니다. 단순히 login ID 문자열을 바꾸어 소유권을 이전하지 않습니다.
- 사용자 삭제와 보관은 Conversation·Run·Attachment·Artifact의 연관 관계와 공유 grant를 함께 처리하는 별도 보존 정책을 따릅니다.

## assistant 답변 하단의 대화 공유 링크

### 사용자 흐름

assistant 답변이 완료되면 하단 action bar에 `대화 링크 공유`를 표시합니다.

1. 소유자가 버튼을 누릅니다.
2. Backend가 현재 답변까지 고정한 `ConversationShareGrant`와 불투명한 링크 token을 생성합니다.
3. Frontend가 링크를 즉시 clipboard에 복사하고 완료 toast를 표시합니다.
4. 링크를 받은 사람은 자신의 Lumina 계정으로 접속해 기존 sidebar를 유지한 채 공유된 대화만 읽습니다.

공유 URL에는 생성자가 현재 사용 중인 `light` 또는 `dark` theme를 포함하고, 공유 viewer는 이를 적용합니다. 대화 본문의 typography는 일반 채팅 화면과 같은 크기와 행간을 사용합니다.
로그인한 사용자가 링크를 열면 자신의 왼쪽 sidebar와 navigation은 유지하고 중앙 영역만 공유 viewer로 전환합니다. 공유 대화는 열람자의 history에 추가하거나 현재 session 선택을 변경하지 않습니다.

기본 공유 단위는 선택한 답변이 포함된 **현재 대화 전체의 읽기 전용 snapshot**입니다. 링크는 선택한 assistant `message_id` 위치로 이동합니다. 더 좁은 답변 한 개 공유가 필요하면 별도의 `message_snapshot` scope로 확장할 수 있지만, 링크를 통해 live 대화의 일부를 임의 조합하지 않습니다.

### 공유 데이터 모델

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
├─ expires_at optional
├─ revoked_at optional
├─ created_by / created_at
└─ last_accessed_at
```

- 원본 token은 링크 생성 시 한 번만 반환하고 DB에는 hash를 저장합니다.
- 기본 공유에서는 충분히 긴 원본 token을 가진 사람이 내용을 볼 수 있습니다. DB에는 token hash만 저장합니다.
- 링크를 전달하면 접근 권한도 함께 전달되므로 사용자는 민감한 대화 링크를 공개 채널에 게시하지 않아야 합니다.
- snapshot은 공유 생성 시점의 `snapshot_through_message_id`까지만 보여줍니다. 이후 대화를 자동 노출하지 않습니다.
- 소유자가 `앞으로 추가되는 메시지도 공유`를 별도로 선택한 경우에만 live conversation grant를 확장할 수 있으며 기본값으로 사용하지 않습니다.
- 링크 열람자는 공유 대화를 수정하거나 Run을 시작하고, steer·승인·취소하거나 Artifact를 덮어쓸 수 없습니다.
- 공유 취소, 만료 또는 원본 대화 삭제 시 즉시 접근을 거부합니다.

### History 유출 방지

공유 화면은 일반 소유자 대화 화면과 같은 데이터를 무조건 재사용하지 않습니다.

- 공유 viewer API는 grant의 `conversation_id`와 snapshot 범위만 반환합니다.
- 소유자의 sidebar history, 최근 대화, 검색 suggestion, Project navigation과 알림을 조회하지 않습니다.
- `previous_conversation_id`, `next_conversation_id`, 전체 대화 count와 소유자 기준 pagination cursor를 응답에 넣지 않습니다.
- 첨부와 Artifact는 공유 snapshot에 명시적으로 포함되고 안전한 항목만 조회합니다. 다른 대화의 Artifact deep link는 거부합니다.
- 공유된 메시지 안의 내부 링크가 다른 private conversation이나 Artifact를 가리키면 권한 없는 placeholder로 표시합니다.
- HTML preview, image URL과 다운로드 endpoint도 동일한 share grant와 snapshot 범위를 다시 검사합니다.
- 캐시 key에는 인증 사용자와 share scope를 포함하고 private 응답을 공용 cache에 저장하지 않습니다.
- 오류 응답은 `존재하지 않음`과 `권한 없음`을 구분해 다른 conversation의 존재 여부를 추측하게 하지 않습니다.

### 링크 화면 표시

공유 viewer에는 다음을 명확히 표시합니다.

- 읽기 전용으로 공유된 대화라는 사실
- 대화 소유자의 표시 이름 또는 조직 정책상 허용된 식별 정보
- 공유 기준 시각과 snapshot 범위
- 만료 여부
- 자신의 전체 채팅으로 돌아가는 동작

원소유자의 다른 채팅으로 이동하는 UI는 제공하지 않습니다.

## 관리자 사용자 관리 화면

관리자 UI는 최소한 다음 화면을 가집니다.

### 사용자 목록

- login ID, 표시 이름, 소속, role, 상태, 생성 시각과 마지막 로그인
- ID·상태·role 검색 및 필터
- 사용자 생성
- 계정 잠금·잠금 해제·비활성화
- 비밀번호 reset
- role 변경

### 사용자 상세

- 계정 상태와 변경 이력
- 소유 Project·대화·Run·Artifact와 사용량
- 생성하거나 받은 활성 공유 grant
- 최근 보안 이벤트와 관리자 조치

### 전체 대화 조회

- 사용자, 기간, Project, 상태와 공유 여부로 검색
- 대화 내용과 관련 Run·Artifact 조회
- 해당 조회가 관리자 감사 로그에 남는다는 지속적 표시
- 공유 grant 강제 취소와 정책 위반 데이터의 격리·보존 처리

초기 삭제는 hard delete보다 비활성화·보존 정책을 우선하며, 실제 삭제는 사용자 데이터 삭제 정책과 감사 요구사항을 따릅니다.

## Backend 권한 검사

모든 endpoint는 인증 principal을 먼저 확정한 뒤 다음 순서로 검사합니다.

```text
1. 유효한 로그인 session 확인
2. 계정 active 상태 확인
3. admin role이면 관리자 policy와 audit 적용
4. 일반 사용자면 직접 소유권 검사
5. 직접 소유하지 않으면 Project membership 검사
6. 그래도 없으면 정확한 ConversationShareGrant 검사
7. 대상 message·attachment·artifact가 grant snapshot 범위인지 검사
8. 허용된 필드만 response DTO로 반환
```

Frontend가 전달한 `owner_user_id`, `recipient_user_id`, role과 scope는 신뢰하지 않습니다.

## 감사 기록

최소 다음 이벤트를 저장합니다.

```text
user_created
user_locked / user_unlocked / user_disabled
password_reset_issued
role_changed
login_succeeded / login_failed
conversation_share_created / opened / revoked / expired
admin_user_viewed
admin_conversation_viewed
admin_share_revoked
```

감사 로그에는 actor, 대상, action, 결과, 시각과 request ID를 기록하되 비밀번호, session cookie, share token 원문과 대화 원문 전체는 넣지 않습니다.

## 수용 기준

1. 사용자 A와 B가 각각 로그인하면 서로의 채팅 목록·검색·직접 URL에 접근할 수 없습니다.
2. 사용자 A가 공유 버튼을 누르면 링크가 즉시 복사되고, B는 로그인 후 자신의 sidebar와 함께 해당 snapshot과 anchor 답변을 정상적으로 엽니다.
3. B가 공유 viewer에서 A의 sidebar history, 다른 conversation ID, Project 목록과 다른 Artifact를 얻을 수 없습니다.
4. 링크 token을 모르는 사용자는 conversation ID나 사용자 ID만으로 공유 내용을 열 수 없습니다.
5. 공유 후 A가 만든 새 메시지는 기본 snapshot 링크에 나타나지 않습니다.
6. A가 grant를 취소하면 이미 열려 있던 B의 다음 조회·다운로드도 거부됩니다.
7. URL의 user ID, conversation ID, role을 변조해도 권한이 확대되지 않습니다.
8. 일반 사용자는 관리자 API와 화면에 접근할 수 없습니다.
9. 관리자는 모든 사용자의 대화를 조회할 수 있고 각 조회가 감사 로그에 남습니다.
10. 관리자도 비밀번호 원문, Connector token과 Provider Secret은 조회할 수 없습니다.
11. 사용자 비활성화 후 기존 session과 해당 사용자의 share 접근이 차단됩니다.
12. 로그인, 공유 viewer, 관리자 전체 조회와 Artifact 다운로드를 실제 브라우저 E2E로 검증합니다.
13. 공유 링크는 인증되지 않았을 때 로그인 화면을 표시하고, 로그인 후 같은 URL에서 사용자의 sidebar와 읽기 전용 viewer를 함께 표시합니다.
14. 아이디 입력란에서 `Tab`을 누르면 비밀번호로 focus가 이동하며, 주소는 별도 control과 기본값 `posco.com`을 유지합니다.
15. `admin@posco.com`과 비밀번호 `1`로 로그인하면 비밀번호 변경 없이 전체 관리자 기능을 즉시 사용할 수 있습니다.
16. 로그인 session은 Asia/Seoul 기준 같은 날에는 유지되고 다음 자정, 로그아웃, 비밀번호 변경 또는 계정 비활성화 시 만료됩니다.
17. 같은 ID로 두 브라우저에 로그인하면 동일한 채팅 목록과 메시지가 보이고, 한쪽에서 만든 채팅과 진행 중 Run이 다른 쪽에서 snapshot·event replay로 복원됩니다.
18. 같은 브라우저에서 다른 ID로 다시 로그인하면 이전 사용자의 채팅 제목, 검색, draft, 메시지와 Artifact가 표시되지 않습니다.
19. 모든 채팅 목록·검색·직접 조회 API는 현재 인증 principal의 `user_id` 또는 정확한 share grant를 기준으로 필터합니다.

## 구현 우선순위

### P0

1. User·server session·role 데이터 모델
2. ID/PW 로그인과 비밀번호 hash·초기 변경
3. 모든 대화 API의 소유권 필터
4. Bootstrap 관리자와 사용자 생성·비활성화
5. 관리자 전체 대화 조회와 감사 기록

### P1

6. 링크 기반 `ConversationShareGrant`
7. 공유 전용 read-only viewer와 history 비노출 DTO
8. 공유 취소·만료와 Artifact 범위 검사
9. 관리자 사용자 관리 UI

### P2

10. 조직 SSO 연동
11. Project 역할과 delegated admin
12. 선택적 message-only snapshot과 조직 정책형 외부 공유
