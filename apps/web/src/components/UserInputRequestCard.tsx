import {
  Check,
  ChevronDown,
  ChevronUp,
  MessageCircleQuestion,
  Send,
  Settings,
  Sparkles,
} from "lucide-react";
import { useMemo, useRef, useState, type FormEvent } from "react";
import type {
  ClarificationMode,
  UserInputAnswer,
  UserInputRequest,
} from "../api-types";

interface UserInputRequestCardProps {
  request: UserInputRequest;
  clarificationMode: ClarificationMode;
  busy: boolean;
  onSubmit: (answers: UserInputAnswer[]) => Promise<boolean>;
  onModeChange: (mode: ClarificationMode) => Promise<unknown>;
}

const modeOptions: Array<{
  value: ClarificationMode;
  label: string;
  description: string;
}> = [
  { value: "autonomous", label: "알아서 진행", description: "치명적인 경우에만 묻습니다." },
  { value: "balanced", label: "균형 있게", description: "결과가 크게 달라질 때 묻습니다." },
  { value: "confirming", label: "먼저 확인", description: "중요한 선택은 확인하고 진행합니다." },
];

function answerForOption(questionId: string, optionId: string): UserInputAnswer {
  return { questionId, optionId };
}

export function UserInputRequestCard({
  request,
  clarificationMode,
  busy,
  onSubmit,
  onModeChange,
}: UserInputRequestCardProps) {
  const [answers, setAnswers] = useState<Record<string, UserInputAnswer>>(() =>
    Object.fromEntries(request.answers.map((answer) => [answer.questionId, answer])),
  );
  const [customText, setCustomText] = useState<Record<string, string>>(() =>
    Object.fromEntries(request.answers
      .filter((answer) => answer.kind === "custom" && answer.text)
      .map((answer) => [answer.questionId, answer.text ?? ""])),
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [collapsing, setCollapsing] = useState(false);
  const [compact, setCompact] = useState(request.status !== "pending");
  const submissionStarted = useRef(false);
  const pending = request.status === "pending" && !compact;
  const complete = request.questions.every((question) => answers[question.id]);
  const orderedAnswers = useMemo(
    () => request.questions.map((question) => answers[question.id]).filter(Boolean),
    [answers, request.questions],
  );

  const submitAnswers = async () => {
    if (!pending || !complete || busy || submissionStarted.current) return;
    submissionStarted.current = true;
    const succeeded = await onSubmit(orderedAnswers);
    if (!succeeded) {
      submissionStarted.current = false;
      return;
    }
    setCollapsing(true);
    window.setTimeout(() => {
      setCompact(true);
      setCollapsing(false);
    }, 240);
  };

  const chooseCustom = (questionId: string, event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = customText[questionId]?.trim();
    if (!text) return;
    setAnswers((current) => ({ ...current, [questionId]: { questionId, customText: text } }));
  };

  const useAiJudgment = () => {
    setAnswers(Object.fromEntries(request.questions.map((question) => [
      question.id,
      { questionId: question.id, useAiJudgment: true },
    ])));
  };

  const updateCustomText = (questionId: string, value: string) => {
    setCustomText((current) => ({ ...current, [questionId]: value }));
  };

  if (compact) {
    return (
      <button
        className="clarification-card is-compact"
        type="button"
        aria-label="답변한 확인 질문 다시 보기"
        aria-expanded="false"
        onClick={() => setCompact(false)}
      >
        <MessageCircleQuestion size={17} aria-hidden="true" />
        <span>확인 질문 {request.questions.length}개에 답변했습니다.</span>
        <Check size={15} aria-hidden="true" />
        <ChevronDown size={15} aria-hidden="true" />
      </button>
    );
  }

  return (
    <section
      className={`clarification-card${collapsing ? " is-collapsing" : ""}`}
      aria-label="AI 확인 질문"
    >
      <header className="clarification-header">
        <span className="clarification-title">
          <MessageCircleQuestion size={19} aria-hidden="true" />
          <strong>확인 질문</strong>
        </span>
        {pending && (
          <span className="clarification-header-actions">
            <button
              className="clarification-ai-judgment"
              type="button"
              disabled={busy}
              onClick={useAiJudgment}
            >
              <Sparkles size={14} /> AI가 판단
            </button>
            <button
              className="clarification-settings-trigger"
              type="button"
              aria-label="AI 확인 질문 설정"
              aria-expanded={settingsOpen}
              data-tooltip="질문 깊이 설정"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              <Settings size={16} />
            </button>
          </span>
        )}
      </header>

      {settingsOpen && (
        <div className="clarification-settings" aria-label="AI 확인 질문 기본값">
          <div>
            <strong>AI가 되묻는 정도</strong>
            <small>계정 기본값으로 계속 적용됩니다.</small>
          </div>
          <div className="clarification-mode-options">
            {modeOptions.map((option) => (
              <button
                className={clarificationMode === option.value ? "is-selected" : ""}
                type="button"
                key={option.value}
                onClick={() => void onModeChange(option.value)}
              >
                <span>{option.label}</span>
                <small>{option.description}</small>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="clarification-questions">
        {request.questions.map((question, index) => {
          const selected = answers[question.id];
          return (
            <fieldset className="clarification-question" key={question.id} disabled={!pending || busy}>
              <legend>
                <span>질문 {index + 1} / {request.questions.length}</span>
                <strong>{question.prompt}</strong>
              </legend>
              <div className="clarification-options">
                {question.options.map((option) => (
                  <button
                    className={selected?.optionId === option.id ? "is-selected" : ""}
                    type="button"
                    key={option.id}
                    aria-pressed={selected?.optionId === option.id}
                    onClick={() => setAnswers((current) => ({
                      ...current,
                      [question.id]: answerForOption(question.id, option.id),
                    }))}
                  >
                    <span>{option.label}</span>
                    {option.description && <small>{option.description}</small>}
                  </button>
                ))}
              </div>
              <form className="clarification-custom-answer" onSubmit={(event) => chooseCustom(question.id, event)}>
                <input
                  type="text"
                  value={customText[question.id] ?? ""}
                  placeholder="직접 답변하기"
                  aria-label={`${index + 1}번 질문에 직접 답변`}
                  onChange={(event) => updateCustomText(question.id, event.currentTarget.value)}
                />
                <button type="submit" disabled={!pending || !customText[question.id]?.trim()}>
                  적용
                </button>
              </form>
              {(selected?.kind === "ai" || selected?.useAiJudgment) && (
                <div className="clarification-ai-answer">
                  <Sparkles size={14} /> AI가 판단하도록 맡겼습니다.
                </div>
              )}
            </fieldset>
          );
        })}
      </div>

      <footer className="clarification-footer">
        {!pending && (
          <button type="button" onClick={() => setCompact(true)}>
            <ChevronUp size={15} /> 다시 접기
          </button>
        )}
        <span>{orderedAnswers.length} / {request.questions.length} 답변</span>
        {pending && (
          <button
            className="clarification-submit"
            type="button"
            disabled={!complete || busy}
            onClick={() => void submitAnswers()}
          >
            <Send size={14} /> {busy ? "보내는 중" : "보내기"}
          </button>
        )}
      </footer>
    </section>
  );
}
