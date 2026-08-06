# Lumina 스킬 관리 및 진화 체계 설계안

> 문서 상태: 합의안 정리
> 작성일: 2026-07-12
> 핵심 원칙: **개인 작업은 자유롭게, 공식 변경은 통제하되 가볍게, 모든 공식 버전은 되돌릴 수 있게 관리한다.**

## 1. 목적

Lumina 사용자는 에이전트와 대화하면서 기존 스킬을 자신의 업무에 맞게 반복적으로 수정하고 테스트할 수 있다. 이때 개인의 수정이 다른 사용자에게 즉시 영향을 주면 공용 스킬의 신뢰성과 재현성이 훼손된다. 반대로 모든 변경에 복잡한 승인 절차를 요구하면 스킬 개선 속도가 지나치게 느려진다.

따라서 본 설계는 다음 목표를 동시에 달성한다.

1. 사용자가 에이전트와 자유롭게 스킬을 수정하고 시험할 수 있게 한다.
2. 개인 수정은 본인에게만 적용하여 타인의 작업을 보호한다.
3. 좋은 개선은 Marketplace를 통해 공식 스킬에 기여할 수 있게 한다.
4. Owner가 검토한 변경은 빠르게 반영하고, 문제가 생기면 즉시 원복한다.
5. 최초 작성자와 현재 관리 책임자를 분리하여 부서 이동·퇴사에도 자산이 유지되게 한다.
6. AI의 잦은 내부 수정은 공식 이력을 오염시키지 않으면서 필요한 복구 능력을 제공한다.

## 2. 한 문장으로 표현한 제품 개념

> **스킬을 개인 업무에 맞게 자유롭게 개선하고, 검증된 개선만 Owner가 공식 자산으로 승격시키는 사내 오픈소스형 Skill Marketplace**

사용 흐름은 다음과 같다.

```text
공식 스킬 사용
→ 개인 작업본에서 에이전트와 수정·테스트
→ 의미 있는 변경으로 Merge
→ 내가 Owner면 직접 Publish
→ 남의 스킬이면 Change Request 제출
→ Owner 승인 및 Publish
→ 문제 발생 시 이전 공식 버전으로 원복
```

## 3. 핵심 관리 원칙

### 3.1 개인 수정 격리

- 사용자가 대화 중 스킬을 수정하면 공용 원본이 아닌 **개인 작업본**에 반영한다.
- 다른 사용자는 계속 Marketplace의 공식 버전을 사용한다.
- 개인 작업본이 존재하면 해당 사용자에게는 개인 작업본을 우선 적용한다.
- 화면에 현재 실행 중인 버전이 공식본인지 개인 작업본인지 항상 표시한다.

### 3.2 공식 버전 불변

- 한 번 Publish된 공식 버전의 내용은 덮어쓰지 않는다.
- 수정은 항상 새로운 버전 생성으로 처리한다.
- 실행 중인 Run은 시작 당시 선택된 `skill_version_id`를 종료 시점까지 유지한다.
- 원복도 과거 버전 번호로 되돌아가는 것이 아니라, 과거 내용을 기반으로 새 공식 버전을 발행하는 방식으로 기록한다.

### 3.3 빠른 반영과 쉬운 원복

- 일반 스킬은 Owner 한 명의 판단으로 Publish할 수 있다.
- 남이 제출한 Change Request도 Owner 중 한 명의 승인으로 반영할 수 있다.
- 모든 스킬을 회사 전략급 자산처럼 무겁게 관리하지 않는다.
- 다만 외부 전송, 데이터 쓰기, 결재, 대외 발송 등 고위험 기능은 별도의 강화 정책을 적용할 수 있다.

### 3.4 작업 이력과 공식 이력 분리

- AI가 수정·실패·재수정한 세부 과정은 개인 작업 이력으로 관리한다.
- Marketplace의 공식 이력에는 의미 있게 정리된 Merge와 Publish를 중심으로 노출한다.
- 여러 자잘한 수정을 Merge할 때 하나의 변경으로 Squash한다.

## 4. 역할 및 소유권

### 4.1 역할 정의

| 역할 | 의미 | 주요 권한 |
|---|---|---|
| Creator | 최초 스킬을 만든 사람 | 영구 기여 기록, 관리 권한과는 분리 |
| Owner | 현재 스킬의 관리 책임자 | Merge 검토, Change Request 승인, Publish, 원복 |
| Maintainer | Owner가 지정한 운영 지원자 | 설정에 따라 리뷰·Merge·Publish 지원 |
| Contributor | 타인의 스킬에 개선을 제안한 사람 | 개인 Fork 수정, 테스트, Change Request 제출 |
| Admin | 조직 차원의 복구 담당 | 고아 스킬 인계, 긴급 비활성화, 소유권 복구 |

### 4.2 Creator와 Owner 분리

- `Creator`는 최초 작성 기록으로 변경하지 않는다.
- `Owner`는 현재 관리 책임이므로 변경·이전할 수 있다.
- 부서 이동, 퇴사, 조직 개편 시에도 Creator 기록은 유지한다.
- Owner는 개인뿐 아니라 팀이나 조직이 될 수 있다.
- 공식 조직 스킬은 조직을 Owner로 두고 담당자를 Owner 또는 Maintainer로 등록하는 방식이 안정적이다.

### 4.3 복수 Owner

- 하나의 스킬에 여러 Owner를 지정할 수 있다.
- 기본 정책은 **Owner 중 한 명이 승인하면 반영 가능**이다.
- Owner 본인이 수정한 스킬은 테스트 결과를 확인한 뒤 직접 Publish할 수 있다.
- 고위험 스킬만 선택적으로 복수 승인, 보안 승인 또는 데이터 Owner 승인을 요구한다.

### 4.4 소유권 이전

- Owner 변경 사유와 이전 전후 주체를 Audit Log에 남긴다.
- 퇴사 또는 계정 비활성화 시 개인 소유 스킬을 지정 조직이나 Admin에게 이전할 수 있다.
- 조직 폐지 시 상위 조직 또는 지정 후임 조직으로 일괄 이전한다.
- Creator 및 Contributor 기록은 소유권 이전과 무관하게 보존한다.

## 5. 개인 작업본과 공식 스킬

### 5.1 개인 작업본 생성

사용자가 공식 스킬과 대화하며 최초 수정 요청을 하면 자동으로 개인 작업본을 만든다.

```text
공식: report-skill v2.0.0
개인 작업본: user/report-skill v2.0.1
```

사용자는 Git이나 Fork 개념을 몰라도 된다. UI에서는 다음과 같이 표현한다.

- `내 버전으로 수정`
- `공식 버전과 다른 점 보기`
- `공식 스킬에 기여`
- `내 변경 폐기`

### 5.2 실행 버전 우선순위

권장 우선순위는 다음과 같다.

1. 대화나 Run에서 사용자가 명시한 버전
2. 해당 사용자의 개인 작업본
3. 프로젝트 또는 팀에서 고정한 버전
4. Marketplace 공식 버전

모든 Run에는 실제 선택된 버전 ID와 표시 버전을 함께 기록한다.

## 6. Lumina 버전 체계

Lumina의 스킬 버전은 `vPublish.Merge.Feedback` 형식을 사용한다.

```text
v2.7.25
 │ │ └─ 현재 Merge 이후 반영된 사용자 수정 피드백 수
 │ └─── 현재 Publish 세대에서 정리된 Merge 수
 └───── Marketplace 공식 Publish 세대
```

### 6.1 버전 상승 규칙

| 사건 | 변경 예시 | 설명 |
|---|---|---|
| 사용자 수정 요청이 실제 반영됨 | `v2.7.25 → v2.7.26` | Feedback/Revision 증가 |
| 여러 수정을 의미 있는 변경으로 Merge | `v2.7.26 → v2.8.0` | Merge 증가, Feedback 초기화 |
| Marketplace 공식 버전으로 Publish | `v2.8.0 → v3.0.0` | Publish 증가, 하위 숫자 초기화 |

### 6.2 마지막 숫자의 의미

마지막 숫자는 단순 대화 횟수가 아니라 **현재 Merge 이후 스킬에 실제 반영된 사용자 피드백 횟수**다.

- 질문만 한 경우: 증가하지 않음
- 테스트만 실행한 경우: 증가하지 않음
- 수정 요청이 있었지만 콘텐츠 변화가 없는 경우: 증가하지 않음
- 수정 후 기존 내용으로 완전히 원복된 경우: 증가하지 않음
- 수정 요청의 최종 결과가 실제 반영된 경우: `+1`
- 실패 상태를 사용자가 명시적으로 보존한 경우: `+1`

즉 `v2.7.25`만 보아도 공식 세대, 정리된 개선 횟수, 최근 Merge 이후의 실제 피드백 반영량이라는 세 가지 정보를 알 수 있다. 단, 숫자는 품질 점수가 아니라 변화 이력의 양을 나타낸다.

### 6.3 Revision 생성 시점

에이전트가 한 번의 답변을 만드는 동안 여러 차례 파일을 수정하고 테스트하더라도 버전은 한 번만 올린다.

```text
수정 요청 접수
→ 임시 작업공간에서 수정
→ 테스트 실패
→ 재수정
→ 테스트 성공
→ 에이전트 최종 답변
→ 최종 콘텐츠가 달라졌으면 Feedback +1
```

버전 생성 조건은 다음과 같다.

1. 수정 요청에 대한 에이전트 작업이 정상적으로 종료되었다.
2. 최종 콘텐츠가 기준 버전과 실제로 다르다.
3. 최종 상태를 일관된 Snapshot으로 저장할 수 있다.
4. 콘텐츠 해시가 이전 버전과 다르다.

### 6.4 원복 버전

공식 `v3.0.0`에 문제가 있어 `v2.0.0`의 내용으로 원복하더라도 공식 번호를 다시 `v2.0.0`으로 낮추지 않는다.

```text
현재 공식: v3.0.0
복원 대상: v2.0.0
새 공식:   v4.0.0
Release Note: v2.0.0 기반 긴급 복원
```

이를 통해 최신 공식 버전의 순서와 원복 행위를 모두 명확하게 보존한다.

## 7. Merge

### 7.1 Merge의 의미

Merge는 AI와 사용자가 여러 번 수정한 작업 이력을 의미 있는 변경 묶음 하나로 정리하는 행위다.

```text
v2.7.21 ~ v2.7.26의 자잘한 수정
→ 유효한 최종 변경만 Squash
→ v2.8.0 생성
```

Merge된 버전은 Publish 가능한 후보본이지만, Publish 전까지 Marketplace의 기본 공식 버전은 바뀌지 않는다.

### 7.2 Merge Comment

Merge할 때 사용자는 선택적으로 Comment를 남길 수 있다.

```text
Merge v2.8.0

변경 요약
- 파일 누락 검증 추가
- 최대 재시도 횟수를 2회로 제한
- 실패 메시지 개선

Comment
월간보고서 작성 과정에서 반복된 파일 누락 오류를 개선함.
```

- Diff는 무엇이 바뀌었는지를 설명한다.
- Comment는 왜 이 변경을 하나로 정리했는지를 설명한다.
- Comment를 입력하지 않으면 AI가 Diff와 테스트 결과를 바탕으로 초안을 제안할 수 있다.
- 사용자는 AI Comment를 그대로 사용하거나 수정하거나 생략할 수 있다.

### 7.3 Merge 방식

| 방식 | 용도 |
|---|---|
| Squash Merge | 기본값. 여러 Feedback 변경을 하나의 Merge로 정리 |
| Merge Selected | 선택한 변경만 반영하고 실험성 변경은 제외 |
| Rebase & Merge | 기준 공식 버전이 바뀌었을 때 최신 버전에 재적용 |
| Replace | 전체 구조 개편 시 새로운 후보본으로 교체 |

일반 사용자 UI에서는 Git 용어를 최소화하여 기본 버튼을 `변경사항 정리(Merge)`로 표시할 수 있다.

## 8. Marketplace 기여와 Publish

### 8.1 내가 Owner인 스킬

```text
개인 작업본 수정·테스트
→ Merge
→ 테스트 결과와 최종 Diff 확인
→ Owner 직접 Publish
→ 공식 Publish 버전 증가
```

Owner가 자신의 변경을 다시 승인하는 형식적 절차는 생략할 수 있다.

### 8.2 남이 Owner인 스킬

```text
공식 스킬에서 개인 작업본 생성
→ 에이전트와 수정·테스트
→ Merge
→ Change Request 제출
→ Owner 검토
→ 승인·일부 채택·수정 요청·거절
→ 승인 시 새 공식 버전 Publish
```

Change Request에는 다음 자료를 자동 첨부한다.

- 기준 공식 버전
- 제안 Merge 버전
- 최종 Diff
- 변경 목적 및 선택적 Comment
- 테스트 통과·실패 결과
- 품질·시간·비용의 전후 비교
- Tool, MCP, 외부 통신 및 데이터 권한 변화
- Contributor와 관련 Agent Run

### 8.3 Publish의 의미

- Marketplace의 공식 기본 버전을 새로운 세대로 전환한다.
- 기존 공식 버전은 불변 상태로 보존한다.
- 이미 실행 중인 Run에는 영향을 주지 않는다.
- 새 Run은 정책에 따라 최신 공식 버전 또는 고정된 이전 버전을 사용한다.
- Release Note를 생성하여 주요 변경과 원복 방법을 설명한다.

## 9. Diff 관리

### 9.1 지원할 비교 방식

- 직전 버전과 비교
- 현재 Marketplace 공식 버전과 비교
- 사용자가 선택한 임의의 두 버전 비교
- 개인 작업본과 최신 공식 버전 비교

### 9.2 구조적 Diff

텍스트 줄 단위 Diff 외에도 다음 변화를 별도 표시한다.

- 지침 추가·삭제·변경
- 스크립트 및 참조 파일 추가·삭제
- Tool 또는 MCP 추가·삭제
- 외부 통신 대상 변화
- 읽기·쓰기 권한 변화
- 평가셋과 테스트 기준 변화
- 종속 스킬 변화

예시:

```text
비교: v2.7.25 ↔ v2.8.0

SKILL.md          +14 / -6
scripts/run.py    +38 / -12
references/       +2 files / -1 file
Tool 권한         1개 추가
외부 도메인       변경 없음
테스트             7/8 → 8/8 통과
```

## 10. 저장 구조와 용량 최적화

AI가 수정할 때마다 모든 파일의 복사본을 저장하지 않는다. 사용자에게는 각 버전이 온전한 전체본으로 보이지만, 물리적으로는 변경된 콘텐츠만 저장한다.

### 10.1 Content-Addressed Storage

```text
v2.7.25
├─ SKILL.md       → hash_A
├─ scripts/run.py → hash_B
└─ refs/guide.md  → hash_C

v2.7.26
├─ SKILL.md       → hash_D   # 변경되어 신규 저장
├─ scripts/run.py → hash_B   # 기존 Blob 재사용
└─ refs/guide.md  → hash_C   # 기존 Blob 재사용
```

- 파일 콘텐츠의 해시를 Blob ID로 사용한다.
- 같은 내용은 한 번만 저장한다.
- 수정 후 원복하면 과거 Blob을 다시 참조한다.
- 각 버전은 전체 파일 목록을 표현하는 Tree와 부모 버전을 가진다.

### 10.2 Snapshot과 Diff

- 복원의 기준은 버전별 논리적 Snapshot/Tree다.
- Diff는 저장의 유일한 원본이 아니라 비교와 리뷰를 위한 표현이다.
- 원하는 두 버전의 Diff는 Tree와 Blob을 이용해 필요할 때 계산한다.
- 큰 파일은 필요할 때만 Chunk 단위 중복 제거를 적용한다.

### 10.3 보존 정책

| 구분 | 보존 원칙 |
|---|---|
| Agent Run 내부 체크포인트 | 작업 중 임시 보존, 최종 답변 후 정리 가능 |
| Feedback/Revision | 개인 복구를 위해 일정 기간 또는 최근 N개 보존 |
| Merge | 의미 있는 변경 이력으로 장기 보존 |
| Publish | 공식 자산으로 영구 보존 |
| 미참조 Blob | 유예기간 후 Garbage Collection |

## 11. 동시 수정과 충돌

모든 수정 작업은 시작 시점의 `base_version_id`를 기억한다.

```text
작업 A 기준: v2.7.25
작업 B 기준: v2.7.25
```

A가 먼저 완료되어 `v2.7.26`이 생성됐다고 해서 B의 결과를 곧바로 `v2.7.27`로 덮어쓰지 않는다.

- 변경 위치가 다르면 최신 작업본에 자동 Rebase하고 테스트한다.
- 같은 지침이나 파일을 동시에 바꾸면 충돌로 표시한다.
- 에이전트가 충돌 해결 후보와 근거를 제안한다.
- 충돌 해결 후 관련 테스트를 다시 실행한다.
- 해결 전까지 별도 Draft Branch로 보존한다.

Change Request 검토 중 제안 내용이 변경되면 기존 승인 상태를 무효화하거나 Owner에게 재검토를 요구한다.

## 12. 테스트 및 Skill Evolution 연계

스킬 관리는 단순한 문서 버전 관리가 아니라 개선 효과를 증명하는 체계와 연결되어야 한다.

### 12.1 버전별 테스트 결과

각 Merge 및 Publish 후보에 다음 정보를 연결한다.

- 평가셋 버전
- 테스트 통과율
- 품질 평가 점수
- 평균 실행 시간
- 토큰 또는 모델 비용
- Tool 오류 수
- 사용자 개입 횟수
- 안전 정책 위반 여부

### 12.2 동일 조건 비교

기준 버전과 후보 버전을 같은 입력, 파일, Tool 환경 및 모델 설정으로 실행한다. 품질만 향상되고 비용이나 권한 위험이 과도하게 증가하지 않았는지 함께 판단한다.

### 12.3 실패의 회귀 테스트 전환

운영 또는 개인 테스트에서 발견된 실패를 평가 케이스로 추가할 수 있다.

```text
실패한 Run
→ 개인정보 제거
→ 회귀 테스트로 추가
→ 다음 Merge 후보부터 자동 실행
```

## 13. 위험도 기반 예외 정책

기본값은 Owner 한 명의 빠른 Publish다. 다음과 같은 고위험 변화만 강화된 검증을 요구할 수 있다.

- 새로운 외부 MCP 서버 또는 외부 도메인 연결
- 데이터베이스·메일·파일 쓰기 권한 추가
- 개인정보·영업비밀 접근 범위 확대
- 대외 발송 또는 결재 실행
- 사용자 승인 단계 제거
- 조직 전체 기본 스킬 지정

강화 정책의 예시는 다음과 같다.

```text
일반 콘텐츠 변경       Owner 1명 또는 Owner 직접 Publish
업무 로직 변경          Owner 1명 + 필수 테스트 통과
권한·외부 연결 변경     Owner 1명 + 보안 검증
결재·대외 실행 변경     별도 조직 정책 적용
긴급 비활성화·원복      Owner 1명 또는 Admin 즉시 실행
```

## 14. 화면 구성 제안

### 14.1 스킬 상세 화면

```text
보고서 작성 스킬
공식 버전: v3.0.0
내 작업본: v3.2.7
Owner: 경영기획DX팀 외 2명

[실행] [내 버전 수정] [공식 버전과 비교]
[변경사항 정리(Merge)] [공식 스킬에 기여]
```

### 14.2 버전 화면

```text
v3.2.7
공식 3세대 · Merge 2회 · 최근 피드백 7건 반영

기준 공식 버전과 차이
- 지침 3개 변경
- 스크립트 1개 변경
- 권한 변경 없음
- 테스트 12/12 통과
```

### 14.3 Marketplace 이력

기본 화면에는 Publish와 Merge를 중심으로 표시하고, 세부 Feedback은 접어서 제공한다.

```text
v4.0.0  공식 발행 · 파일 검증 개선
└─ v3.2.0  오류 처리 정리
   └─ Feedback 7건 보기
```

### 14.4 최종 답변 표시

에이전트가 스킬 수정 요청을 완료하면 결과와 버전을 함께 보여준다.

```text
스킬 수정과 테스트를 완료했습니다.

v3.2.6 → v3.2.7
변경: 파일 누락 처리와 재시도 제한 추가
테스트: 8/8 통과
현재 변경은 내 작업본에만 적용됩니다.
```

## 15. 권장 데이터 모델

```text
Skill
- id
- name
- creator_user_id
- official_version_id
- risk_level
- status

SkillOwnership
- skill_id
- principal_type: user | team
- principal_id
- role: owner | maintainer
- created_at
- created_by

SkillVersion
- id
- skill_id
- display_version
- publish_number
- merge_number
- feedback_number
- parent_version_id
- base_version_id
- root_tree_hash
- owner_scope: official | user | team
- owner_principal_id
- change_type: feedback | merge | publish | rollback
- created_by_user_id
- created_by_agent_run_id
- comment
- content_hash
- created_at

SkillChangeRequest
- id
- skill_id
- base_official_version_id
- proposed_version_id
- proposer_id
- status: open | changes_requested | approved | rejected | merged
- test_summary
- permission_diff
- reviewed_by
- reviewed_at

SkillBlob
- content_hash
- storage_key
- size
- reference_count

SkillVersionTree
- version_id
- path
- blob_hash
- mode

SkillVersionTestResult
- version_id
- evaluation_suite_version_id
- pass_count
- fail_count
- quality_score
- duration
- cost
- result_artifact_id
```

버전 표시 문자열은 계산 결과로 생성하고, 비교와 정렬에는 세 개의 정수 필드를 사용한다.

## 16. MVP 우선순위

### P0 — 기본 안전성

- 개인 작업본과 공식본의 완전한 격리
- Run 시작 시 `skill_version_id` 고정
- Creator와 Owner 필드 분리
- 복수 Owner 지원
- 공식 Publish 버전 불변 보존
- 원클릭 원복

### P1 — 버전 및 Merge

- `vPublish.Merge.Feedback` 버전 규칙
- 수정 요청 완료 시 Feedback 번호 증가
- 버전 단위 Snapshot과 Diff
- Squash Merge
- 선택적 Merge Comment
- 공식본과 개인 작업본 비교

### P2 — Marketplace 기여

- Change Request 제출
- Owner 한 명의 승인·일부 채택·수정 요청·거절
- Owner 직접 Publish
- Release Note 및 Contributor 기록
- 공식 버전 변경 알림

### P3 — 저장 및 동시성

- 콘텐츠 해시 기반 Blob 중복 제거
- Tree 기반 논리적 Snapshot
- Revision 보존 정책과 Garbage Collection
- `base_version_id` 기반 충돌 탐지
- 자동 Rebase 및 충돌 해결 지원

### P4 — Skill Evolution

- 버전별 자동 평가셋 실행
- 기준/후보 A/B 비교
- 실패 원인 자동 분류
- 실패 Run의 회귀 테스트 전환
- 품질·비용·시간·안전성 변화 시각화
- AI 변경 요약과 Merge Comment 자동 제안

## 17. 운영 원칙 요약

1. **대화 중 수정은 개인에게만 영향을 준다.**
2. **수정 요청 한 건이 실제 반영될 때 마지막 버전 숫자가 한 번 증가한다.**
3. **자잘한 수정은 Merge할 때 하나의 의미 있는 변경으로 정리한다.**
4. **Merge Comment는 선택 사항이며 AI가 초안을 제안할 수 있다.**
5. **내 스킬은 직접 Publish하고, 남의 스킬은 Change Request로 기여한다.**
6. **Owner는 여러 명일 수 있으며 기본적으로 한 명의 승인으로 충분하다.**
7. **Creator는 영구 기록하고 Owner는 조직 변화에 따라 이전한다.**
8. **공식 버전은 불변이며 문제 발생 시 새 버전으로 원복한다.**
9. **물리 저장은 변경된 Blob만 저장하여 AI의 반복 수정을 감당한다.**
10. **모든 Run은 시작 당시 버전에 고정하여 재현성을 보장한다.**

## 18. 결론

이 관리 체계는 Git의 Fork·Diff·Merge·Pull Request·불변 버전 개념을 차용하지만, 일반 사용자가 Git을 몰라도 에이전트와 대화만으로 사용할 수 있도록 단순화한다.

Lumina의 차별점은 스킬을 단순히 등록하고 다운로드하는 Marketplace가 아니라, 사용자의 실제 업무 피드백이 개인 작업본에 축적되고, 의미 있는 개선이 조직의 공식 자산으로 다시 환류되는 구조에 있다.

> **작업 과정은 자유롭게, 공식 이력은 의미 있게, 반영은 빠르게, 문제는 쉽게 되돌린다.**
