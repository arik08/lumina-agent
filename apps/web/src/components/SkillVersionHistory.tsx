import { AlertTriangle, Check, GitCompareArrows, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { SkillVersion, SkillVersionComparison } from "../api-types";
import { SelectMenu } from "./SelectMenu";
import "./SkillVersionHistory.css";

interface SkillVersionHistoryProps {
  versions: SkillVersion[];
  latestPublishedVersionId: string | null;
  comparison: SkillVersionComparison | null;
  busy: boolean;
  canRollback: boolean;
  onCompare: (fromVersionId: string, toVersionId: string) => void;
  onRollback: (target: SkillVersion, changeSummary: string) => void;
}

function versionState(version: SkillVersion, latestPublishedVersionId: string | null) {
  if (version.id === latestPublishedVersionId) return "현재 공식";
  if (version.changeType === "rollback") return "복원";
  if (version.publishedAt || version.status === "published") return "과거 공식";
  return "저장본";
}

function formattedVersionTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function SkillVersionHistory({
  versions,
  latestPublishedVersionId,
  comparison,
  busy,
  canRollback,
  onCompare,
  onRollback,
}: SkillVersionHistoryProps) {
  const orderedVersions = useMemo(
    () => [...versions].sort((left, right) => right.version - left.version),
    [versions],
  );
  const defaultTo = latestPublishedVersionId ?? orderedVersions[0]?.id ?? "";
  const defaultFrom = orderedVersions.find((version) => version.id !== defaultTo)?.id ?? defaultTo;
  const [fromVersionId, setFromVersionId] = useState(defaultFrom);
  const [toVersionId, setToVersionId] = useState(defaultTo);
  const [activePath, setActivePath] = useState("");
  const [rollbackTargetId, setRollbackTargetId] = useState<string | null>(null);
  const [rollbackSummary, setRollbackSummary] = useState("");

  useEffect(() => {
    setFromVersionId(defaultFrom);
    setToVersionId(defaultTo);
    setRollbackTargetId(null);
  }, [defaultFrom, defaultTo]);

  useEffect(() => {
    setActivePath(comparison?.files[0]?.path ?? "");
  }, [comparison]);

  const versionOptions = orderedVersions.map((version) => ({
    value: version.id,
    label: `v${version.version} · ${versionState(version, latestPublishedVersionId)}`,
  }));
  const activeDiff = comparison?.files.find((file) => file.path === activePath)
    ?? comparison?.files[0]
    ?? null;

  return <div className="skill-version-workspace">
    <aside className="skill-version-history" aria-label="Skill 버전 이력">
      <header><strong>버전 이력</strong><span>{versions.length}개</span></header>
      <div className="skill-version-list">
        {orderedVersions.map((version) => {
          const state = versionState(version, latestPublishedVersionId);
          const rollbackArmed = rollbackTargetId === version.id;
          return <article className={version.id === latestPublishedVersionId ? "is-current" : ""} key={version.id}>
            <div className="skill-version-row-heading">
              <strong>v{version.version}</strong>
              <span className={`skill-version-state is-${version.changeType}`}>{state}</span>
            </div>
            <p>{version.changeSummary || "변경 요약 없음"}</p>
            <small>{version.createdByDisplayName || "알 수 없는 사용자"} · {formattedVersionTime(version.createdAt)}</small>
            {version.restoredFromVersionId && <small>과거 버전 내용을 복원한 이력</small>}
            {canRollback && version.id !== latestPublishedVersionId && (
              rollbackArmed ? <div className="skill-version-rollback-confirm">
                <input
                  aria-label={`v${version.version} 복원 사유`}
                  placeholder="복원 사유"
                  value={rollbackSummary}
                  onChange={(event) => setRollbackSummary(event.currentTarget.value)}
                />
                <div>
                  <button type="button" disabled={busy} onClick={() => setRollbackTargetId(null)}>취소</button>
                  <button className="is-warning" type="button" disabled={busy} onClick={() => onRollback(version, rollbackSummary)}><AlertTriangle size={13} /> 새 버전으로 복원</button>
                </div>
              </div> : <button className="skill-version-rollback" type="button" disabled={busy} onClick={() => {
                setRollbackTargetId(version.id);
                setRollbackSummary(`v${version.version} 기반 복원`);
              }}><RotateCcw size={13} /> 이 버전으로 복원</button>
            )}
          </article>;
        })}
      </div>
    </aside>

    <section className="skill-version-compare" aria-label="Skill 버전 비교">
      <header className="skill-version-compare-toolbar">
        <div>
          <SelectMenu size="small" width="auto" value={fromVersionId} options={versionOptions} ariaLabel="비교 기준 버전" onChange={setFromVersionId} />
          <span>→</span>
          <SelectMenu size="small" width="auto" value={toVersionId} options={versionOptions} ariaLabel="비교 대상 버전" onChange={setToVersionId} />
        </div>
        <button type="button" disabled={busy || !fromVersionId || !toVersionId || fromVersionId === toVersionId} onClick={() => onCompare(fromVersionId, toVersionId)}><GitCompareArrows size={14} /> 비교</button>
      </header>

      {!comparison ? <div className="skill-version-empty">서로 다른 두 버전을 선택해 변경 내용을 비교해 보세요.</div> : comparison.files.length === 0 ? <div className="skill-version-empty"><Check size={15} /> 두 버전의 파일 내용이 같습니다.</div> : <>
        <div className="skill-version-diff-summary">
          <strong>v{comparison.fromVersion.version} → v{comparison.toVersion.version}</strong>
          <span>{comparison.summary.filesChanged}개 파일</span>
          <span className="is-add">+{comparison.summary.additions}</span>
          <span className="is-delete">−{comparison.summary.deletions}</span>
        </div>
        <div className="skill-version-diff-body">
          <nav aria-label="변경된 파일">
            {comparison.files.map((file) => <button className={file.path === activeDiff?.path ? "is-selected" : ""} type="button" key={file.path} onClick={() => setActivePath(file.path)}>
              <span className={`skill-diff-status is-${file.status}`}>{file.status === "added" ? "A" : file.status === "deleted" ? "D" : "M"}</span>
              <span>{file.path}</span>
              <small><b>+{file.additions}</b> <i>−{file.deletions}</i></small>
            </button>)}
          </nav>
          <div className="skill-code-diff" role="table" aria-label={`${activeDiff?.path ?? "파일"} 코드 변경 내용`}>
            {activeDiff?.hunks.map((hunk, hunkIndex) => <div className="skill-code-hunk" key={`${hunk.oldStart}:${hunk.newStart}:${hunkIndex}`}>
              <div className="skill-code-hunk-heading">@@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@</div>
              {hunk.lines.map((line, lineIndex) => <div className={`skill-code-line is-${line.kind}`} role="row" key={`${line.oldLine}:${line.newLine}:${lineIndex}`}>
                <span role="cell">{line.oldLine ?? ""}</span>
                <span role="cell">{line.newLine ?? ""}</span>
                <span aria-hidden="true">{line.kind === "add" ? "+" : line.kind === "delete" ? "−" : " "}</span>
                <code role="cell">{line.content || " "}</code>
              </div>)}
            </div>)}
          </div>
        </div>
      </>}
    </section>
  </div>;
}
