(() => {
  if (window.__luminaArtifactPreviewBridgeReady) return;
  window.__luminaArtifactPreviewBridgeReady = true;

  const style = document.createElement("style");
  style.id = "lumina-artifact-preview-style";
  style.textContent = `
    sup.source-ref { display:inline; margin:0 1px 0 2px; color:#315fbd; font-size:inherit; line-height:inherit; vertical-align:baseline; }
    a.source-ref, sup.source-ref > a { display:inline; width:auto; height:auto; margin:0 1px 0 2px; padding:0; border:0; border-radius:3px; background:transparent; color:#315fbd; font-family:inherit; font-size:1em; font-weight:720; line-height:inherit; text-decoration:none; vertical-align:baseline; }
    a.source-ref:focus-visible, sup.source-ref > a:focus-visible { outline:2px solid color-mix(in srgb,currentColor 55%,transparent); outline-offset:2px; }
    .lumina-artifact-source-card { position:fixed; z-index:2147483647; right:18px; bottom:18px; display:grid; width:min(420px,calc(100vw - 36px)); gap:8px; padding:14px 42px 14px 15px; border:1px solid rgba(49,95,189,.28); border-radius:8px; background:#fff; color:#202631; box-shadow:0 16px 44px rgba(20,31,54,.22); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
    .lumina-artifact-source-card a { overflow-wrap:anywhere; color:#315fbd; text-decoration:underline; text-underline-offset:2px; }
    .lumina-artifact-source-card button { position:absolute; top:8px; right:8px; display:grid; width:28px; height:28px; place-items:center; border:0; border-radius:5px; background:transparent; color:#6b7280; cursor:pointer; font:18px/1 sans-serif; }
    .lumina-artifact-mermaid-host { position:relative!important; }
    .lumina-artifact-mermaid-expand { position:absolute; top:10px; right:10px; z-index:20; display:grid; width:32px; height:32px; padding:0; place-items:center; border:1px solid rgba(32,36,44,.18); border-radius:6px; background:rgba(255,255,255,.96); color:#20242c; box-shadow:0 7px 20px rgba(20,31,54,.15); cursor:pointer; }
    .lumina-artifact-mermaid-expand:focus-visible { border-color:#3f66c9; outline:2px solid rgba(63,102,201,.22); outline-offset:2px; }
    .lumina-artifact-mermaid-expand svg, .lumina-artifact-mermaid-control svg { width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
    .lumina-artifact-mermaid-backdrop { position:fixed; inset:0; z-index:2147483647; display:flex; flex-direction:column; background:rgba(248,250,252,.99); color:#20242c; font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif; }
    .lumina-artifact-mermaid-header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-bottom:1px solid rgba(32,36,44,.14); background:#fff; }
    .lumina-artifact-mermaid-controls { display:flex; align-items:center; gap:6px; }
    .lumina-artifact-mermaid-value { min-width:48px; text-align:center; color:#626b78; }
    .lumina-artifact-mermaid-control { display:grid; width:30px; height:30px; padding:0; place-items:center; border:1px solid rgba(32,36,44,.16); border-radius:6px; background:#fff; color:#20242c; cursor:pointer; }
    .lumina-artifact-mermaid-viewport { display:grid; flex:1; overflow:hidden; place-items:center; background:radial-gradient(circle,rgba(108,115,126,.22) 0 1px,transparent 1.2px),#eef1f5; background-size:18px 18px,auto; cursor:grab; touch-action:none; user-select:none; }
    .lumina-artifact-mermaid-viewport.is-dragging { cursor:grabbing; }
    .lumina-artifact-mermaid-canvas { transform-origin:center; }
    .lumina-artifact-mermaid-canvas svg { display:block!important; width:auto!important; height:auto!important; max-width:calc(100vw - 48px)!important; max-height:calc(100vh - 92px)!important; }
    @media print { .lumina-artifact-mermaid-expand,.lumina-artifact-mermaid-backdrop { display:none!important; } }
  `;
  document.head.append(style);

  const icon = (paths) => `<svg aria-hidden="true" viewBox="0 0 24 24">${paths}</svg>`;
  const icons = {
    expand: icon('<path d="M8 3H3v5"></path><path d="M3 3l7 7"></path><path d="M16 3h5v5"></path><path d="m21 3-7 7"></path><path d="M8 21H3v-5"></path><path d="m3 21 7-7"></path><path d="M16 21h5v-5"></path><path d="m21 21-7-7"></path>'),
    close: icon('<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>'),
    reset: icon('<path d="M5 7v5h5"></path><path d="M5.7 12A7 7 0 0 1 17 6.5"></path><path d="M18.3 12A7 7 0 0 1 7 17.5"></path>'),
    plus: icon('<path d="M12 5v14"></path><path d="M5 12h14"></path>'),
    minus: icon('<path d="M5 12h14"></path>'),
  };
  let activeViewer = null;

  const control = (label, iconName, action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-artifact-mermaid-control";
    button.setAttribute("aria-label", label);
    button.innerHTML = icons[iconName];
    button.addEventListener("click", action);
    return button;
  };

  const closeViewer = () => {
    activeViewer?.close();
    activeViewer = null;
  };
  const onEscape = (event) => { if (event.key === "Escape") closeViewer(); };
  const openViewer = (svg, trigger) => {
    closeViewer();
    const previousOverflow = document.body.style.overflow;
    const backdrop = document.createElement("section");
    backdrop.className = "lumina-artifact-mermaid-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    const header = document.createElement("header");
    header.className = "lumina-artifact-mermaid-header";
    const heading = document.createElement("strong");
    heading.textContent = svg.closest("[aria-label]")?.getAttribute("aria-label") || "Mermaid";
    const controls = document.createElement("div");
    controls.className = "lumina-artifact-mermaid-controls";
    const value = document.createElement("output");
    value.className = "lumina-artifact-mermaid-value";
    const viewport = document.createElement("div");
    viewport.className = "lumina-artifact-mermaid-viewport";
    const canvas = document.createElement("div");
    canvas.className = "lumina-artifact-mermaid-canvas";
    canvas.append(svg.cloneNode(true));
    viewport.append(canvas);
    let zoom = 1;
    let offsetX = 0;
    let offsetY = 0;
    let drag = null;
    const update = () => {
      canvas.style.transform = `translate(${offsetX}px,${offsetY}px) scale(${zoom})`;
      value.textContent = `${Math.round(zoom * 100)}%`;
    };
    const changeZoom = (next) => { zoom = Math.min(4, Math.max(.5, next)); update(); };
    const reset = () => { zoom = 1; offsetX = 0; offsetY = 0; update(); };
    const close = () => {
      backdrop.remove();
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onEscape);
      trigger.focus();
    };
    activeViewer = { close };
    const closeButton = control("크게 보기 닫기", "close", closeViewer);
    controls.append(
      control("축소", "minus", () => changeZoom(zoom / 1.2)),
      value,
      control("확대", "plus", () => changeZoom(zoom * 1.2)),
      control("보기 초기화", "reset", reset),
      closeButton,
    );
    header.append(heading, controls);
    backdrop.append(header, viewport);
    document.body.append(backdrop);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onEscape);
    viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      changeZoom(zoom * (event.deltaY > 0 ? .9 : 1.1));
    }, { passive: false });
    viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, offsetX, offsetY };
      viewport.setPointerCapture?.(event.pointerId);
      viewport.classList.add("is-dragging");
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      offsetX = drag.offsetX + event.clientX - drag.x;
      offsetY = drag.offsetY + event.clientY - drag.y;
      update();
    });
    const finishDrag = (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      drag = null;
      viewport.classList.remove("is-dragging");
    };
    viewport.addEventListener("pointerup", finishDrag);
    viewport.addEventListener("pointercancel", finishDrag);
    closeButton.focus();
    update();
  };

  const attachZoom = (svg) => {
    if (svg.closest(".lumina-artifact-mermaid-backdrop")) return;
    const host = svg.closest("[data-lumina-rendered-mermaid],.mermaid,.mermaid-chart") || svg.parentElement;
    if (!host || host.dataset.luminaMermaidZoomAttached === "true") return;
    host.dataset.luminaMermaidZoomAttached = "true";
    host.classList.add("lumina-artifact-mermaid-host");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-artifact-mermaid-expand";
    button.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    button.innerHTML = icons.expand;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openViewer(svg, button);
    });
    host.prepend(button);
  };
  const enhanceZoom = () => document.querySelectorAll("[data-lumina-rendered-mermaid] svg,.mermaid svg,.mermaid-chart svg,svg[id^='mermaid-']").forEach(attachZoom);
  let enhanceFrame = null;
  const scheduleEnhanceZoom = () => {
    if (enhanceFrame !== null) return;
    enhanceFrame = requestAnimationFrame(() => {
      enhanceFrame = null;
      enhanceZoom();
    });
  };
  new MutationObserver(scheduleEnhanceZoom).observe(document.documentElement, { childList: true, subtree: true });

  const markers = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"];
  document.querySelectorAll("a.source-ref[href], sup.source-ref > a[href]").forEach((link) => {
    const number = Number((link.textContent || "").trim());
    if (Number.isInteger(number) && number > 0) link.textContent = markers[number - 1] || `[${number}]`;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    if (!link.getAttribute("aria-label")) link.setAttribute("aria-label", Number.isInteger(number) ? `출처 ${number} 열기` : "출처 열기");
    link.addEventListener("click", () => {
      document.querySelector(".lumina-artifact-source-card")?.remove();
      const card = document.createElement("aside");
      card.className = "lumina-artifact-source-card";
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-label", "출처 링크");
      const heading = document.createElement("strong");
      heading.textContent = link.getAttribute("aria-label") || "출처 링크";
      const sourceLink = document.createElement("a");
      sourceLink.href = link.href;
      sourceLink.target = "_blank";
      sourceLink.rel = "noreferrer noopener";
      sourceLink.textContent = link.href;
      const close = document.createElement("button");
      close.type = "button";
      close.setAttribute("aria-label", "출처 링크 닫기");
      close.textContent = "×";
      close.addEventListener("click", () => card.remove());
      card.append(heading, sourceLink, close);
      document.body.append(card);
    });
  });

  const rawMermaid = [];
  document.querySelectorAll(".mermaid").forEach((element) => {
    if (!element.querySelector("svg") && element.textContent?.trim()) rawMermaid.push({ element, source: element.textContent.trim() });
  });
  document.querySelectorAll("pre > code.language-mermaid,pre > code.lang-mermaid,pre > code.language-mmd,pre > code.lang-mmd").forEach((code) => {
    if (code.closest(".mermaid") || !code.textContent?.trim()) return;
    const element = document.createElement("div");
    element.className = "mermaid";
    code.closest("pre")?.replaceWith(element);
    rawMermaid.push({ element, source: code.textContent.trim() });
  });
  let mermaidIndex = 0;
  let pendingMermaid = null;
  const renderNextMermaid = () => {
    if (pendingMermaid || mermaidIndex >= rawMermaid.length) return;
    const task = rawMermaid[mermaidIndex++];
    const requestId = `mermaid-${Date.now()}-${mermaidIndex}`;
    pendingMermaid = { requestId, task };
    parent.postMessage({ type: "lumina:artifact-mermaid-request", requestId, source: task.source }, "*");
  };
  window.addEventListener("message", (event) => {
    if (event.source !== parent || event.data?.type !== "lumina:artifact-mermaid-result" || event.data.requestId !== pendingMermaid?.requestId) return;
    const { task } = pendingMermaid;
    if (typeof event.data.svg === "string" && event.data.svg) {
      task.element.innerHTML = event.data.svg;
      task.element.dataset.luminaRenderedMermaid = "true";
      task.element.setAttribute("role", "img");
      task.element.setAttribute("aria-label", "Mermaid 다이어그램");
    } else {
      task.element.classList.add("lumina-mermaid-error");
      task.element.textContent = "Mermaid 다이어그램을 렌더링하지 못했습니다.";
    }
    pendingMermaid = null;
    requestAnimationFrame(() => { enhanceZoom(); renderNextMermaid(); });
  });

  requestAnimationFrame(() => {
    enhanceZoom();
    renderNextMermaid();
    parent.postMessage({ type: "lumina:artifact-preview-ready" }, "*");
  });
})();
