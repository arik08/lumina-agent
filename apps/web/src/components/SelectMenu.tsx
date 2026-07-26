import { Check, ChevronDown } from "lucide-react";
import { Fragment, type CSSProperties, type KeyboardEvent, type ReactNode, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./SelectMenu.css";

export interface SelectMenuOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectMenuProps {
  value: string;
  options: readonly SelectMenuOption[];
  ariaLabel: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  size?: "small" | "medium";
  width?: "fill" | "auto";
  align?: "start" | "end";
  className?: string;
  menuClassName?: string;
  onOpenChange?: (open: boolean) => void;
  renderOptionAction?: (option: SelectMenuOption) => ReactNode;
}

interface SelectMenuPosition {
  left: number;
  top: number;
  minWidth: number;
  maxHeight: number;
  opensAbove: boolean;
}

const MENU_GAP = 5;
const VIEWPORT_MARGIN = 12;

export function SelectMenu({
  value,
  options,
  ariaLabel,
  onChange,
  disabled = false,
  placeholder,
  size = "medium",
  width = "fill",
  align = "start",
  className = "",
  menuClassName = "",
  onOpenChange,
  renderOptionAction,
}: SelectMenuProps) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<SelectMenuPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listId = useId();
  const conversationFontSize = rootRef.current
    ?.closest<HTMLElement>(".app-shell")
    ?.style.getPropertyValue("--conversation-font-size");
  const selectedIndex = options.findIndex((option) => option.value === value);
  const selected = options[selectedIndex];

  useEffect(() => onOpenChange?.(open), [onOpenChange, open]);

  const positionMenu = useCallback(() => {
    if (!rootRef.current || !menuRef.current) return;
    const triggerRect = rootRef.current.getBoundingClientRect();
    const menuRect = menuRef.current.getBoundingClientRect();
    const availableBelow = Math.max(0, window.innerHeight - triggerRect.bottom - MENU_GAP - VIEWPORT_MARGIN);
    const availableAbove = Math.max(0, triggerRect.top - MENU_GAP - VIEWPORT_MARGIN);
    const opensAbove = menuRect.height > availableBelow && availableAbove > availableBelow;
    const maxHeight = Math.min(280, opensAbove ? availableAbove : availableBelow);
    const visibleHeight = Math.min(menuRect.height, maxHeight);
    const menuWidth = Math.max(menuRect.width, triggerRect.width);
    const preferredLeft = align === "end" ? triggerRect.right - menuWidth : triggerRect.left;
    const left = Math.min(
      Math.max(VIEWPORT_MARGIN, preferredLeft),
      Math.max(VIEWPORT_MARGIN, window.innerWidth - menuWidth - VIEWPORT_MARGIN),
    );
    const top = opensAbove
      ? Math.max(VIEWPORT_MARGIN, triggerRect.top - MENU_GAP - visibleHeight)
      : triggerRect.bottom + MENU_GAP;
    setMenuPosition({ left, top, minWidth: triggerRect.width, maxHeight, opensAbove });
  }, [align]);

  useEffect(() => {
    if (!open) return;
    const focusIndex = selectedIndex >= 0 && !options[selectedIndex]?.disabled
      ? selectedIndex
      : options.findIndex((option) => !option.disabled);
    const frame = window.requestAnimationFrame(() => optionRefs.current[focusIndex]?.focus());
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (
        event.target instanceof Node
        && !rootRef.current?.contains(event.target)
        && !menuRef.current?.contains(event.target)
      ) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, [open, options, selectedIndex]);

  useLayoutEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }
    positionMenu();
    const reposition = () => positionMenu();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, options.length, positionMenu]);

  useEffect(() => {
    if (disabled || options.length === 0) setOpen(false);
  }, [disabled, options.length]);

  const choose = (nextValue: string) => {
    setOpen(false);
    if (nextValue !== value) onChange(nextValue);
    triggerRef.current?.focus();
  };

  const moveFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    event.stopPropagation();
    const currentIndex = optionRefs.current.findIndex((option) => option === document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && currentIndex >= 0) {
      event.preventDefault();
      const currentOption = options[currentIndex];
      if (currentOption && !currentOption.disabled) choose(currentOption.value);
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const available = options.flatMap((option, index) => option.disabled ? [] : [index]);
    if (available.length === 0) return;
    const currentPosition = available.indexOf(currentIndex);
    const nextPosition = event.key === "Home"
      ? 0
      : event.key === "End"
        ? available.length - 1
        : event.key === "ArrowDown"
          ? (currentPosition + 1 + available.length) % available.length
          : (currentPosition - 1 + available.length) % available.length;
    optionRefs.current[available[nextPosition]]?.focus();
  };

  const menu = open && createPortal(
    <div
      className={`lumina-select-menu lumina-select-menu-global size-${size} ${menuPosition?.opensAbove ? "opens-above" : ""} ${rootRef.current?.closest(".theme-dark") ? "theme-dark" : ""} ${menuClassName}`.trim()}
      id={listId}
      role="listbox"
      aria-label={`${ariaLabel} 목록`}
      ref={menuRef}
      onKeyDown={moveFocus}
      style={{
        left: menuPosition?.left ?? 0,
        top: menuPosition?.top ?? 0,
        minWidth: menuPosition?.minWidth,
        maxHeight: menuPosition?.maxHeight,
        visibility: menuPosition ? "visible" : "hidden",
        ...(conversationFontSize ? { "--conversation-font-size": conversationFontSize } : {}),
      } as CSSProperties}
    >
      {options.map((option, index) => {
        const optionButton = (
          <button
            className={`lumina-select-option ${option.value === value ? "is-selected" : ""}`.trim()}
            type="button"
            role="option"
            aria-selected={option.value === value}
            disabled={option.disabled}
            ref={(element) => { optionRefs.current[index] = element; }}
            onClick={() => choose(option.value)}
          >
            <span>{option.label}</span>
            <Check size={12} aria-hidden="true" />
          </button>
        );
        return renderOptionAction ? (
          <div className="lumina-select-option-row" role="presentation" key={option.value}>
            {optionButton}
            {renderOptionAction(option)}
          </div>
        ) : <Fragment key={option.value}>{optionButton}</Fragment>;
      })}
    </div>,
    document.body,
  );

  return (
    <>
      <div
        className={`lumina-select size-${size} width-${width} align-${align} ${open ? "is-open" : ""} ${className}`.trim()}
        ref={rootRef}
      >
        <button
          className="lumina-select-trigger"
          type="button"
          aria-label={ariaLabel}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          disabled={disabled || options.length === 0}
          ref={triggerRef}
          onClick={() => setOpen((current) => !current)}
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
            }
          }}
        >
          <span>{selected?.label ?? placeholder ?? ariaLabel}</span>
          <ChevronDown size={13} aria-hidden="true" />
        </button>
      </div>
      {menu}
    </>
  );
}
