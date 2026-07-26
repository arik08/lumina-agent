import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

const tooltipSelector = "[data-tooltip]";
const viewportPadding = 12;
const tooltipGap = 8;

interface TooltipPosition {
  placement: "above" | "below" | "right" | "left";
  style: CSSProperties & {
    "--global-tooltip-anchor-x": string;
    left: number;
    top: number;
    visibility: "hidden" | "visible";
  };
}

interface ActiveTooltip {
  target: HTMLElement;
  text: string;
}

function tooltipTarget(value: EventTarget | null) {
  return value instanceof Element ? value.closest<HTMLElement>(tooltipSelector) : null;
}

function tooltipText(target: HTMLElement) {
  return target.dataset.tooltip?.trim() || "";
}

export function GlobalTooltipLayer({
  anchor,
  open,
  children,
  className = "global-tooltip",
  id,
  preferredPlacement = "vertical",
}: {
  anchor: HTMLElement | null;
  open: boolean;
  children: ReactNode;
  className?: string;
  id?: string;
  preferredPlacement?: "vertical" | "right";
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<TooltipPosition>({
    placement: "above",
    style: { "--global-tooltip-anchor-x": "50%", left: 0, top: 0, visibility: "hidden" },
  });

  const updatePosition = useCallback(() => {
    const layer = layerRef.current;
    if (!open || !anchor || !layer || !anchor.isConnected) return;
    const anchorRect = anchor.getBoundingClientRect();
    const layerRect = layer.getBoundingClientRect();
    const spaceAbove = anchorRect.top - viewportPadding - tooltipGap;
    const spaceBelow = window.innerHeight - anchorRect.bottom - viewportPadding - tooltipGap;
    const spaceRight = window.innerWidth - anchorRect.right - viewportPadding - tooltipGap;
    const spaceLeft = anchorRect.left - viewportPadding - tooltipGap;
    const placement = preferredPlacement === "right"
      ? (spaceRight >= layerRect.width || spaceRight >= spaceLeft ? "right" : "left")
      : (spaceAbove < layerRect.height && spaceBelow > spaceAbove ? "below" : "above");
    const maximumLeft = Math.max(viewportPadding, window.innerWidth - viewportPadding - layerRect.width);
    const requestedLeft = placement === "right"
      ? anchorRect.right + tooltipGap
      : placement === "left"
        ? anchorRect.left - tooltipGap - layerRect.width
        : anchorRect.left + (anchorRect.width - layerRect.width) / 2;
    const left = Math.min(maximumLeft, Math.max(viewportPadding, requestedLeft));
    const anchorX = `${Math.min(layerRect.width - 16, Math.max(16, anchorRect.left + anchorRect.width / 2 - left))}px`;
    const requestedTop = placement === "below"
      ? anchorRect.bottom + tooltipGap
      : placement === "above"
        ? anchorRect.top - tooltipGap - layerRect.height
        : anchorRect.top + (anchorRect.height - layerRect.height) / 2;
    const top = Math.min(
      Math.max(viewportPadding, window.innerHeight - viewportPadding - layerRect.height),
      Math.max(viewportPadding, requestedTop),
    );
    setPosition((current) => (
      current.placement === placement
      && current.style.left === left
      && current.style.top === top
      && current.style["--global-tooltip-anchor-x"] === anchorX
      && current.style.visibility === "visible"
        ? current
        : { placement, style: { "--global-tooltip-anchor-x": anchorX, left, top, visibility: "visible" } }
    ));
  }, [anchor, open, preferredPlacement]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  });

  useEffect(() => {
    if (!open) return undefined;
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition]);

  if (!open || !anchor) return null;
  const themeClassName = anchor.closest(".theme-dark") ? " theme-dark" : "";
  return createPortal(
    <div className={`global-tooltip-layer ${className}${themeClassName}`} data-placement={position.placement} id={id} ref={layerRef} role="tooltip" style={position.style}>
      {children}
    </div>,
    document.body,
  );
}

export function GlobalTooltipProvider({ children }: { children: ReactNode }) {
  const tooltipId = useId();
  const activeRef = useRef<ActiveTooltip | null>(null);
  const [active, setActive] = useState<ActiveTooltip | null>(null);

  useEffect(() => {
    const show = (event: Event) => {
      if (event instanceof PointerEvent && event.buttons !== 0) return;
      const target = tooltipTarget(event.target);
      if (!target) return;
      const text = tooltipText(target);
      if (!text) return;
      activeRef.current = { target, text };
      setActive({ target, text });
    };
    const hide = (event: Event) => {
      const current = activeRef.current;
      if (!current) return;
      const relatedTarget = "relatedTarget" in event ? event.relatedTarget : null;
      if (relatedTarget instanceof Node && current.target.contains(relatedTarget)) return;
      activeRef.current = null;
      setActive(null);
    };
    document.addEventListener("pointerover", show, true);
    document.addEventListener("pointerout", hide, true);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("focusin", show, true);
    document.addEventListener("focusout", hide, true);
    return () => {
      document.removeEventListener("pointerover", show, true);
      document.removeEventListener("pointerout", hide, true);
      document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("focusin", show, true);
      document.removeEventListener("focusout", hide, true);
    };
  }, []);

  useEffect(() => {
    const target = active?.target;
    if (!target) return undefined;
    const previous = target.getAttribute("aria-describedby");
    const descriptions = new Set((previous ?? "").split(/\s+/).filter(Boolean));
    descriptions.add(tooltipId);
    target.setAttribute("aria-describedby", [...descriptions].join(" "));
    return () => {
      if (previous) target.setAttribute("aria-describedby", previous);
      else target.removeAttribute("aria-describedby");
    };
  }, [active?.target, tooltipId]);

  useEffect(() => {
    const target = active?.target;
    if (!target) return undefined;
    const observer = new MutationObserver(() => {
      const text = tooltipText(target);
      if (!text) {
        activeRef.current = null;
        setActive(null);
        return;
      }
      activeRef.current = { target, text };
      setActive((current) => current?.target === target && current.text === text ? current : { target, text });
    });
    observer.observe(target, { attributes: true, attributeFilter: ["data-tooltip"] });
    return () => observer.disconnect();
  }, [active?.target]);

  return (
    <>
      {children}
      <GlobalTooltipLayer anchor={active?.target ?? null} id={tooltipId} open={Boolean(active)}>
        {active?.text}
      </GlobalTooltipLayer>
    </>
  );
}
