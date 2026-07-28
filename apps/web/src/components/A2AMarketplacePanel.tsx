import {
  ArrowRight,
  BadgeCheck,
  Bot,
  Braces,
  Check,
  CircleOff,
  Clock3,
  FileJson2,
  KeyRound,
  Network,
  Radio,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState } from "react";

type A2AView = "catalog" | "connected";

const demoAgents = [
  {
    id: "procurement-research",
    name: "조달 리서치 코디네이터",
    publisher: "Lumina Labs",
    description: "공급사 조사부터 비교표와 RFQ 초안까지, 근거 자료를 보존하며 조달 검토 업무를 분담하는 원격 Agent입니다.",
    version: "0.1.0-demo",
    protocol: "A2A v0.3",
    endpoint: "https://agents.demo.lumina.local/procurement/a2a",
    tags: ["조달", "리서치", "문서화"],
    capabilities: ["Streaming task updates", "Multi-turn task context", "Artifact handoff", "Cancellation and status polling"],
    boundaries: ["Project 단위 연결과 대화 격리", "외부 발송 전 사용자 승인", "위임 기록과 Artifact provenance 보존"],
    skills: [
      {
        name: "공급사 후보 조사",
        description: "요구 조건과 지역을 기준으로 후보를 조사하고 출처가 연결된 shortlist를 반환합니다.",
        input: "SourcingBrief",
        output: "SupplierShortlist",
      },
      {
        name: "제안 비교 및 위험 검토",
        description: "가격, 납기, 인증, 계약 조건을 비교하고 추가 확인이 필요한 위험을 표시합니다.",
        input: "ProposalBundle",
        output: "ComparisonReport",
      },
      {
        name: "RFQ 초안 작성",
        description: "승인된 요구사항과 비교 결과를 바탕으로 발송 전 검토용 RFQ 초안을 만듭니다.",
        input: "ApprovedRequirements",
        output: "RfqDraft",
      },
    ],
  },
  {
    id: "maintenance-response",
    name: "설비 이상 대응 Agent",
    publisher: "Smart Operations Lab",
    description: "설비 알람과 정비 이력을 받아 이상 징후를 정리하고, 현장 확인 순서와 교대 인수인계 초안을 만드는 원격 Agent입니다.",
    version: "0.2.0-demo",
    protocol: "A2A v0.3",
    endpoint: "https://agents.demo.lumina.local/maintenance/a2a",
    tags: ["설비", "이상진단", "안전"],
    capabilities: ["Streaming task updates", "Long-running task support", "Artifact handoff", "Cancellation and status polling"],
    boundaries: ["원시 센서 데이터의 Project 단위 격리", "위험 작업 제안 전 작업허가 승인", "진단 근거와 참조 정비 이력 보존"],
    skills: [
      {
        name: "알람 맥락 정리",
        description: "동시 발생 알람, 운전 조건과 최근 정비 이력을 시간순으로 정리해 우선 확인 대상을 좁힙니다.",
        input: "EquipmentAlertBundle",
        output: "IncidentContext",
      },
      {
        name: "원인 가설 및 점검 순서",
        description: "관측 증상과 설비 계통을 바탕으로 원인 가설을 제시하고 안전 조건을 포함한 현장 점검 순서를 만듭니다.",
        input: "IncidentContext",
        output: "InspectionPlan",
      },
      {
        name: "교대 인수인계 초안",
        description: "확인 결과, 미해결 위험과 다음 조치를 교대조가 이어받을 수 있는 구조화 문서로 정리합니다.",
        input: "InspectionFindings",
        output: "ShiftHandoverDraft",
      },
    ],
  },
] as const;

export function A2AMarketplacePanel() {
  const [view, setView] = useState<A2AView>("catalog");
  const [query, setQuery] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState<string>(demoAgents[0].id);
  const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
  const visibleAgents = useMemo(() => demoAgents.filter((agent) => (
    !normalizedQuery
    || `${agent.name} ${agent.publisher} ${agent.description} ${agent.tags.join(" ")}`
      .toLocaleLowerCase("ko-KR")
      .includes(normalizedQuery)
  )), [normalizedQuery]);
  const selectedAgent = visibleAgents.find((agent) => agent.id === selectedAgentId) ?? visibleAgents[0] ?? null;

  return (
    <div className="a2a-marketplace-panel">
      <div className="marketplace-toolbar">
        <div className="marketplace-scope-tabs" role="tablist" aria-label="A2A 보기">
          <button type="button" role="tab" aria-selected={view === "catalog"} onClick={() => setView("catalog")}>
            <Network size={14} /> 카탈로그 <span>{demoAgents.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={view === "connected"} onClick={() => setView("connected")}>
            <Radio size={14} /> 연결됨 <span>0</span>
          </button>
        </div>
        {view === "catalog" && <label className="marketplace-search">
          <Search size={14} />
          <input
            type="search"
            aria-label="A2A Agent 검색"
            placeholder="Agent 이름, 역할 또는 태그 검색"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        </label>}
      </div>

      {view === "connected" ? <section className="a2a-connected-empty">
        <CircleOff size={22} />
        <strong>연결된 A2A Agent가 없습니다.</strong>
        <p>카탈로그에서 Agent Card와 권한 범위를 검토한 뒤 프로젝트에 연결할 수 있습니다.</p>
        <button type="button" onClick={() => setView("catalog")}>카탈로그 보기</button>
      </section> : !selectedAgent ? <section className="a2a-connected-empty">
        <Search size={22} />
        <strong>검색 결과가 없습니다.</strong>
        <p>Agent 이름, 역할 또는 태그를 바꿔 다시 검색해 주세요.</p>
        <button type="button" onClick={() => setQuery("")}>검색 초기화</button>
      </section> : <div className="a2a-catalog-layout">
        <aside className="a2a-catalog-list" aria-label="A2A Agent 목록">
          <header>
            <div><strong>A2A Agent</strong><span>조직에서 검토 가능한 원격 Agent</span></div>
            <small>{visibleAgents.length}개</small>
          </header>
          <div className="a2a-agent-rows">
            {visibleAgents.map((agent) => <button
              className={`a2a-agent-row ${agent.id === selectedAgent.id ? "is-selected" : ""}`}
              type="button"
              aria-current={agent.id === selectedAgent.id ? "true" : undefined}
              key={agent.id}
              onClick={() => setSelectedAgentId(agent.id)}
            >
              <span className="a2a-agent-mark"><Bot size={17} /></span>
              <span>
                <strong>{agent.name}</strong>
                <small>{agent.publisher} · {agent.protocol}</small>
                <span className="a2a-row-tags">{agent.tags.map((tag) => <em key={tag}>#{tag}</em>)}</span>
              </span>
              <ArrowRight size={14} />
            </button>)}
          </div>
          <footer>
            <ShieldCheck size={14} />
            <span>등록 전 보안·권한·데이터 경계 검토가 필요합니다.</span>
          </footer>
        </aside>

        <article className="a2a-agent-detail">
          <header className="a2a-agent-heading">
            <div className="a2a-agent-identity">
              <span className="a2a-agent-mark"><Bot size={20} /></span>
              <div>
                <span className="a2a-eyebrow"><BadgeCheck size={13} /> 설계 미리보기</span>
                <h2>{selectedAgent.name}</h2>
                <p>{selectedAgent.description}</p>
              </div>
            </div>
            <div className="a2a-agent-actions">
              <span><Clock3 size={13} /> 연결 준비 전</span>
              <button type="button" disabled aria-describedby="a2a-availability-note">프로젝트에 연결</button>
              <small id="a2a-availability-note">A2A Runtime 적용 후 사용할 수 있습니다.</small>
            </div>
          </header>

          <section className="a2a-contract-strip" aria-label="A2A 연결 계약 요약">
            <div><span>Protocol</span><strong>{selectedAgent.protocol}</strong></div>
            <div><span>Transport</span><strong>JSON-RPC · HTTP/SSE</strong></div>
            <div><span>Authentication</span><strong>OAuth 2.0 + mTLS</strong></div>
            <div><span>Version</span><strong>{selectedAgent.version}</strong></div>
          </section>

          <div className="a2a-detail-columns">
            <section className="a2a-detail-section">
              <header><div><Braces size={15} /><h3>위임 가능한 작업</h3></div><span>{selectedAgent.skills.length} Skills</span></header>
              <div className="a2a-skill-list">
                {selectedAgent.skills.map((skill, index) => <article key={skill.name}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{skill.name}</strong>
                    <p>{skill.description}</p>
                    <small><code>{skill.input}</code><ArrowRight size={12} /><code>{skill.output}</code></small>
                  </div>
                </article>)}
              </div>
            </section>

            <aside className="a2a-agent-card">
              <section>
                <header><FileJson2 size={14} /><h3>Agent Card</h3></header>
                <dl>
                  <div><dt>Provider</dt><dd>{selectedAgent.publisher}</dd></div>
                  <div><dt>Endpoint</dt><dd><code>{selectedAgent.endpoint}</code></dd></div>
                  <div><dt>Input modes</dt><dd>text, file, structured data</dd></div>
                  <div><dt>Output modes</dt><dd>text, artifact, status event</dd></div>
                </dl>
              </section>
              <section>
                <header><Radio size={14} /><h3>Capabilities</h3></header>
                <ul>
                  {selectedAgent.capabilities.map((capability) => <li key={capability}><Check size={13} /> {capability}</li>)}
                </ul>
              </section>
              <section>
                <header><KeyRound size={14} /><h3>운영 경계</h3></header>
                <ul>
                  {selectedAgent.boundaries.map((boundary) => <li key={boundary}><ShieldCheck size={13} /> {boundary}</li>)}
                </ul>
              </section>
            </aside>
          </div>
        </article>
      </div>}
    </div>
  );
}
