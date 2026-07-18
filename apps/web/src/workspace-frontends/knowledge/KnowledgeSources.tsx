import { CheckCircle2, Clock3, FileText, LoaderCircle, RefreshCw, RotateCcw, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import type { KnowledgeIngestionJob, KnowledgeSource } from "../../api-types";
import { formatBytes, formatDate } from "./knowledge-utils";

interface KnowledgeSourcesProps {
  sources: KnowledgeSource[];
  ingestions: KnowledgeIngestionJob[];
  selectedSourceId: string | null;
  selectedEvidenceId: string | null;
  startingSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
  onSelectEvidence: (evidenceId: string | null) => void;
  onStartIngestion: (sourceId: string) => void;
}

export function KnowledgeSources({ sources, ingestions, selectedSourceId, selectedEvidenceId, startingSourceId, onSelectSource, onSelectEvidence, onStartIngestion }: KnowledgeSourcesProps) {
  const selected = sources.find((source) => source.id === selectedSourceId) ?? sources[0] ?? null;
  const jobsBySource = useMemo(() => {
    const result = new Map<string, KnowledgeIngestionJob[]>();
    for (const job of ingestions) result.set(job.sourceId, [...(result.get(job.sourceId) ?? []), job]);
    return result;
  }, [ingestions]);
  const jobs = selected ? jobsBySource.get(selected.id) ?? [] : [];
  const latestJob = jobs[0];
  const active = latestJob?.status === "queued" || latestJob?.status === "running";
  const selectedEvidence = selected?.evidenceSegments.find((item) => item.id === selectedEvidenceId) ?? selected?.evidenceSegments[0] ?? null;

  if (!sources.length) return <div className="knowledge-empty"><FileText size={25} /><h3>등록된 원문이 없습니다.</h3><p>상단의 원문 버튼에서 텍스트나 Markdown을 등록하면 revision과 digest를 보존합니다.</p></div>;

  return (
    <div className="knowledge-master-detail knowledge-sources-page">
      <aside className="knowledge-master-list">
        <header><div><strong>원문</strong><small>{sources.length}개 revision</small></div></header>
        {sources.map((source) => {
          const latest = jobsBySource.get(source.id)?.[0];
          return <button type="button" className={selected?.id === source.id ? "is-active" : ""} key={source.id} onClick={() => { onSelectSource(source.id); onSelectEvidence(null); }}>
            <FileText size={15} />
            <span><strong>{source.title}</strong><small>rev {source.revision.revisionNumber} · {formatBytes(source.revision.byteSize)}</small></span>
            <JobIcon job={latest} />
          </button>;
        })}
      </aside>

      {selected && <section className="knowledge-detail-panel">
        <header className="knowledge-detail-header">
          <div><span className="knowledge-kicker">{selected.sourceType.toUpperCase()} SOURCE</span><h3>{selected.title}</h3><p>revision {selected.revision.revisionNumber} · {formatDate(selected.revision.capturedAt)} · {formatBytes(selected.revision.byteSize)}</p></div>
          <button type="button" disabled={active || startingSourceId !== null || latestJob?.status === "completed"} onClick={() => onStartIngestion(selected.id)}>
            {(active || startingSourceId === selected.id) ? <RefreshCw className="is-running" size={14} /> : latestJob?.status === "failed" ? <RotateCcw size={14} /> : <LoaderCircle size={14} />}
            {latestJob?.status === "completed" ? "추출 완료" : latestJob?.status === "failed" ? "다시 추출" : active ? "AI 추출 중" : "AI 추출"}
          </button>
        </header>

        {latestJob && <div className={`knowledge-job-banner is-${latestJob.status}`} role="status">
          <JobIcon job={latestJob} />
          <div><strong>{ingestionLabel(latestJob)}</strong><small>{latestJob.status === "completed" ? `${latestJob.providerId} / ${latestJob.modelKey} · 입력 ${latestJob.inputTokens.toLocaleString()} tokens · 출력 ${latestJob.outputTokens.toLocaleString()} tokens` : latestJob.errorMessage || `${latestJob.inputSegmentCount}개 근거 구간을 처리합니다.`}</small></div>
          <time>{formatDate(latestJob.finishedAt ?? latestJob.startedAt ?? latestJob.queuedAt)}</time>
        </div>}

        <div className="knowledge-source-body">
          <section className="knowledge-evidence-list">
            <header><strong>근거 구간</strong><span>{selected.evidenceSegments.length}</span></header>
            {selected.evidenceSegments.map((evidence) => <button type="button" className={selectedEvidence?.id === evidence.id ? "is-active" : ""} key={evidence.id} onClick={() => onSelectEvidence(evidence.id)}><span>#{evidence.segmentOrdinal + 1}</span><p>{evidence.text.slice(0, 120)}</p><small>{evidence.tokenCount.toLocaleString()} tokens</small></button>)}
          </section>
          <article className="knowledge-evidence-detail">
            {selectedEvidence ? <><header><div><span>Evidence #{selectedEvidence.segmentOrdinal + 1}</span><strong>{locatorLabel(selectedEvidence.locator)}</strong></div><small>{selectedEvidence.language || "언어 미지정"} · digest {selectedEvidence.textDigest.slice(0, 10)}</small></header><pre>{selectedEvidence.text}</pre></> : <p>확인할 근거 구간을 선택해 주세요.</p>}
          </article>
        </div>

        {jobs.length > 1 && <section className="knowledge-job-history"><header><strong>처리 기록</strong><span>{jobs.length}</span></header>{jobs.map((job) => <div key={job.id}><JobIcon job={job} /><span><strong>{ingestionLabel(job)}</strong><small>{job.providerId} / {job.modelKey}</small></span><time>{formatDate(job.createdAt)}</time></div>)}</section>}
      </section>}
    </div>
  );
}

function JobIcon({ job }: { job?: KnowledgeIngestionJob }) {
  if (!job) return <Clock3 className="is-muted" size={14} />;
  if (job.status === "completed") return <CheckCircle2 className="is-success" size={14} />;
  if (job.status === "failed") return <TriangleAlert className="is-danger" size={14} />;
  return <LoaderCircle className="is-running" size={14} />;
}

function ingestionLabel(job: KnowledgeIngestionJob) {
  if (job.status === "queued") return "추출 대기";
  if (job.status === "running") return "근거 기반 추출 중";
  if (job.status === "failed") return "추출 실패";
  return `${job.entityCount}개 Entity · ${job.statementCount}개 검토 제안`;
}

function locatorLabel(locator: Record<string, unknown>) {
  const entries = Object.entries(locator);
  return entries.length ? entries.map(([key, value]) => `${key} ${String(value)}`).join(" · ") : "위치 정보 없음";
}
