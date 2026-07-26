import { Children, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useRef, useState } from "react";

interface ResizableSplitPaneProps {
  children: ReactNode;
  storageKey: string;
  ariaLabel: string;
  className?: string;
  defaultWidth?: number;
  minimumWidth?: number;
  maximumRatio?: number;
  primarySide?: "left" | "right";
}

function storedWidth(storageKey: string, fallback: number) {
  try {
    const value = Number(window.localStorage.getItem(storageKey));
    return Number.isFinite(value) && value > 0 ? value : fallback;
  } catch {
    return fallback;
  }
}

export function ResizableSplitPane({
  children,
  storageKey,
  ariaLabel,
  className = "",
  defaultWidth = 300,
  minimumWidth = 220,
  maximumRatio = 0.58,
  primarySide = "left",
}: ResizableSplitPaneProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [primaryWidth, setPrimaryWidth] = useState(() => storedWidth(storageKey, defaultWidth));
  const panes = Children.toArray(children);

  const clampWidth = (value: number) => {
    const available = rootRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    return Math.round(Math.min(Math.max(minimumWidth, value), Math.max(minimumWidth, available * maximumRatio)));
  };

  const remember = (value: number) => {
    try {
      window.localStorage.setItem(storageKey, String(value));
    } catch {
      // The browser may block local storage. The current session still remains resizable.
    }
  };

  useEffect(() => {
    const fitToViewport = () => setPrimaryWidth((current) => clampWidth(current));
    fitToViewport();
    window.addEventListener("resize", fitToViewport);
    return () => window.removeEventListener("resize", fitToViewport);
  }, [maximumRatio, minimumWidth]);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!rootRef.current) return;
    event.preventDefault();
    const bounds = rootRef.current.getBoundingClientRect();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const widthAt = (clientX: number) => (
      primarySide === "right" ? bounds.right - clientX : clientX - bounds.left
    );
    const move = (pointerEvent: PointerEvent) => setPrimaryWidth(clampWidth(widthAt(pointerEvent.clientX)));
    const finish = (pointerEvent: PointerEvent) => {
      const nextWidth = clampWidth(widthAt(pointerEvent.clientX));
      setPrimaryWidth(nextWidth);
      remember(nextWidth);
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  };

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const boundaryDelta = event.key === "ArrowRight" ? 16 : -16;
    const nextWidth = clampWidth(primaryWidth + (primarySide === "right" ? -boundaryDelta : boundaryDelta));
    setPrimaryWidth(nextWidth);
    remember(nextWidth);
  };

  return (
    <div
      ref={rootRef}
      className={`split-feature resizable-split is-primary-${primarySide} ${className}`.trim()}
      style={{ "--split-primary-width": `${primaryWidth}px` } as CSSProperties}
    >
      {panes[0]}
      <div
        className="split-resizer"
        role="separator"
        aria-label={ariaLabel}
        aria-orientation="vertical"
        aria-valuemin={minimumWidth}
        aria-valuemax={Math.round((rootRef.current?.clientWidth ?? 1000) * maximumRatio)}
        aria-valuenow={primaryWidth}
        tabIndex={0}
        onPointerDown={startResize}
        onKeyDown={resizeWithKeyboard}
      />
      {panes[1]}
    </div>
  );
}
