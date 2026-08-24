import {
  ArrowRight,
  BadgeCheck,
  Bot,
  Braces,
  Check,
  CircleOff,
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
    id: "posco-cost-analysis",
    name: "원가분석 AI Agent",
    publisher: "Enhans",
    description: "POSCO Data Lake의 표준·실적 원가 데이터를 조회해 제품, 공정과 기간별 원가 차이를 설명하고 의사결정용 시나리오를 만드는 원격 Agent입니다.",
    version: "1.4.2-demo",
    protocol: "A2A v0.3",
    connected: true,
    endpoint: "https://a2a.enhans.example/v1/posco-cost-analysis",
    dataSource: "POSCO Data Lake · Cost Mart",
    tags: ["원가분석", "POSCO", "Data Lake"],
    capabilities: ["Streaming analysis updates", "Structured data input", "Artifact handoff", "Dataset revision traceability"],
    boundaries: [
      "POSCO Data Lake 원가 Mart 읽기 전용",
      "사업장·품종·기간은 Project 권한 범위로 제한",
      "계약단가와 개인 식별 정보는 결과에서 마스킹",
      "조회 조건·데이터 기준일·산출 근거를 Artifact에 보존",
    ],
    skills: [
      {
        name: "표준·실적 원가 차이 분석",
        description: "사업장, 품종과 기간을 기준으로 재료비·에너지비·노무비·가공비의 표준 대비 실적 차이를 브리지로 분해합니다.",
        input: "CostVarianceRequest",
        output: "CostVarianceBridge",
      },
      {
        name: "원가 변동 원인 Drill-down",
        description: "원료 단가, 투입 원단위, 수율, 환율과 조업 조건을 단계별로 추적해 주요 원가 변동 요인과 기여도를 설명합니다.",
        input: "CostDriverQuery",
        output: "CostDriverAnalysis",
      },
      {
        name: "원가 개선 시나리오",
        description: "원료 가격, 에너지 단가와 수율 가정을 조정해 예상 원가와 손익 민감도를 비교하고 검토용 분석표를 생성합니다.",
        input: "CostScenarioAssumptions",
        output: "CostScenarioWorkbook",
      },
    ],
  },
  {
    id: "salesforce-mih",
    name: "MIH Agent",
    publisher: "Salesforce",
    description: "Marketing Information Hub의 시장·고객·경쟁 정보를 연결해 지역과 제품별 수요 신호를 분석하고 마케팅 의사결정 자료를 만드는 원격 Agent입니다.",
    version: "2.3.0-demo",
    protocol: "A2A v0.3",
    connected: true,
    endpoint: "https://a2a.salesforce.example/v1/mih-intelligence",
    dataSource: "Salesforce MIH · Marketing Data Mart",
    tags: ["마케팅", "시장정보", "Salesforce"],
    capabilities: ["Multi-source intelligence retrieval", "Streaming task updates", "Structured insight output", "Artifact handoff"],
    boundaries: [
      "승인된 MIH 시장·고객 데이터셋만 읽기 전용 조회",
      "고객 식별 정보와 영업 기밀은 집계 수준으로 제한",
      "지역·제품·기간별 Project 접근 권한 적용",
      "출처·갱신 시각·분석 기준을 결과에 함께 표시",
    ],
    skills: [
      {
        name: "시장 수요 Signal 분석",
        description: "지역·산업·제품별 시장 지표와 고객 접점을 결합해 수요 변화와 조기 경보 신호를 정리합니다.",
        input: "MarketSignalRequest",
        output: "DemandSignalBrief",
      },
      {
        name: "고객·제품 Opportunity Map",
        description: "고객군, 제품 포트폴리오와 판매 접점을 교차 분석해 우선 대응할 시장 기회와 공백을 식별합니다.",
        input: "OpportunityScope",
        output: "OpportunityMap",
      },
      {
        name: "경쟁·캠페인 Intelligence Brief",
        description: "경쟁 동향과 캠페인 성과를 비교해 핵심 변화, 근거와 다음 마케팅 액션을 한 문서로 정리합니다.",
        input: "IntelligenceBriefRequest",
        output: "MarketingIntelligenceBrief",
      },
    ],
  },
  {
    id: "facility-management-gpt",
    name: "설비관리 GPT",
    publisher: "POSCO",
    description: "설비 기준정보와 점검·정비 이력을 바탕으로 설비 상태를 요약하고 예방정비 우선순위와 현장 작업 준비사항을 안내하는 사내 원격 Agent입니다.",
    version: "1.8.1-demo",
    protocol: "A2A v0.3",
    connected: true,
    endpoint: "https://a2a.posco.example/v1/facility-management-gpt",
    dataSource: "설비관리 GPT · 설비 기준정보/정비 이력",
    tags: ["설비관리", "예방정비", "POSCO"],
    capabilities: ["Multi-turn equipment context", "Long-running task support", "Maintenance artifact handoff", "Status polling and cancellation"],
    boundaries: [
      "사용자에게 허용된 사업장·설비 범위만 조회",
      "설비 제어와 작업지시 확정은 수행하지 않음",
      "안전·정비 기준 변경은 담당자 승인 후 반영",
      "참조한 설비·점검·정비 이력을 결과에 보존",
    ],
    skills: [
      {
        name: "설비 상태·이력 요약",
        description: "설비번호를 기준으로 현재 상태, 최근 점검 결과, 고장과 정비 이력을 시간순으로 요약합니다.",
        input: "EquipmentContextRequest",
        output: "EquipmentHealthSummary",
      },
      {
        name: "예방정비 우선순위 추천",
        description: "점검 주기, 이상 징후, 고장 영향도와 정비 이력을 종합해 우선 확인할 설비와 근거를 제시합니다.",
        input: "MaintenancePriorityRequest",
        output: "MaintenancePriorityPlan",
      },
      {
        name: "현장 작업 준비사항",
        description: "승인된 정비 범위에 맞춰 관련 매뉴얼, 안전 확인사항, 필요 자재와 과거 유사 작업을 작업 전 검토용으로 정리합니다.",
        input: "MaintenanceWorkScope",
        output: "WorkPreparationBrief",
      },
    ],
  },
] as const;

export function A2AMarketplacePanel() {
  const [view, setView] = useState<A2AView>("catalog");
  const [query, setQuery] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState<string>(demoAgents[0].id);
  const connectedAgents = useMemo(() => demoAgents.filter((agent) => agent.connected), []);
  const agentsInView = view === "connected" ? connectedAgents : demoAgents;
  const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
  const visibleAgents = useMemo(() => agentsInView.filter((agent) => (
    view === "connected"
    || !normalizedQuery
    || `${agent.name} ${agent.publisher} ${agent.description} ${agent.tags.join(" ")}`
      .toLocaleLowerCase("ko-KR")
      .includes(normalizedQuery)
  )), [agentsInView, normalizedQuery, view]);
  const selectedAgent = visibleAgents.find((agent) => agent.id === selectedAgentId) ?? visibleAgents[0] ?? null;

  return (
    <div className="a2a-marketplace-panel">
      <div className="marketplace-toolbar">
        <div className="marketplace-scope-tabs" role="tablist" aria-label="A2A 보기">
          <button type="button" role="tab" aria-selected={view === "catalog"} onClick={() => setView("catalog")}>
            <Network size={14} /> 카탈로그 <span>{demoAgents.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={view === "connected"} onClick={() => setView("connected")}>
            <Radio size={14} /> 연결됨 <span>{connectedAgents.length}</span>
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

      {view === "connected" && connectedAgents.length === 0 ? <section className="a2a-connected-empty">
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
            <div><strong>A2A Agent</strong><span>{view === "connected" ? "현재 Project에 데모 연결된 Agent" : "조직에서 검토 가능한 원격 Agent"}</span></div>
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
            <span>데모 연결입니다. 실제 연결 전 보안·권한·데이터 경계 검토가 필요합니다.</span>
          </footer>
        </aside>

        <article className="a2a-agent-detail">
          <header className="a2a-agent-heading">
            <div className="a2a-agent-identity">
              <span className="a2a-agent-mark"><Bot size={20} /></span>
              <div>
                <span className="a2a-eyebrow"><BadgeCheck size={13} /> A2A Agent Card · 데모</span>
                <h2>{selectedAgent.name}</h2>
                <p>{selectedAgent.description}</p>
              </div>
            </div>
            <div className="a2a-agent-actions">
              <span><Radio size={13} /> 데모 연결됨</span>
              <button type="button" disabled aria-describedby="a2a-availability-note">연결됨</button>
              <small id="a2a-availability-note">표시 전용 연결이며 실제 작업은 실행되지 않습니다.</small>
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
                  <div><dt>Data source</dt><dd>{selectedAgent.dataSource}</dd></div>
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
