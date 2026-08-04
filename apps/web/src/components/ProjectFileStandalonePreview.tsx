import { Code2, Download, Eye, FileText, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError } from "../api";
import type { ProjectFileDetail } from "../api-types";
import { projectFilesApi } from "../feature-api";
import { isMarkdownFile, ProjectFilePreviewContent, saveProjectFileDownload, useProjectFilePreview } from "./ProjectFilePreview";

interface ProjectFileStandalonePreviewProps {
  fileId: string;
  projectId: string;
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "파일 요청을 처리하지 못했습니다.";
}

export function ProjectFileStandalonePreview({ fileId, projectId }: ProjectFileStandalonePreviewProps) {
  const [detail, setDetail] = useState<ProjectFileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [markdownSource, setMarkdownSource] = useState(false);
  const { frameRef, preview } = useProjectFilePreview(projectId, detail);

  useEffect(() => {
    const controller = new AbortController();
    projectFilesApi.get(projectId, fileId, controller.signal)
      .then((value) => {
        setDetail(value);
        document.title = `${value.displayName} · Lumina`;
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [fileId, projectId]);

  const download = async () => {
    if (!detail) return;
    try {
      saveProjectFileDownload(await projectFilesApi.download(projectId, detail.id));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <main className="project-file-preview-route">
      {!detail && !error ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 파일을 여는 중</div> : null}
      {error ? <div className="feature-error" role="alert">{error}</div> : null}
      {detail ? (
        <div className="file-viewer-document">
          <header className="file-viewer-heading">
            <span className="file-viewer-icon"><FileText size={22} /></span>
            <div><h2>{detail.displayName}</h2></div>
            <div className="file-viewer-actions">
              {isMarkdownFile(detail) ? (
                <button className={`file-preview-mode-toggle tooltip-control ${markdownSource ? "is-active" : ""}`} type="button" aria-label={markdownSource ? "렌더링 보기" : "원문 보기"} aria-pressed={markdownSource} data-tooltip={markdownSource ? "렌더링 보기" : "원문 보기"} onClick={() => setMarkdownSource((current) => !current)}>
                  {markdownSource ? <Eye size={14} /> : <Code2 size={14} />}
                </button>
              ) : null}
              <button type="button" onClick={() => void download()}><Download size={14} /> 다운로드</button>
            </div>
          </header>
          <div className="file-preview-surface thin-scrollbar">
            <ProjectFilePreviewContent preview={preview} detail={detail} markdownSource={markdownSource} frameRef={frameRef} />
          </div>
        </div>
      ) : null}
    </main>
  );
}
