import type { CSSProperties, ReactNode, RefObject } from "react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, FileText, LoaderCircle, WandSparkles } from "lucide-react";

import type { OutputMode, PromptEnhancementOption } from "../api-types";

export interface ComposerPickerOption {
  id: string;
  label: string;
  triggerLabel?: string;
  description?: string;
}

export const analysisDepthOptions: ComposerPickerOption[] = [
  { id: "auto", label: "자동", description: "요청에 맞춰 분석 범위를 결정합니다." },
  { id: "brief", label: "간단", description: "핵심 사실만 빠르게 확인합니다." },
  { id: "standard", label: "충분", description: "필요한 근거와 예외를 함께 확인합니다." },
  { id: "deep", label: "심층", description: "다양한 근거와 반례까지 폭넓게 검증합니다." },
];

export const answerLengthOptions: ComposerPickerOption[] = [
  { id: "auto", label: "자동", description: "요청에 맞춰 답변 분량을 결정합니다." },
  { id: "brief", label: "짧게", description: "결론과 핵심만 간결하게 답합니다." },
  { id: "standard", label: "보통", description: "이해에 필요한 설명을 함께 답합니다." },
  { id: "detailed", label: "상세", description: "배경과 예외까지 상세하게 답합니다." },
];

export const defaultArtifactOutputTokens = 10_000;
const promptEnhancementOptions: Array<{
  id: PromptEnhancementOption;
  label: string;
  description: string;
}> = [
  { id: "structure", label: "요청 구조화", description: "목적, 범위와 수행 항목을 정리합니다." },
  { id: "evidence", label: "근거 기준 보강", description: "수치, 출처와 검증 조건을 추가합니다." },
  { id: "missing_context", label: "누락 조건 보완", description: "기간, 대상, 단위와 가정을 명확히 합니다." },
  { id: "output_format", label: "출력 형식 구체화", description: "산출물의 구성과 형식을 정리합니다." },
];
const artifactLengthSteps = [
  { value: 8_000, label: "8k", warning: null },
  { value: 10_000, label: "10k", warning: null },
  { value: 12_000, label: "12k", warning: null },
  { value: 15_000, label: "15k", warning: null },
  { value: 20_000, label: "20k", warning: "장문" },
  { value: 30_000, label: "30k", warning: "장문" },
  { value: 40_000, label: "40k", warning: "최대" },
] as const;

export function PromptEnhancementMenu({
  disabled,
  instruction,
  loading,
  onApply,
}: {
  disabled: boolean;
  instruction: string;
  loading: boolean;
  onApply: (options: PromptEnhancementOption[], instruction: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<PromptEnhancementOption[]>([]);
  const [instructionDraft, setInstructionDraft] = useState(instruction);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const instructionId = useId();

  useEffect(() => {
    setInstructionDraft(instruction);
  }, [instruction]);

  useEffect(() => {
    if (!open) setSelected([]);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const toggle = (option: PromptEnhancementOption) => {
    setSelected((current) => (
      current.includes(option)
        ? current.filter((item) => item !== option)
        : [...current, option]
    ));
  };

  return (
    <div className={`composer-picker prompt-enhancement-picker${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        className="composer-picker-trigger composer-utility-button prompt-enhancement-control has-no-chevron tooltip-control"
        type="button"
        aria-label="프롬프트 개선"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        data-tooltip="프롬프트 개선"
        disabled={disabled || loading}
        onClick={() => setOpen((current) => !current)}
      >
        {loading
          ? <LoaderCircle className="is-running" size={16} aria-hidden="true" />
          : <WandSparkles size={16} aria-hidden="true" />}
      </button>
      {open && (
        <div className="composer-picker-menu prompt-enhancement-menu has-descriptions" id={menuId} role="menu" aria-label="프롬프트 개선">
          <div className="composer-picker-menu-label">프롬프트 개선</div>
          {promptEnhancementOptions.map((option) => {
            const checked = selected.includes(option.id);
            return (
              <button
                key={option.id}
                className={checked ? "is-selected" : ""}
                type="button"
                role="menuitemcheckbox"
                aria-checked={checked}
                onClick={() => toggle(option.id)}
              >
                <span className="composer-picker-option-copy">
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
                <Check size={14} aria-hidden="true" />
              </button>
            );
          })}
          <label className="prompt-enhancement-instruction" htmlFor={instructionId}>
            <span>직접 입력</span>
            <textarea
              id={instructionId}
              value={instructionDraft}
              maxLength={1_000}
              rows={2}
              placeholder="예: 핵심만 짧고 자연스럽게 정리"
              onChange={(event) => setInstructionDraft(event.currentTarget.value)}
            />
          </label>
          <div className="prompt-enhancement-actions">
            <button
              type="button"
              className="prompt-enhancement-apply"
              disabled={selected.length === 0 && !instructionDraft.trim()}
              onClick={() => {
                setOpen(false);
                onApply(selected, instructionDraft);
                setSelected([]);
              }}
            >
              적용
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ArtifactLengthSlider({
  value,
  onChange,
  outputMode,
  onOutputModeChange,
  controlRef,
  attention = false,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  outputMode: OutputMode;
  onOutputModeChange: (value: OutputMode) => void;
  controlRef?: RefObject<HTMLButtonElement | null>;
  attention?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({ left: 0, top: 0, visibility: "hidden" });
  const rootRef = useRef<HTMLDivElement>(null);
  const internalTriggerRef = useRef<HTMLButtonElement>(null);
  const triggerRef = controlRef ?? internalTriggerRef;
  const popoverRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const popoverId = useId();
  const selectedIndex = Math.max(
    0,
    artifactLengthSteps.findIndex((option) => option.value === (value ?? defaultArtifactOutputTokens)),
  );
  const selected = artifactLengthSteps[selectedIndex];
  const outputModeLabel = outputMode === "auto" ? "자동" : outputMode === "chat" ? "채팅" : "파일";
  const selectStep = (index: number) => {
    const boundedIndex = Math.min(artifactLengthSteps.length - 1, Math.max(0, index));
    const option = artifactLengthSteps[boundedIndex];
    onChange(option ? option.value : defaultArtifactOutputTokens);
  };
  const tone = selected.warning === "최대"
    ? "danger"
    : selected.warning
      ? "warning"
      : selected.value <= 10_000
        ? "muted"
        : "normal";
  const ariaValueText = `${selected.label}${selected.warning ? `, ${selected.warning}` : ""}, 채팅 답변이 아닌 생성 파일의 목표 분량`;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, triggerRef]);

  useLayoutEffect(() => {
    if (!open) return undefined;
    const updatePosition = () => {
      const trigger = triggerRef.current;
      const popover = popoverRef.current;
      if (!trigger || !popover) return;
      const triggerRect = trigger.getBoundingClientRect();
      const popoverRect = popover.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const maximumLeft = Math.max(viewportPadding, window.innerWidth - viewportPadding - popoverRect.width);
      const left = Math.min(
        maximumLeft,
        Math.max(viewportPadding, triggerRect.left + (triggerRect.width - popoverRect.width) / 2),
      );
      setPopoverStyle({
        left,
        top: Math.max(viewportPadding, triggerRect.top - gap - popoverRect.height),
        visibility: "visible",
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, triggerRef]);

  return (
    <div ref={rootRef} className={`artifact-length-control is-${tone}${open ? " is-open" : ""}`}>
      <button
        ref={triggerRef}
        className={`artifact-length-trigger${attention ? " is-file-mode-nudged" : ""}`}
        type="button"
        aria-label={`출력 방식 ${outputModeLabel}, 문서 출력 토큰 ${selected.label}${selected.warning ? `, ${selected.warning}` : ""}`}
        aria-describedby={attention ? "file-mode-nudge" : undefined}
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((current) => !current)}
      >
        <FileText size={12} aria-hidden="true" />
        <span className={`artifact-output-mode-value is-${outputMode}`}>{outputModeLabel}</span>
        <span className="artifact-control-separator" aria-hidden="true">·</span>
        <span className="artifact-length-value">{selected.label}</span>
        {selected.warning && <small>{selected.warning}</small>}
      </button>
      {open && createPortal(
        <div
          ref={popoverRef}
          id={popoverId}
          className={`artifact-length-popover is-${tone}${rootRef.current?.closest(".theme-dark") ? " theme-dark" : ""}`}
          role="group"
          aria-label="문서 출력 토큰 조절"
          style={{
            ...popoverStyle,
            "--artifact-length-progress": `${(selectedIndex / (artifactLengthSteps.length - 1)) * 100}%`,
          } as CSSProperties}
        >
          <div className="artifact-output-mode-picker">
            <span>출력 방식</span>
            <div role="group" aria-label="출력 방식">
              {([['auto', '자동'], ['chat', '채팅'], ['file', '파일']] as const).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={outputMode === mode ? "is-active" : ""}
                  aria-pressed={outputMode === mode}
                  onClick={() => onOutputModeChange(mode)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className={`artifact-length-popover-header${outputMode === "chat" ? " is-disabled" : ""}`}>
            <label htmlFor={inputId}>문서 출력 토큰</label>
            <output htmlFor={inputId}>
              <span>{selected.label}</span>
              {selected.warning && <small>{selected.warning}</small>}
            </output>
          </div>
          <input
            id={inputId}
            data-testid="artifact-length-slider"
            type="range"
            min={0}
            max={artifactLengthSteps.length - 1}
            step={1}
            value={selectedIndex}
            aria-label="문서 출력 토큰"
            aria-valuetext={ariaValueText}
            disabled={outputMode === "chat"}
            onChange={(event) => selectStep(Number(event.currentTarget.value))}
            onKeyDown={(event) => {
              const nextIndex = event.key === "Home"
                ? 0
                : event.key === "End"
                  ? artifactLengthSteps.length - 1
                  : ["ArrowRight", "ArrowUp"].includes(event.key)
                    ? selectedIndex + 1
                    : ["ArrowLeft", "ArrowDown"].includes(event.key)
                      ? selectedIndex - 1
                      : null;
              if (nextIndex === null) return;
              event.preventDefault();
              selectStep(nextIndex);
            }}
          />
        </div>,
        document.body,
      )}
    </div>
  );
}

export function ComposerPicker({
  options,
  value,
  onChange,
  ariaLabel,
  menuLabel,
  menuDescription,
  controlClassName,
  placeholder,
  tooltip,
  triggerIcon,
  hideChevron = false,
  disabled = false,
}: {
  options: ComposerPickerOption[];
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  menuLabel: string;
  menuDescription?: string;
  controlClassName: string;
  placeholder?: string;
  tooltip?: string;
  triggerIcon?: ReactNode;
  hideChevron?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const selectedIndex = options.findIndex((option) => option.id === value);
  const selected = options[selectedIndex];

  const openMenu = () => {
    setActiveIndex(Math.max(selectedIndex, 0));
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  const choose = (option: ComposerPickerOption) => {
    onChange(option.id);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className={`composer-picker ${open ? "is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        className={`composer-picker-trigger ${controlClassName}${hideChevron ? " has-no-chevron" : ""}${tooltip ? " tooltip-control" : ""}`}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={disabled || options.length === 0}
        data-tooltip={tooltip}
        onClick={() => open ? setOpen(false) : openMenu()}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!open) {
              openMenu();
              return;
            }
            const direction = event.key === "ArrowDown" ? 1 : -1;
            setActiveIndex((current) => (current + direction + options.length) % options.length);
          } else if (event.key === "Enter" && open) {
            event.preventDefault();
            const active = options[activeIndex];
            if (active) choose(active);
          } else if (event.key === "Escape" && open) {
            event.preventDefault();
            setOpen(false);
          }
        }}
      >
        {triggerIcon}
        <span>{selected?.triggerLabel ?? selected?.label ?? placeholder ?? ariaLabel}</span>
        {!hideChevron && <ChevronDown size={13} aria-hidden="true" />}
      </button>
      {open && (
        <div className={`composer-picker-menu${options.some((option) => option.description) ? " has-descriptions" : ""}`} id={listId} role="listbox" aria-label={ariaLabel}>
          <div className={`composer-picker-menu-label${menuDescription ? " has-description" : ""}`}>
            <span>{menuLabel}</span>
            {menuDescription && <small>{menuDescription}</small>}
          </div>
          {options.map((option, index) => (
            <button
              key={option.id}
              className={`${option.id === value ? "is-selected" : ""} ${index === activeIndex ? "is-active" : ""}`}
              type="button"
              role="option"
              aria-selected={option.id === value}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(option)}
            >
              <span className="composer-picker-option-copy">
                <strong>{option.label}</strong>
                {option.description && <small>{option.description}</small>}
              </span>
              <Check size={14} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
