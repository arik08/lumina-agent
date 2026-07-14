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

const tooltipSelector = "[data-tooltip], [data-global-tooltip-title], [title]:not(iframe)";
const viewportPadding = 12;
const tooltipGap = 8;

interface TooltipPosition {
  placement: "above" | "below";
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
  return target.dataset.tooltip?.trim()
    || target.dataset.globalTooltipTitle?.trim()
    || target.getAttribute("title")?.trim()
    || "";
}

function suppressNativeTitle(target: HTMLElement) {
  const title = target.getAttribute("title");
  if (!title) return;
  target.dataset.globalTooltipTitle = title;
  target.removeAttribute("title");
}

function restoreNativeTitle(target: HTMLElement) {
  const title = target.dataset.globalTooltipTitle;
  if (title === undefined) return;
  if (!target.hasAttribute("title")) target.setAttribute("title", title);
  delete target.dataset.globalTooltipTitle;
}

export function GlobalTooltipLayer({
  anchor,
  open,
  children,
  className = "global-tooltip",
  id,
}: {
  anchor: HTMLElement | null;
  open: boolean;
  children: ReactNode;
  className?: string;
  id?: string;
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
    const maximumLeft = Math.max(viewportPadding, window.innerWidth - viewportPadding - layerRect.width);
    const left = Math.min(
      maximumLeft,
      Math.max(viewportPadding, anchorRect.left + (anchorRect.width - layerRect.width) / 2),
    );
    const anchorX = `${Math.min(layerRect.width - 16, Math.max(16, anchorRect.left + anchorRect.width / 2 - left))}px`;
    const spaceAbove = anchorRect.top - viewportPadding - tooltipGap;
    const spaceBelow = window.innerHeight - anchorRect.bottom - viewportPadding - tooltipGap;
    const placement = spaceAbove < layerRect.height && spaceBelow > spaceAbove ? "below" : "above";
    const requestedTop = placement === "below"
      ? anchorRect.bottom + tooltipGap
      : anchorRect.top - tooltipGap - layerRect.height;
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
  }, [anchor, open]);

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
  return createPortal(
    <div className={`global-tooltip-layer ${className}`} data-placement={position.placement} id={id} ref={layerRef} role="tooltip" style={position.style}>
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
      const target = tooltipTarget(event.target);
      if (!target) return;
      suppressNativeTitle(target);
      const text = tooltipText(target);
      if (!text) return;
      const previous = activeRef.current;
      if (previous && previous.target !== target) restoreNativeTitle(previous.target);
      activeRef.current = { target, text };
      setActive({ target, text });
    };
    const hide = (event: Event) => {
      const current = activeRef.current;
      if (!current) return;
      const relatedTarget = "relatedTarget" in event ? event.relatedTarget : null;
      if (relatedTarget instanceof Node && current.target.contains(relatedTarget)) return;
      restoreNativeTitle(current.target);
      activeRef.current = null;
      setActive(null);
    };
    document.addEventListener("pointerover", show, true);
    document.addEventListener("pointerout", hide, true);
    document.addEventListener("focusin", show, true);
    document.addEventListener("focusout", hide, true);
    return () => {
      document.removeEventListener("pointerover", show, true);
      document.removeEventListener("pointerout", hide, true);
      document.removeEventListener("focusin", show, true);
      document.removeEventListener("focusout", hide, true);
      if (activeRef.current) restoreNativeTitle(activeRef.current.target);
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
    observer.observe(target, { attributes: true, attributeFilter: ["data-tooltip", "title"] });
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
