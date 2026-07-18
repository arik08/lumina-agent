import { ArrowRight, BookOpenText, CircleAlert, FileText, GitBranch, LoaderCircle, ShieldCheck } from "lucide-react";
import type { KnowledgeEntity, KnowledgeIngestionJob, KnowledgeSource, KnowledgeStatement } from "../../api-types";
import type { KnowledgeTab } from "./KnowledgeView";
import { formatDate, statementSentence } from "./knowledge-utils";

interface KnowledgeHomeProps {
  sources: KnowledgeSource[];
  entities: KnowledgeEntity[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  ingestions: KnowledgeIngestionJob[];
  onChangeTab: (tab: KnowledgeTab) => void;
  onOpenEntity: (entityId: string, tab?: KnowledgeTab) => void;
}

export function KnowledgeHome({ sources, entities, statements, entityById, ingestions, onChangeTab, onOpenEntity }: KnowledgeHomeProps) {
  const approved = statements.filter((statement) => statement.status === "approved");
  const pending = statements.filter((statement) => statement.status === "proposed");
  const running = ingestions.filter((job) => job.status === "queued" || job.status === "running");
  const failed = ingestions.filter((job) => job.status === "failed");
  const recentStatements = statements.slice(0, 5);
  const ready = sources.length > 0 && entities.length > 0 && approved.length > 0;

  return (
    <div className="knowledge-page knowledge-home">
      <section className="knowledge-hero-card">
        <div>
          <small>PERSONAL KNOWLEDGE</small>
          <h3>{ready ? "검증된 지식을 바로 찾아 쓸 수 있습니다." : "원문에서 검증 가능한 지식으로"}</h3>
          <p>{ready ? "Wiki와 Graph는 같은 승인 Statement를 사용하며, 모든 사실에서 원문 근거를 다시 열 수 있습니다." : "원문을 추가하면 AI가 Entity와 Statement를 제안하고, 검토한 결과만 Wiki와 Graph에 반영됩니다."}</p>
        </div>
        <button type="button" onClick={() => onChangeTab(sources.length ? (pending.length ? "review" : "wiki") : "sources")}>
          {sources.length ? (pending.length ? "검토 시작" : "Wiki 열기") : "첫 원문 추가"}<ArrowRight size={15} />
        </button>
      </section>

      <div className="knowledge-stat-grid">
        <button type="button" onClick={() => onChangeTab("sources")}><FileText /><span><b>{sources.length}</b><small>보존된 원문</small></span></button>
        <button type="button" onClick={() => onChangeTab("wiki")}><BookOpenText /><span><b>{entities.length}</b><small>Wiki Entity</small></span></button>
        <button type="button" onClick={() => onChangeTab("graph")}><GitBranch /><span><b>{approved.length}</b><small>승인 Statement</small></span></button>
        <button type="button" className={pending.length ? "is-warning" : ""} onClick={() => onChangeTab("review")}><ShieldCheck /><span><b>{pending.length}</b><small>검토 대기</small></span></button>
      </div>

      {(running.length > 0 || failed.length > 0) && (
        <section className="knowledge-status-strip" aria-label="처리 상태">
          {running.length > 0 && <span><LoaderCircle className="is-running" size={14} /> {running.length}개 원문에서 지식을 추출하고 있습니다.</span>}
          {failed.length > 0 && <button type="button" onClick={() => onChangeTab("sources")}><CircleAlert size={14} /> 실패 {failed.length}개 확인</button>}
        </section>
      )}

      <div className="knowledge-dashboard-grid">
        <section className="knowledge-card">
          <header><div><strong>최근 지식 변경</strong><small>현재 revision 기준</small></div><button type="button" onClick={() => onChangeTab("explore")}>전체 탐색</button></header>
          {recentStatements.length ? <div className="knowledge-activity-list">{recentStatements.map((statement) => (
            <button type="button" key={statement.id} onClick={() => onOpenEntity(statement.subjectEntityId)}>
              <span className={`knowledge-status-dot is-${statement.status}`} />
              <span><strong>{statementSentence(statement, entityById)}</strong><small>revision {statement.revisionNumber ?? "-"} · {formatDate(statement.recordedAt)}</small></span>
              <em>{statement.status === "approved" ? "승인" : statement.status === "proposed" ? "검토" : "거절"}</em>
            </button>
          ))}</div> : <EmptyBlock text="아직 Statement가 없습니다. 원문을 추가하고 AI 추출을 시작해 보세요." />}
        </section>

        <section className="knowledge-card">
          <header><div><strong>구성 상태</strong><small>운영 가능한 지식 흐름</small></div></header>
          <ol className="knowledge-readiness-list">
            <li className={sources.length ? "is-done" : ""}><span>1</span><div><strong>원문 보존</strong><small>{sources.length ? `${sources.length}개 원문과 revision 보존 중` : "근거가 될 텍스트를 등록해 주세요."}</small></div></li>
            <li className={entities.length ? "is-done" : ""}><span>2</span><div><strong>구조화 추출</strong><small>{entities.length ? `${entities.length}개 Entity 식별됨` : "AI 추출 또는 수동 등록이 필요합니다."}</small></div></li>
            <li className={approved.length ? "is-done" : ""}><span>3</span><div><strong>사람 검토</strong><small>{approved.length ? `${approved.length}개 Statement 승인됨` : pending.length ? `${pending.length}개 제안을 검토해 주세요.` : "근거가 있는 Statement가 필요합니다."}</small></div></li>
            <li className={approved.length ? "is-done" : ""}><span>4</span><div><strong>Wiki · Graph 반영</strong><small>승인된 사실만 읽기 화면과 그래프에 반영됩니다.</small></div></li>
          </ol>
        </section>
      </div>
    </div>
  );
}

function EmptyBlock({ text }: { text: string }) {
  return <div className="knowledge-card-empty"><BookOpenText size={20} /><p>{text}</p></div>;
}
