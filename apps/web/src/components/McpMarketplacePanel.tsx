import { Check, KeyRound, LoaderCircle, Plug, Power, ShieldCheck, Trash2, Wrench } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { McpDefinition, McpInstallation } from "../api-types";
import { ResizableSplitPane } from "./ResizableSplitPane";

interface McpMarketplacePanelProps {
  projectId: string | null;
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "MCP 요청을 처리하지 못했습니다.";
}

function stateLabel(value: string) {
  if (value === "healthy" || value === "valid" || value === "approved" || value === "connected") return "정상";
  if (value === "not_connected") return "연결 전";
  if (value === "pending") return "검증 대기";
  if (value === "failed" || value === "invalid") return "확인 필요";
  return value.replaceAll("_", " ");
}

function resolverLabel(value: McpInstallation["secretResolutionStatus"]) {
  if (value === "not_required") return "Secret 불필요";
  if (value === "ready") return "Secret 사용 가능";
  if (value === "binding_required") return "env:// 연결 필요";
  if (value === "administrator_required") return "관리자 연결 필요";
  return "지원 Resolver 없음";
}

export function McpMarketplacePanel({ projectId }: McpMarketplacePanelProps) {
  const [catalog, setCatalog] = useState<McpDefinition[]>([]);
  const [installations, setInstallations] = useState<McpInstallation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [catalogPendingId, setCatalogPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [uninstallConfirmId, setUninstallConfirmId] = useState<string | null>(null);
  const [unbindConfirmKey, setUnbindConfirmKey] = useState<string | null>(null);

  const selected = catalog.find((item) => item.id === selectedId) ?? catalog[0] ?? null;
  const currentRevision = selected?.revisions.find((item) => item.id === selected.currentRevisionId) ?? selected?.revisions.at(-1) ?? null;
  const selectedInstallations = selected ? installations.filter((item) => item.definitionId === selected.id) : [];
  const skillWrapperApplied = selected?.skillWrapper?.wrapped;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      api.mcp.listCatalog(controller.signal),
      api.mcp.listInstallations(projectId ?? undefined, controller.signal),
    ]).then(([definitions, installed]) => {
      setCatalog(definitions);
      setInstallations(installed);
      setSelectedId((current) => current && definitions.some((item) => item.id === current) ? current : definitions[0]?.id ?? null);
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [projectId, refreshKey]);

  useEffect(() => {
    setSelectedTools(currentRevision?.tools.map((tool) => tool.name) ?? []);
  }, [currentRevision?.id]);

  useEffect(() => {
    setUninstallConfirmId(null);
    setUnbindConfirmKey(null);
  }, [projectId, selected?.id]);

  const refresh = () => {
    setUninstallConfirmId(null);
    setUnbindConfirmKey(null);
    setRefreshKey((value) => value + 1);
  };

  const install = async (scope: "user" | "project") => {
    if (!selected || !currentRevision || busy || scope === "project" && !projectId) return;
    setBusy(true);
    setError(null);
    try {
      await api.mcp.install(
        selected.id,
        currentRevision.id,
        scope,
        scope === "project" ? projectId ?? undefined : undefined,
        selectedTools,
      );
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const toggleCatalogInstallation = async (definition: McpDefinition) => {
    if (catalogPendingId) return;
    const revision = definition.revisions.find((item) => item.id === definition.currentRevisionId) ?? definition.revisions.at(-1) ?? null;
    const userInstallation = installations.find((item) => item.definitionId === definition.id && item.scopeType === "user") ?? null;
    if (!revision && !userInstallation) return;
    setCatalogPendingId(definition.id);
    setError(null);
    try {
      if (userInstallation) {
        await api.mcp.uninstall(userInstallation.id);
        setInstallations((current) => current.filter((item) => item.id !== userInstallation.id));
      } else {
        const installed = await api.mcp.install(definition.id, revision!.id, "user", undefined, revision!.tools.map((tool) => tool.name));
        setInstallations((current) => [...current.filter((item) => item.id !== installed.id), installed]);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setCatalogPendingId(null);
    }
  };

  const toggleInstallation = async (installation: McpInstallation) => {
    setBusy(true);
    try {
      await api.mcp.setEnabled(installation.id, !installation.enabled);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const uninstall = async (installation: McpInstallation) => {
    if (uninstallConfirmId !== installation.id) {
      setUninstallConfirmId(installation.id);
      setUnbindConfirmKey(null);
      return;
    }
    setUninstallConfirmId(null);
    setBusy(true);
    try {
      await api.mcp.uninstall(installation.id);
      setSecretInputs((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${installation.id}:`))));
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const bindSecret = async (event: FormEvent<HTMLFormElement>, installation: McpInstallation, secretName: string) => {
    event.preventDefault();
    const key = `${installation.id}:${secretName}`;
    const secretRef = secretInputs[key]?.trim() ?? "";
    if (!secretRef || busy) return;
    setSecretInputs((current) => ({ ...current, [key]: "" }));
    setBusy(true);
    try {
      await api.mcp.bindSecret(installation.id, secretName, secretRef);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const unbindSecret = async (installation: McpInstallation, secretName: string) => {
    const key = `${installation.id}:${secretName}`;
    if (unbindConfirmKey !== key) {
      setUnbindConfirmKey(key);
      setUninstallConfirmId(null);
      return;
    }
    setUnbindConfirmKey(null);
    setBusy(true);
    try {
      await api.mcp.unbindSecret(installation.id, secretName);
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  if (loading && catalog.length === 0) return <div className="feature-state"><LoaderCircle className="is-running" size={16} /> MCP 카탈로그를 불러오는 중</div>;

  return (
    <div className="mcp-marketplace-panel">
      {error && <div className="feature-error" role="alert">{error}</div>}
      <ResizableSplitPane storageKey="lumina:marketplace-list-width" ariaLabel="MCP 목록 너비 조절" className="marketplace-split">
        <aside className="feature-list" aria-label="승인된 MCP 카탈로그">
          {catalog.length === 0 ? <div className="feature-state">승인된 MCP가 없습니다.</div> : catalog.map((definition) => {
            const userInstallation = installations.find((item) => item.definitionId === definition.id && item.scopeType === "user") ?? null;
            const currentDefinitionRevision = definition.revisions.find((item) => item.id === definition.currentRevisionId) ?? definition.revisions.at(-1) ?? null;
            const pending = catalogPendingId === definition.id;
            const stateClass = userInstallation ? "is-installed" : "";
            return <div className={`marketplace-skill-row ${definition.id === selected?.id ? "is-selected" : ""}`} key={definition.id}>
              <button className="marketplace-skill-select" type="button" onClick={() => { setSelectedId(definition.id); setUninstallConfirmId(null); setUnbindConfirmKey(null); }}><span><strong>{definition.name}</strong><small>{definition.description || definition.slug}</small></span></button>
              <button className={`marketplace-install-toggle ${stateClass}`} type="button" aria-label={`${definition.name} ${userInstallation ? "미사용" : "설치"}`} aria-pressed={Boolean(userInstallation)} aria-busy={pending} disabled={pending || !userInstallation && !currentDefinitionRevision} onClick={() => void toggleCatalogInstallation(definition)}>{pending ? <LoaderCircle className="is-running" size={12} /> : userInstallation ? <><span className="install-toggle-rest">설치됨</span><span className="install-toggle-hover">미사용</span></> : <span>설치</span>}</button>
            </div>;
          })}
        </aside>
        <section className="feature-detail mcp-detail">
          {!selected || !currentRevision ? <div className="feature-state">MCP를 선택해 주세요.</div> : (
            <>
              <header className="detail-heading">
                <div><h2>{selected.name}</h2><p>{selected.description || "설명 없음"}</p></div>
                <div className="detail-badges"><span>MCP r{currentRevision.revision}</span><span>{currentRevision.transport}</span><span className={skillWrapperApplied === true ? "is-wrapper-ready" : skillWrapperApplied === false ? "is-wrapper-missing" : undefined}>Skill 래퍼 {skillWrapperApplied === true ? "적용" : skillWrapperApplied === false ? "누락" : "확인 불가"}</span><span className={`status-${currentRevision.healthStatus}`}>health {stateLabel(currentRevision.healthStatus)}</span><span className={`status-${currentRevision.schemaStatus}`}>schema {stateLabel(currentRevision.schemaStatus)}</span></div>
              </header>
              {skillWrapperApplied === false && <div className="mcp-wrapper-warning" role="alert"><strong>Skill 래퍼가 없습니다.</strong><span>이 MCP를 실행할 때 사용 지침이 Context에 주입되지 않습니다. extensions/skills 아래에 source: skill-mcp:{selected.slug} 래퍼를 추가해 주세요.</span></div>}
              <div className="mcp-tool-section">
                <div className="mcp-section-heading"><strong><Wrench size={14} /> 설치 Tool allowlist</strong><small>{selectedTools.length} / {currentRevision.tools.length}</small></div>
                <div className="mcp-tool-list">{currentRevision.tools.map((tool) => <label key={tool.name}><input type="checkbox" checked={selectedTools.includes(tool.name)} onChange={(event) => { const checked = event.currentTarget.checked; setSelectedTools((current) => checked ? [...current, tool.name] : current.filter((name) => name !== tool.name)); }} /><span><strong>{tool.name}</strong><small>{tool.description || "설명 없음"}</small></span></label>)}</div>
                <div className="mcp-install-controls" aria-label="MCP 설치 대상">
                  <button className="is-primary lumina-primary-action" type="button" disabled={busy || selectedTools.length === 0 || selectedInstallations.some((item) => item.scopeType === "user")} onClick={() => void install("user")}><Plug size={14} /> {selectedInstallations.some((item) => item.scopeType === "user") ? "내 계정 설치됨" : "내 계정 설치"}</button>
                  <button type="button" aria-label={!projectId ? "Project를 선택해야 설치할 수 있습니다." : "내 프로젝트 MCP 설치"} data-tooltip={!projectId ? "Project를 선택해야 설치할 수 있습니다." : undefined} disabled={busy || !projectId || selectedTools.length === 0 || selectedInstallations.some((item) => item.scopeType === "project")} onClick={() => void install("project")}><Plug size={14} /> {selectedInstallations.some((item) => item.scopeType === "project") ? "내 프로젝트 설치됨" : "내 프로젝트 설치"}</button>
                </div>
              </div>
              <div className="mcp-installation-section">
                <div className="mcp-section-heading"><strong><ShieldCheck size={14} /> 설치 및 연결</strong><small>Secret 값은 저장·재표시하지 않습니다.</small></div>
                {selectedInstallations.length === 0 ? <p className="mcp-empty">설치 후 Secret Store reference와 연결 상태를 설정할 수 있습니다.</p> : selectedInstallations.map((installation) => (
                  <article className="mcp-installation-row" key={installation.id}>
                    <header><div><strong>{installation.scopeType === "project" ? "Project" : "내 계정"} · r{installation.configurationRevision}</strong><small>{installation.toolAllowlist.join(", ")}</small></div><div className="mcp-installation-actions"><span className={`mcp-installation-ready-state ${installation.ready ? "is-ready" : "is-pending"}`}>{installation.ready ? <Check size={13} /> : <LoaderCircle size={13} />} {installation.ready ? "사용 가능" : resolverLabel(installation.secretResolutionStatus)}</span><button className="tooltip-control" type="button" aria-label={installation.enabled ? "MCP 비활성화" : "MCP 활성화"} data-tooltip={installation.enabled ? "비활성화" : "활성화"} disabled={busy} onClick={() => void toggleInstallation(installation)}><Power size={14} /></button><button className={`mcp-uninstall-action text-danger ${uninstallConfirmId === installation.id ? "is-delete-armed" : ""}`} type="button" aria-label={uninstallConfirmId === installation.id ? "MCP 설치 해제 확인, 한 번 더 누르면 설치 해제" : "MCP 설치 해제"} data-tooltip={uninstallConfirmId === installation.id ? "한 번 더 눌러 설치 해제" : "설치 해제"} disabled={busy} onClick={() => void uninstall(installation)}><Trash2 size={14} />{uninstallConfirmId === installation.id ? <span>한 번 더 눌러 설치 해제</span> : null}</button></div></header>
                    <div className="mcp-health-line"><span>health <strong>{stateLabel(installation.healthStatus)}</strong></span><span>schema <strong>{stateLabel(installation.schemaStatus)}</strong></span><span>Secret <strong>{resolverLabel(installation.secretResolutionStatus)}</strong></span><span>{installation.enabled ? "활성" : "비활성"}</span></div>
                    {installation.boundSecrets.map((slot) => {
                      const key = `${installation.id}:${slot.name}`;
                      return <form className="mcp-secret-row" key={slot.name} onSubmit={(event) => void bindSecret(event, installation, slot.name)}><KeyRound size={14} /><span><strong>{slot.name}</strong><small>{resolverLabel(slot.resolverStatus)}</small></span>{slot.bound ? <button className={`mcp-secret-action text-danger ${unbindConfirmKey === key ? "is-delete-armed" : ""}`} type="button" disabled={busy} onClick={() => void unbindSecret(installation, slot.name)}>{unbindConfirmKey === key ? "한 번 더 눌러 연결 해제" : "연결 해제"}</button> : slot.canBind ? <><input type="text" autoComplete="off" aria-label={`${slot.name} Secret Store reference`} placeholder="env://VARIABLE_NAME" value={secretInputs[key] ?? ""} onChange={(event) => { const value = event.currentTarget.value; setSecretInputs((current) => ({ ...current, [key]: value })); }} /><button type="submit" disabled={busy || !(secretInputs[key] ?? "").trim()}>연결</button></> : <span className="mcp-secret-guidance">관리자 env:// 연결 필요</span>}</form>;
                    })}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </ResizableSplitPane>
    </div>
  );
}
