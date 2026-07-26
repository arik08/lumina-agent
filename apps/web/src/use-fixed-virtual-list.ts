import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

interface FixedVirtualListOptions {
  threshold?: number;
  overscan?: number;
  disabled?: boolean;
}

export function useFixedVirtualList<T extends HTMLElement = HTMLDivElement>(
  itemCount: number,
  rowHeight: number,
  { threshold = 80, overscan = 6, disabled = false }: FixedVirtualListOptions = {},
) {
  const containerRef = useRef<T | null>(null);
  const frameRef = useRef<number | null>(null);
  const [viewport, setViewport] = useState({ height: 0, scrollTop: 0 });

  const measure = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    setViewport((current) => {
      const height = container.clientHeight;
      const scrollTop = container.scrollTop;
      return current.height === height && current.scrollTop === scrollTop
        ? current
        : { height, scrollTop };
    });
  }, []);

  const onScroll = useCallback((target: T) => {
    if (frameRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = null;
      setViewport((current) => current.scrollTop === target.scrollTop
        ? current
        : { ...current, scrollTop: target.scrollTop });
    });
  }, []);

  useLayoutEffect(() => {
    measure();
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [measure]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const maximumScrollTop = Math.max(0, itemCount * rowHeight - container.clientHeight);
    if (container.scrollTop <= maximumScrollTop) return;
    container.scrollTop = maximumScrollTop;
    measure();
  }, [itemCount, measure, rowHeight]);

  useEffect(() => () => {
    if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
  }, []);

  const virtualized = !disabled && itemCount > threshold && viewport.height > 0;
  const visibleCount = Math.ceil(viewport.height / rowHeight);
  const start = virtualized
    ? Math.max(0, Math.floor(viewport.scrollTop / rowHeight) - overscan)
    : 0;
  const end = virtualized
    ? Math.min(itemCount, start + visibleCount + overscan * 2)
    : itemCount;

  return {
    containerRef,
    onScroll,
    virtualized,
    start,
    end,
    totalHeight: itemCount * rowHeight,
  };
}
