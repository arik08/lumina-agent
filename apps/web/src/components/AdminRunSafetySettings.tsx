import { AlertTriangle, CircleStop, LoaderCircle, Save, ShieldAlert } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import type { AdminRunSafetySettings as RunSafetySettings } from "../api-types";

interface AdminRunSafetySettingsProps {
  onToast: (message: string) => void;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

export function AdminRunSafetySettings({ onToast }: AdminRunSafetySettingsProps) {
  const [runSafety, setRunSafety] = useState<RunSafetySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [killArmed, setKillArmed] = useState(false);
  const [killRunning, setKillRunning] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.admin.getRunSafetySettings(controller.signal)
      .then(setRunSafety)
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const saveRunSafety = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!runSafety) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.admin.updateRunSafetySettings(runSafety);
      setRunSafety(updated);
      onToast("Run 안전 한도를 저장했습니다. 새 Run부터 적용됩니다.");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const emergencyStopAllRuns = async () => {
    if (!killArmed) {
      setKillArmed(true);
      return;
    }
    setKillRunning(true);
    setError(null);
    try {
      const result = await api.admin.emergencyStopAllRuns();
      setKillArmed(false);
      onToast(`Run ${result.cancelledRunCount}개 · 대기 요청 ${result.cancelledQueuedMessageCount}개를 중단했습니다.`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setKillRunning(false);
    }
  };

  return (
    <section className="settings-card settings-admin-card settings-run-safety-card" aria-labelledby="admin-run-safety-title">
      <header><span><ShieldAlert size={15} /><h2 id="admin-run-safety-title">실행 안전</h2></span><small>모든 사용자에게 적용</small></header>
      <div className="admin-run-safety-heading">
        <div><strong>Run 폭주 방지 한도</strong><small>정상적인 장시간 작업은 방해하지 않도록 넉넉한 기본값을 사용합니다.</small></div>
      </div>
      {loading && <p className="settings-run-safety-loading"><LoaderCircle className="is-running" size={14} /> 실행 안전 설정을 불러오는 중입니다.</p>}
      {runSafety && (
        <form className="admin-run-safety-form" onSubmit={(event) => void saveRunSafety(event)}>
          <label><span>최대 모델 Turn</span><input type="number" min="10" max="10000" value={runSafety.maxModelTurns} onChange={(event) => setRunSafety({ ...runSafety, maxModelTurns: Number(event.currentTarget.value) })} /><small>Run당 모델 호출 단계</small></label>
          <label><span>최대 누적 Token</span><input type="number" min="100000" max="100000000" step="100000" value={runSafety.maxTotalTokens} onChange={(event) => setRunSafety({ ...runSafety, maxTotalTokens: Number(event.currentTarget.value) })} /><small>입력과 출력 Token 합계</small></label>
          <label><span>최대 실행 시간</span><div className="admin-run-safety-input"><input type="number" min="30" max="525600" step="1" value={runSafety.maxElapsedMinutes} onChange={(event) => setRunSafety({ ...runSafety, maxElapsedMinutes: Number(event.currentTarget.value) })} /><span>분</span></div><small>실제 실행 시작 이후 기준</small></label>
          <label><span>최대 예상 비용</span><div className="admin-run-safety-input"><span>$</span><input type="number" min="1" max="10000" step="1" value={runSafety.maxCostUsd} onChange={(event) => setRunSafety({ ...runSafety, maxCostUsd: Number(event.currentTarget.value) })} /></div><small>Provider 보고값 또는 가격표 추정</small></label>
          <footer><p>저장한 값은 새로 시작하는 Run의 snapshot에 고정됩니다.</p><button type="submit" disabled={saving}>{saving ? <LoaderCircle className="is-running" size={14} /> : <Save size={14} />} 저장</button></footer>
        </form>
      )}
      <div className="admin-emergency-stop-panel">
        <div><strong>비상 전체 중단</strong><small>이 조직의 실행 중·대기 중 Run과 다음 요청 Queue를 즉시 중단합니다.</small></div>
        <button className={killArmed ? "is-armed" : ""} type="button" disabled={killRunning} onClick={() => void emergencyStopAllRuns()}>{killRunning ? <LoaderCircle className="is-running" size={15} /> : <CircleStop size={15} />} {killArmed ? "한 번 더 눌러 모든 작업 중단" : "모든 세션 작업 Kill"}</button>
        {killArmed && <p className="admin-inline-confirm"><AlertTriangle size={14} /> 같은 버튼을 한 번 더 누르면 복구 대기 작업까지 모두 취소됩니다.</p>}
      </div>
      {error && <p className="settings-inline-error" role="alert">{error}</p>}
    </section>
  );
}
