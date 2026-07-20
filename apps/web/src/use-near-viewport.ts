import { useEffect, useState, type RefObject } from "react";

export function useNearViewport(
  targetRef: RefObject<Element | null>,
  { eager = false, rootMargin = "900px 0px" }: { eager?: boolean; rootMargin?: string } = {},
) {
  const [nearViewport, setNearViewport] = useState(eager);

  useEffect(() => {
    if (eager) {
      setNearViewport(true);
      return undefined;
    }
    const target = targetRef.current;
    if (!target || typeof IntersectionObserver !== "function") {
      setNearViewport(true);
      return undefined;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      setNearViewport(true);
      observer.disconnect();
    }, { rootMargin });
    observer.observe(target);
    return () => observer.disconnect();
  }, [eager, rootMargin, targetRef]);

  return nearViewport;
}
