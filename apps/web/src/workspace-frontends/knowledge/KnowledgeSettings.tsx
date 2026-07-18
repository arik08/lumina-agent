import { Archive, Check, Coins, Database, LoaderCircle, LockKeyhole, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api } from "../../api";
import type { KnowledgeIngestionJob, KnowledgeSpace } from "../../api-types";
import { formatDate } from "./knowledge-utils";

interface KnowledgeSettingsProps {
  space: KnowledgeSpace;
  ingestions: KnowledgeIngestionJob[];
  onUpdated: (space: KnowledgeSpace) => void;
  onArchived: (spaceId: string) => void;
  onError: (error: unknown) => void;
}

export function KnowledgeSettings({ space, ingestions, onUpdated, onArchived, onError }: KnowledgeSettingsProps) {
  const [name, setName] = useState(space.name);
  const [purpose, setPurpose] = useState(space.purpose);
  const [description, setDescription] = useState(space.description);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const usage = useMemo(() => ingestions.reduce((total, job) => ({ input: total.input + job.inputTokens, output: total.output + job.outputTokens, characters: total.characters + job.inputCharacterCount }), { input: 0, output: 0, characters: 0 }), [ingestions]);
  const latestJob = ingestions[0];
  const dirty = name.trim() !== space.name || purpose.trim() !== space.purpose || description.trim() !== space.description;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !dirty || saving) return;
    setSaving(true);
    setSaved(false);
    try {
      const updated = await api.knowledge.updateSpace(space.id, {
        expectedRevision: space.settingsRevision,
        name: name.trim(),
        purpose: purpose.trim(),
        description: description.trim(),
      });
      onUpdated(updated);
      setSaved(true);
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  async function archive() {
    if (!confirmArchive || saving) return;
    setSaving(true);
    try {
      await api.knowledge.archiveSpace(space.id, space.settingsRevision);
      onArchived(space.id);
    } catch (error) {
      onError(error);
      setConfirmArchive(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="knowledge-page knowledge-settings-page">
      <div className="knowledge-settings-column">
        <section className="knowledge-card knowledge-settings-card">
          <header><div><strong>공간 정보</strong><small>이름과 설명은 보이는 자리에서 바로 관리합니다.</small></div><span>revision {space.settingsRevision}</span></header>
          <form onSubmit={save}>
            <label>공간 이름<input value={name} maxLength={240} onChange={(event) => { setName(event.target.value); setSaved(false); }} /></label>
            <label>목적<textarea value={purpose} rows={3} maxLength={20_000} placeholder="이 공간이 다루는 지식의 범위와 용도" onChange={(event) => { setPurpose(event.target.value); setSaved(false); }} /></label>
            <label>설명<textarea value={description} rows={3} maxLength={10_000} placeholder="사용자가 알아야 할 보충 설명" onChange={(event) => { setDescription(event.target.value); setSaved(false); }} /></label>
            <footer>{saved && <span><Check size={13} /> 저장됨</span>}<button type="submit" disabled={!dirty || !name.trim() || saving}>{saving ? <LoaderCircle className="is-running" size={14} /> : <Save size={14} />} 변경 저장</button></footer>
          </form>
        </section>

        <section className="knowledge-card knowledge-danger-card">
          <header><div><strong>공간 삭제</strong><small>화면에서 제거하되 revision과 provenance는 보존 정책에 따라 archive합니다.</small></div></header>
          <div><Archive size={18} /><p><strong>{space.name}</strong>을 더 이상 목록에 표시하지 않습니다. 실행 중인 추출이 있다면 완료 후 정리하는 것을 권장합니다.</p>{confirmArchive ? <div className="knowledge-inline-confirm"><span>정말 삭제하시겠습니까?</span><button type="button" onClick={() => setConfirmArchive(false)}>취소</button><button type="button" disabled={saving} onClick={archive}>{saving && <LoaderCircle className="is-running" size={13} />} 삭제 확인</button></div> : <button type="button" onClick={() => setConfirmArchive(true)}>공간 삭제</button>}</div>
        </section>
      </div>

      <aside className="knowledge-settings-aside">
        <section className="knowledge-card">
          <header><div><strong>범위와 권한</strong><small>현재 적용 중인 데이터 경계</small></div></header>
          <dl className="knowledge-policy-list"><div><dt><LockKeyhole size={14} /> 소유 범위</dt><dd>개인 계정</dd></div><div><dt><ShieldCheck size={14} /> 공개 범위</dt><dd>비공개</dd></div><div><dt><Database size={14} /> 저장 방식</dt><dd>SQLite · relational graph</dd></div></dl>
          <p className="knowledge-policy-note">조직 공유는 개인 원본을 직접 공개하지 않고 고정 Revision Publication으로 연결하는 별도 단계입니다.</p>
        </section>

        <section className="knowledge-card">
          <header><div><strong>AI 추출과 사용량</strong><small>현재 Space 누적 관측값</small></div><Coins size={16} /></header>
          <div className="knowledge-usage-grid"><span><b>{ingestions.length}</b><small>추출 작업</small></span><span><b>{usage.input.toLocaleString()}</b><small>입력 tokens</small></span><span><b>{usage.output.toLocaleString()}</b><small>출력 tokens</small></span><span><b>{usage.characters.toLocaleString()}</b><small>입력 문자</small></span></div>
          {latestJob ? <div className="knowledge-model-info"><RotateCcw size={14} /><span><strong>{latestJob.providerId} / {latestJob.modelKey}</strong><small>최근 작업 {formatDate(latestJob.createdAt)} · extractor {latestJob.extractorVersion}</small></span></div> : <p className="knowledge-policy-note">아직 AI 추출 작업이 없습니다. 계정의 기본 실행 모델을 첫 작업에서 snapshot으로 고정합니다.</p>}
          <ul className="knowledge-cost-guards"><li>동일 source digest·모델·extractor 결과 재사용</li><li>작업당 최대 40개 근거 구간·60,000자</li><li>구조화 추출 결과를 Wiki와 Graph에서 함께 재사용</li><li>실패 시 자동 게시하지 않고 검토함 유지</li></ul>
        </section>
      </aside>
    </div>
  );
}
