import { Check, ChevronDown } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
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
}

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
}: SelectMenuProps) {
  const [open, setOpen] = useState(false);
  const [opensAbove, setOpensAbove] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listId = useId();
  const selectedIndex = options.findIndex((option) => option.value === value);
  const selected = options[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const focusIndex = selectedIndex >= 0 && !options[selectedIndex]?.disabled
      ? selectedIndex
      : options.findIndex((option) => !option.disabled);
    const frame = window.requestAnimationFrame(() => optionRefs.current[focusIndex]?.focus());
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, [open, options, selectedIndex]);

  useLayoutEffect(() => {
    if (!open || !rootRef.current || !menuRef.current) return;
    const rootRect = rootRef.current.getBoundingClientRect();
    const menuRect = menuRef.current.getBoundingClientRect();
    const lacksRoomBelow = rootRect.bottom + menuRect.height + 13 > window.innerHeight;
    const hasRoomAbove = rootRect.top - menuRect.height - 13 >= 0;
    setOpensAbove(lacksRoomBelow && hasRoomAbove);
  }, [open, options.length]);

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

  return (
    <div
      className={`lumina-select size-${size} width-${width} align-${align} ${open ? "is-open" : ""} ${opensAbove ? "opens-above" : ""} ${className}`.trim()}
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
      {open && (
        <div className="lumina-select-menu" id={listId} role="listbox" aria-label={`${ariaLabel} 목록`} ref={menuRef} onKeyDown={moveFocus}>
          {options.map((option, index) => (
            <button
              className={option.value === value ? "is-selected" : ""}
              type="button"
              role="option"
              aria-selected={option.value === value}
              disabled={option.disabled}
              key={option.value}
              ref={(element) => { optionRefs.current[index] = element; }}
              onClick={() => choose(option.value)}
            >
              <span>{option.label}</span>
              <Check size={12} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
