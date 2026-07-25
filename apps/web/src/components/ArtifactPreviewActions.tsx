import { Code2, Download, ExternalLink, Eye } from "lucide-react";

import { ShareActionIcon } from "./ActionIcons";

interface ArtifactPreviewActionsProps {
  sourceActive: boolean;
  sourceDisabled?: boolean;
  shareDisabled?: boolean;
  downloadDisabled?: boolean;
  openWindowHref?: string | null;
  onToggleSource: () => void | Promise<void>;
  onShare: () => void | Promise<void>;
  onDownload: () => void | Promise<void>;
}

export function ArtifactPreviewActions({
  sourceActive,
  sourceDisabled = false,
  shareDisabled = false,
  downloadDisabled = false,
  openWindowHref = null,
  onToggleSource,
  onShare,
  onDownload,
}: ArtifactPreviewActionsProps) {
  return <>
    <button
      className="artifact-view-control tooltip-control"
      type="button"
      aria-label={sourceActive ? "미리보기" : "소스코드 보기"}
      data-tooltip={sourceDisabled ? "이 형식은 소스 보기 없음" : sourceActive ? "미리보기" : "소스코드 보기"}
      disabled={sourceDisabled}
      onClick={() => void onToggleSource()}
    >
      {sourceActive ? <Eye size={17} /> : <Code2 size={17} />}
    </button>
    <button
      className="tooltip-control"
      type="button"
      aria-label="공유 링크 복사"
      data-tooltip={shareDisabled ? "공유할 수 없는 산출물입니다." : "공유 링크 복사"}
      disabled={shareDisabled}
      onClick={() => void onShare()}
    >
      <ShareActionIcon size={17} />
    </button>
    <button
      className="artifact-file-control tooltip-control"
      type="button"
      aria-label="다운로드"
      data-tooltip="다운로드"
      disabled={downloadDisabled}
      onClick={() => void onDownload()}
    >
      <Download size={17} />
    </button>
    {openWindowHref ? (
      <a
        className="artifact-open-window-control tooltip-control"
        href={openWindowHref}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="새 창에서 열기"
        data-tooltip="새 창에서 열기"
      >
        <ExternalLink size={17} />
      </a>
    ) : (
      <button
        className="tooltip-control"
        type="button"
        aria-label="새 창에서 열기"
        data-tooltip="이 형식은 새 창 미리보기를 지원하지 않습니다."
        disabled
      >
        <ExternalLink size={17} />
      </button>
    )}
  </>;
}
