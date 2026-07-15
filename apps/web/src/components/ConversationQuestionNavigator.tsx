import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import type { TurnSet } from "../api-types";
import { GlobalTooltipLayer } from "./GlobalTooltip";

interface QuestionNavigatorItem {
  anchorId: string;
  questionPreview: string;
  answerPreview: string;
}

type NavigatorStyle = CSSProperties & Record<`--${string}`, string | number>;

const previewCharacterLimit = 180;
const questionPreviewCharacterLimit = 96;
const answerPreviewCharacterLimit = 140;

function plainTextPreview(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, " 코드 ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " 이미지 ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*`~>|]/g, "")
    .replace(/:\s*(?=(?:또한|그리고|$))/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

export function questionNavigatorPreview(text: string, characterLimit = previewCharacterLimit) {
  const preview = plainTextPreview(text);
  if (preview.length <= characterLimit) return preview;
  return `${preview.slice(0, characterLimit).trimEnd()}…`;
}

export function markerScaleForDistance(distance: number) {
  if (distance === 0) return 1;
  if (distance === 1) return 0.76;
  if (distance === 2) return 0.56;
  if (distance === 3) return 0.4;
  return 0.28;
}

export function easeInOutCubic(progress: number) {
  return progress < 0.5
    ? 4 * progress * progress * progress
    : 1 - ((-2 * progress + 2) ** 3) / 2;
}

function questionItems(turnSets: TurnSet[]) {
  return turnSets.flatMap<QuestionNavigatorItem>((turnSet) => (
    turnSet.messages.flatMap((message, messageIndex) => {
      if (message.role !== "user") return [];
      const questionPreview = questionNavigatorPreview(message.text, questionPreviewCharacterLimit);
      if (!questionPreview) return [];
      const answer = turnSet.messages
        .slice(messageIndex + 1)
        .find((candidate) => candidate.role === "assistant");
      const answerPreview = questionNavigatorPreview(answer?.text ?? "", answerPreviewCharacterLimit);
      return [{ anchorId: message.id, questionPreview, answerPreview }];
    })
  ));
}

export function ConversationQuestionNavigator({
  turnSets,
  scrollContainerRef,
  onNavigateStart,
}: {
  turnSets: TurnSet[];
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  onNavigateStart: () => void;
}) {
  const items = useMemo(() => questionItems(turnSets), [turnSets]);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const markerRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const itemKey = items.map((item) => item.anchorId).join("|");

  const cancelScrollAnimation = () => {
    if (animationFrameRef.current !== null) window.cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  };

  useEffect(() => {
    cancelScrollAnimation();
    setActiveIndex(null);
  }, [itemKey]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return undefined;
    const cancelForUserInput = () => cancelScrollAnimation();
    container.addEventListener("wheel", cancelForUserInput, { passive: true });
    container.addEventListener("pointerdown", cancelForUserInput, { passive: true });
    container.addEventListener("touchstart", cancelForUserInput, { passive: true });
    return () => {
      cancelScrollAnimation();
      container.removeEventListener("wheel", cancelForUserInput);
      container.removeEventListener("pointerdown", cancelForUserInput);
      container.removeEventListener("touchstart", cancelForUserInput);
    };
  }, [scrollContainerRef]);

  const navigateToQuestion = (item: QuestionNavigatorItem) => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const target = [...container.querySelectorAll<HTMLElement>("[data-question-anchor]")]
      .find((element) => element.dataset.questionAnchor === item.anchorId);
    if (!target) return;

    onNavigateStart();
    cancelScrollAnimation();
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const startTop = container.scrollTop;
    const maximumTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maximumTop, startTop + targetRect.top - containerRect.top - 24));
    const distance = targetTop - startTop;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduceMotion || Math.abs(distance) < 2) {
      container.scrollTop = targetTop;
      return;
    }

    const duration = Math.min(340, Math.max(190, 190 + Math.abs(distance) / 7));
    const startedAt = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      container.scrollTop = startTop + distance * easeInOutCubic(progress);
      if (progress < 1) {
        animationFrameRef.current = window.requestAnimationFrame(step);
      } else {
        animationFrameRef.current = null;
      }
    };
    animationFrameRef.current = window.requestAnimationFrame(step);
  };

  if (items.length === 0) return null;

  return (
    <nav
      className="question-navigator"
      aria-label={`사용자 질문 ${items.length}개 바로가기`}
      onMouseLeave={() => setActiveIndex(null)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setActiveIndex(null);
      }}
    >
      <div className="question-navigator-track" style={{ "--question-count": items.length } as NavigatorStyle}>
        {items.map((item, index) => {
          const distance = activeIndex === null ? Number.POSITIVE_INFINITY : Math.abs(activeIndex - index);
          const tooltipId = `question-navigator-tooltip-${item.anchorId}`;
          const markerStyle = {
            "--question-marker-scale": markerScaleForDistance(distance),
            "--question-marker-opacity": distance === 0 ? 1 : distance <= 3 ? 0.72 : 0.42,
          } as NavigatorStyle;
          return (
            <button
              className={`question-navigator-marker ${index < 2 ? "is-tooltip-start" : ""} ${index >= items.length - 2 ? "is-tooltip-end" : ""}`}
              type="button"
              ref={(node) => { markerRefs.current[index] = node; }}
              aria-label={`질문 ${index + 1}로 이동: ${item.questionPreview}`}
              aria-describedby={activeIndex === index ? tooltipId : undefined}
              style={markerStyle}
              onMouseEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              onClick={() => navigateToQuestion(item)}
              key={item.anchorId}
            >
              {activeIndex === index && (
                <GlobalTooltipLayer anchor={markerRefs.current[index]} className="question-navigator-tooltip" id={tooltipId} open preferredPlacement="right">
                  <strong>질문 {index + 1}</strong>
                  <span className="question-navigator-preview-row">
                    <small>질문</small>
                    <span>{item.questionPreview}</span>
                  </span>
                  <span className="question-navigator-preview-row is-answer">
                    <small>답변</small>
                    <span>{item.answerPreview || "아직 답변이 없습니다."}</span>
                  </span>
                </GlobalTooltipLayer>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
