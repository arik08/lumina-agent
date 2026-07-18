import { Check, FileText, LoaderCircle, ShieldCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api";
import type { KnowledgeEntity, KnowledgeSource, KnowledgeStatement } from "../../api-types";
import { evidenceById, formatDate, statementSentence } from "./knowledge-utils";

interface KnowledgeReviewProps {
  sources: KnowledgeSource[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  onOpenEvidence: (evidenceId: string) => void;
  onReviewed: (originalId: string, reviewed: KnowledgeStatement) => void;
  onError: (error: unknown) => void;
}

export function KnowledgeReview({ sources, statements, entityById, onOpenEvidence, onReviewed, onError }: KnowledgeReviewProps) {
  const pending = statements.filter((statement) => statement.status === "proposed");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const selected = pending.find((statement) => statement.id === selectedId) ?? pending[0] ?? null;
  const evidence = useMemo(() => evidenceById(sources), [sources]);

  async function decide(decision: "approved" | "rejected") {
    if (!selected || saving) return;
    setSaving(true);
    try {
      const reviewed = await api.knowledge.decideStatement(selected.id, { decision, reason: reason.trim() });
      onReviewed(selected.id, reviewed);
      setSelectedId(pending.find((item) => item.id !== selected.id)?.id ?? null);
      setReason("");
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  if (!pending.length) return <div className="knowledge-empty knowledge-review-empty"><ShieldCheck size={28} /><h3>검토할 제안이 없습니다.</h3><p>AI 추출 결과는 자동 게시되지 않으며, 새 제안이 생기면 이곳에서 근거를 확인할 수 있습니다.</p><span><Check size={13} /> 현재 Wiki와 Graph에는 승인된 지식만 반영됩니다.</span></div>;

  return (
    <div className="knowledge-master-detail knowledge-review-page">
      <aside className="knowledge-master-list">
        <header><div><strong>검토 대기</strong><small>{pending.length}개 Statement 제안</small></div></header>
        {pending.map((statement) => <button type="button" className={selected?.id === statement.id ? "is-active" : ""} key={statement.id} onClick={() => { setSelectedId(statement.id); setReason(""); }}><ShieldCheck size={14} /><span><strong>{statementSentence(statement, entityById)}</strong><small>revision {statement.revisionNumber ?? "-"} · 근거 {statement.evidenceSegmentIds.length}개</small></span></button>)}
      </aside>

      {selected && <section className="knowledge-review-detail">
        <header><span className="knowledge-kicker">STATEMENT PROPOSAL</span><h3>{statementSentence(selected, entityById)}</h3><p>revision {selected.revisionNumber ?? "-"} · {formatDate(selected.recordedAt)}{selected.confidence != null ? ` · 추출 신뢰 신호 ${Math.round(selected.confidence * 100)}%` : ""}</p></header>

        <section>
          <h4>제안 내용</h4>
          <dl><div><dt>주체</dt><dd>{entityById.get(selected.subjectEntityId)?.canonicalName ?? "알 수 없음"}</dd></div><div><dt>관계</dt><dd>{selected.predicateKey}</dd></div><div><dt>대상</dt><dd>{selected.objectEntityId ? entityById.get(selected.objectEntityId)?.canonicalName ?? "알 수 없음" : String(selected.objectValue)}</dd></div><div><dt>상태</dt><dd><span className="knowledge-badge is-proposed">검토 제안</span></dd></div></dl>
        </section>

        <section>
          <h4>연결된 근거</h4>
          {selected.evidenceSegmentIds.length ? <div className="knowledge-review-evidence">{selected.evidenceSegmentIds.map((id) => { const info = evidence.get(id); return info ? <button type="button" key={id} onClick={() => onOpenEvidence(id)}><FileText size={15} /><span><strong>{info.source.title}</strong><small>{info.evidence.text}</small></span><em>원문 열기</em></button> : <div className="knowledge-missing-evidence" key={id}>근거에 접근할 수 없습니다.</div>; })}</div> : <div className="knowledge-missing-evidence">근거가 없어 승인할 수 없습니다. 거절하거나 근거가 있는 새 Statement를 등록해 주세요.</div>}
        </section>

        <section className="knowledge-review-decision">
          <label>검토 메모<textarea value={reason} rows={3} maxLength={10_000} placeholder="승인 또는 거절 이유를 남길 수 있습니다." onChange={(event) => setReason(event.target.value)} /></label>
          <p>결정하면 기존 제안을 덮어쓰지 않고 새 Knowledge revision으로 기록합니다.</p>
          <div><button className="is-reject" type="button" disabled={saving} onClick={() => decide("rejected")}><X size={14} /> 거절</button><button className="is-approve" type="button" disabled={saving || !selected.evidenceSegmentIds.length} onClick={() => decide("approved")}>{saving ? <LoaderCircle className="is-running" size={14} /> : <Check size={14} />} 근거 확인 후 승인</button></div>
        </section>
      </section>}
    </div>
  );
}
