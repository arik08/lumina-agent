import { Ban, Check, ChevronDown, LoaderCircle, Plus, RefreshCw, Save, ServerCog, ShieldCheck } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { McpConfiguration, McpDefinition, McpToolDefinition, McpTransport } from "../api-types";
import { SyntaxTextarea } from "./SyntaxCode";

const defaultConfiguration: McpConfiguration = {
  transport: "streamable_http",
  command: [],
  urlTemplate: "https://mcp.example.com/v1/mcp",
  allowedHosts: ["mcp.example.com"],
  allowedIpRanges: [],
  headerTemplates: {},
  tools: [{ name: "search", description: "검색", inputSchema: { type: "object", properties: { query: { type: "string" } } } }],
  requiredSecretNames: [],
  timeoutSeconds: 30,
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "MCP 관리 요청을 처리하지 못했습니다.";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function parseConfiguration(value: string): McpConfiguration {
  const parsed: unknown = JSON.parse(value);
  if (!isRecord(parsed) || parsed.transport !== "stdio" && parsed.transport !== "streamable_http") {
    throw new Error("transport는 stdio 또는 streamable_http여야 합니다.");
  }
  if (!Array.isArray(parsed.tools) || parsed.tools.length === 0) throw new Error("tools를 하나 이상 입력해 주세요.");
  const tools: McpToolDefinition[] = parsed.tools.map((item) => {
    if (!isRecord(item) || typeof item.name !== "string" || !item.name.trim()) throw new Error("각 Tool에는 name이 필요합니다.");
    return {
      name: item.name.trim(),
      description: typeof item.description === "string" ? item.description : "",
      inputSchema: isRecord(item.inputSchema) ? item.inputSchema : { type: "object" },
    };
  });
  return {
    transport: parsed.transport as McpTransport,
    command: stringList(parsed.command),
    urlTemplate: typeof parsed.urlTemplate === "string" ? parsed.urlTemplate : null,
    allowedHosts: stringList(parsed.allowedHosts),
    allowedIpRanges: stringList(parsed.allowedIpRanges),
    headerTemplates: isRecord(parsed.headerTemplates)
      ? Object.fromEntries(Object.entries(parsed.headerTemplates).filter((entry): entry is [string, string] => typeof entry[1] === "string"))
      : {},
    tools,
    requiredSecretNames: stringList(parsed.requiredSecretNames),
    timeoutSeconds: typeof parsed.timeoutSeconds === "number" ? parsed.timeoutSeconds : 30,
  };
}

export function AdminMcpPanel() {
  const [definitions, setDefinitions] = useState<McpDefinition[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [configurationText, setConfigurationText] = useState(JSON.stringify(defaultConfiguration, null, 2));
  const [revisionText, setRevisionText] = useState(JSON.stringify(defaultConfiguration, null, 2));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const selected = definitions.find((item) => item.id === selectedId) ?? definitions[0] ?? null;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api.admin.listMcpDefinitions(controller.signal)
      .then((items) => {
        setDefinitions(items);
        setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const createDefinition = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    let configuration: McpConfiguration;
    try {
      configuration = parseConfiguration(configurationText);
    } catch (caught) {
      setError(errorMessage(caught));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.admin.createMcpDefinition({ name: name.trim(), slug: slug.trim() || undefined, description: description.trim(), configuration });
      setName("");
      setSlug("");
      setDescription("");
      setConfigurationText(JSON.stringify(defaultConfiguration, null, 2));
      setCreateOpen(false);
      setSelectedId(created.id);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const openRevision = () => {
    const current = selected?.revisions.find((item) => item.id === selected.currentRevisionId) ?? selected?.revisions.at(-1);
    const configuration = current?.configuration ?? (current ? {
      transport: current.transport,
      command: [],
      urlTemplate: null,
      allowedHosts: [],
      allowedIpRanges: [],
      headerTemplates: {},
      tools: current.tools,
      requiredSecretNames: current.requiredSecretNames,
      timeoutSeconds: current.timeoutSeconds,
    } : defaultConfiguration);
    setRevisionText(JSON.stringify(configuration, null, 2));
    setRevisionOpen(true);
  };

  const createRevision = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected || busy) return;
    let configuration: McpConfiguration;
    try {
      configuration = parseConfiguration(revisionText);
    } catch (caught) {
      setError(errorMessage(caught));
      return;
    }
    setBusy(true);
    try {
      await api.admin.createMcpRevision(selected.id, configuration);
      setRevisionOpen(false);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const approve = async (revisionId: string, revision: number) => {
    if (!selected || !window.confirm(`${selected.name} r${revision}을 승인하고 신규 설치 revision으로 지정하시겠습니까?`)) return;
    setBusy(true);
    try {
      await api.admin.approveMcpRevision(selected.id, revisionId);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    if (!selected || !window.confirm(`${selected.name}을 비활성화하시겠습니까? 신규 설치와 Composer 노출이 중단됩니다.`)) return;
    setBusy(true);
    try {
      await api.admin.setMcpStatus(selected.id, "disabled", "관리자 UI에서 비활성화");
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="admin-mcp-panel" aria-label="MCP 정의 관리">
      <div className="admin-mcp-toolbar"><span>MCP 정의 {definitions.length}개</span><div><button type="button" aria-label="MCP 새로 고침" disabled={loading} onClick={refresh}>{loading ? <LoaderCircle className="is-running" size={14} /> : <RefreshCw size={14} />}</button><button className="primary-compact lumina-primary-action" type="button" onClick={() => setCreateOpen((open) => !open)}><Plus size={14} /> 정의 등록</button></div></div>
      {error && <div className="feature-error" role="alert">{error}</div>}
      {createOpen && <form className="admin-mcp-form" onSubmit={(event) => void createDefinition(event)}><div className="admin-mcp-form-grid"><label>이름<input autoFocus value={name} onChange={(event) => setName(event.currentTarget.value)} /></label><label>Slug<input value={slug} placeholder="internal-search" onChange={(event) => setSlug(event.currentTarget.value)} /></label><label>설명<input value={description} onChange={(event) => setDescription(event.currentTarget.value)} /></label></div><label>Configuration JSON<SyntaxTextarea ariaLabel="Configuration JSON" language="json" value={configurationText} onChange={(event) => setConfigurationText(event.currentTarget.value)} /></label><div><small>Secret은 requiredSecretNames와 headerTemplates로 연결합니다. 사내 private·loopback 대상만 allowedIpRanges에 관리자 승인 CIDR로 입력합니다.</small><button type="submit" disabled={busy || !name.trim()}><Save size={14} /> 등록</button></div></form>}
      <div className="admin-mcp-layout">
        <div className="admin-mcp-list">{definitions.map((definition) => <button className={definition.id === selected?.id ? "is-selected" : ""} type="button" key={definition.id} onClick={() => setSelectedId(definition.id)}><ServerCog size={15} /><span><strong>{definition.name}</strong><small>{definition.slug} · {definition.status}</small></span><ChevronDown size={14} /></button>)}</div>
        <div className="admin-mcp-detail">
          {!selected ? <p className="workspace-empty">MCP 정의를 선택해 주세요.</p> : <><header><div><strong>{selected.name}</strong><small>{selected.description || selected.slug}</small></div><div><button type="button" onClick={openRevision}><Plus size={14} /> Revision</button>{selected.status !== "disabled" && <button className="text-danger" type="button" disabled={busy} onClick={() => void disable()}><Ban size={14} /> 비활성화</button>}</div></header>{revisionOpen && <form className="admin-mcp-form revision-form" onSubmit={(event) => void createRevision(event)}><label>새 Configuration JSON<SyntaxTextarea ariaLabel="새 Configuration JSON" language="json" value={revisionText} onChange={(event) => setRevisionText(event.currentTarget.value)} /></label><small>allowedIpRanges는 승인된 private·loopback CIDR만 허용하며 link-local·multicast는 사용할 수 없습니다.</small><div><button type="button" onClick={() => setRevisionOpen(false)}>취소</button><button type="submit" disabled={busy}><Save size={14} /> Revision 등록</button></div></form>}<div className="admin-mcp-revisions">{[...selected.revisions].reverse().map((revision) => <article key={revision.id}><div><strong>r{revision.revision}</strong><span>{revision.transport}</span><span>health {revision.healthStatus}</span><span>schema {revision.schemaStatus}</span></div><small>{revision.tools.map((tool) => tool.name).join(", ")} · secrets {revision.requiredSecretNames.length}</small><div>{selected.currentRevisionId === revision.id && <em><ShieldCheck size={13} /> 현재 승인</em>}{revision.approvalStatus !== "approved" && <button type="button" disabled={busy || revision.validationStatus === "failed"} onClick={() => void approve(revision.id, revision.revision)}><Check size={14} /> 승인</button>}</div></article>)}</div></>}
        </div>
      </div>
    </section>
  );
}
