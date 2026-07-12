import { Component, type ErrorInfo, type PropsWithChildren } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

interface AppErrorBoundaryState {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<PropsWithChildren, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[Lumina] 화면 렌더링 오류", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-error-boundary" role="alert">
          <section>
            <TriangleAlert size={28} aria-hidden="true" />
            <div>
              <h1>화면을 표시하지 못했습니다.</h1>
              <p>작업 내용은 서버에 보관되어 있습니다. 화면을 다시 불러와 복구해 주세요.</p>
            </div>
            <button type="button" onClick={() => window.location.reload()}>
              <RefreshCw size={16} aria-hidden="true" />
              화면 다시 불러오기
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
