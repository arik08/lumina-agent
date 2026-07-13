import { LoaderCircle, Save } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { InstructionDocument, InstructionScope } from "../api-types";

interface InstructionEditorProps {
  scope: InstructionScope;
  projectId?: string;
  heading: string;
  description: string;
  note: string;
  onSaved?: () => void;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "지침을 처리하지 못했습니다.";
}

export function InstructionEditor({
  scope,
  projectId,
  heading,
  description,
  note,
  onSaved,
}: InstructionEditorProps) {
  const [snapshot, setSnapshot] = useState<InstructionDocument | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchSnapshot = useCallback(
    async (signal?: AbortSignal, preserveDraft = false) => {
      const loaded = scope === "personal"
        ? await api.instructions.getPersonal(signal)
        : scope === "organization"
          ? await api.instructions.getOrganization(signal)
          : projectId
            ? await api.instructions.getProject(projectId, signal)
            : null;
      if (!loaded) return null;
      setSnapshot(loaded);
      if (!preserveDraft) setDraft(loaded.content);
      return loaded;
    },
    [projectId, scope],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setNotice(null);
    void fetchSnapshot(controller.signal)
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [fetchSnapshot]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!snapshot || !snapshot.editable || draft === snapshot.content) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    const payload = {
      content: draft,
      expectedRevision: snapshot.revision,
      expectedDigest: snapshot.digest,
    };
    try {
      const updated = scope === "personal"
        ? await api.instructions.updatePersonal(payload)
        : scope === "organization"
          ? await api.instructions.updateOrganization(payload)
          : projectId
            ? await api.instructions.updateProject(projectId, payload)
            : null;
      if (!updated) return;
      setSnapshot(updated);
      setDraft(updated.content);
      setNotice("지침을 저장했습니다.");
      onSaved?.();
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.code === "instruction_conflict") {
        try {
          await fetchSnapshot(undefined, true);
          setError("다른 작업에서 지침이 변경되었습니다. 입력한 내용은 유지했습니다. 최신 내용을 확인한 뒤 다시 저장해 주세요.");
        } catch (reloadError) {
          setError(errorMessage(reloadError));
        }
      } else {
        setError(errorMessage(requestError));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="instruction-editor" aria-labelledby={`${scope}-instruction-heading`}>
      <header>
        <div>
          <h2 id={`${scope}-instruction-heading`}>{heading}</h2>
          <p>{description}</p>
        </div>
      </header>
      {loading ? (
        <p className="instruction-loading"><LoaderCircle className="is-running" size={15} /> 지침을 불러오는 중입니다.</p>
      ) : (
        <form onSubmit={(event) => void save(event)}>
          <label>
            <span>지침 내용</span>
            <textarea
              value={draft}
              rows={10}
              maxLength={40_000}
              readOnly={!snapshot?.editable}
              placeholder="새 Run에 일관되게 적용할 작업 방식과 산출물 원칙을 입력하세요."
              onChange={(event) => setDraft(event.currentTarget.value)}
            />
          </label>
          <div className="instruction-editor-footer">
            <small>{note}</small>
            <span>{draft.length.toLocaleString()} / 40,000</span>
            {snapshot?.editable && (
              <button className="primary-compact lumina-primary-action" type="submit" disabled={saving || draft === snapshot.content}>
                {saving ? <LoaderCircle className="is-running" size={15} /> : <Save size={15} />}
                지침 저장
              </button>
            )}
          </div>
          {error && <p className="instruction-message is-error" role="alert">{error}</p>}
          {notice && <p className="instruction-message" role="status">{notice}</p>}
        </form>
      )}
    </section>
  );
}
