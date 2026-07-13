const SCROLLBAR_IDLE_DELAY_MS = 650;

export function installScrollbarActivity() {
  const idleTimers = new Map<HTMLElement, number>();

  const handleScroll = (event: Event) => {
    const target = event.target;
    const element = target instanceof HTMLElement
      ? target
      : document.scrollingElement instanceof HTMLElement
        ? document.scrollingElement
        : null;

    if (!element) {
      return;
    }

    element.classList.add("has-scrollbar-fade", "is-scrolling");
    const previousTimer = idleTimers.get(element);
    if (previousTimer !== undefined) {
      window.clearTimeout(previousTimer);
    }

    idleTimers.set(element, window.setTimeout(() => {
      element.classList.remove("is-scrolling");
      idleTimers.delete(element);
    }, SCROLLBAR_IDLE_DELAY_MS));
  };

  document.addEventListener("scroll", handleScroll, true);

  return () => {
    document.removeEventListener("scroll", handleScroll, true);
    for (const [element, timer] of idleTimers) {
      window.clearTimeout(timer);
      element.classList.remove("has-scrollbar-fade", "is-scrolling");
    }
    idleTimers.clear();
  };
}
