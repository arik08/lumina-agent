from __future__ import annotations

import re


MERMAID_CDN_VERSION = "11.16.0"
_RAW_MERMAID_BLOCK = re.compile(
    br'(?:class=["\'][^"\']*\bmermaid\b|'
    br'<pre\b[^>]*>\s*(?:<code\b[^>]*>\s*)?'
    br'(?:(?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR)\b|'
    br'(?:sequenceDiagram|classDiagram(?:-v2)?|stateDiagram(?:-v2)?|'
    br'erDiagram|journey|gantt|gitGraph|requirementDiagram|mindmap)\b))',
    flags=re.IGNORECASE,
)
_EXISTING_MERMAID_RUNTIME = re.compile(
    br'(?:src=["\'][^"\']*mermaid[^"\']*["\']|mermaid\s*\.\s*initialize\s*\()',
    flags=re.IGNORECASE,
)
_CLOSING_BODY = re.compile(br"</body\b", flags=re.IGNORECASE)
_STANDALONE_MARKER = b'data-lumina-standalone-mermaid="11.16.0"'

_STANDALONE_MERMAID_LAYER = f"""
<script {_STANDALONE_MARKER.decode("ascii")} src="https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_CDN_VERSION}/dist/mermaid.min.js"></script>
<style>
.lumina-standalone-mermaid-host{{position:relative!important}}
.lumina-standalone-mermaid-expand{{position:absolute;top:10px;right:10px;z-index:20;display:grid;width:32px;height:32px;padding:0;place-items:center;border:1px solid rgba(32,36,44,.18);border-radius:6px;background:rgba(255,255,255,.96);color:#20242c;box-shadow:0 7px 20px rgba(20,31,54,.15);cursor:pointer}}
.lumina-standalone-mermaid-expand:hover,.lumina-standalone-mermaid-expand:focus-visible{{border-color:#3f66c9;color:#315fbd;outline:2px solid rgba(63,102,201,.22);outline-offset:2px}}
.lumina-standalone-mermaid-expand svg,.lumina-standalone-mermaid-control svg{{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}
.lumina-standalone-mermaid-backdrop{{position:fixed;inset:0;z-index:2147483647;display:flex;flex-direction:column;background:rgba(248,250,252,.99);color:#20242c;font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}}
.lumina-standalone-mermaid-header{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-bottom:1px solid rgba(32,36,44,.14);background:#fff}}
.lumina-standalone-mermaid-controls{{display:flex;align-items:center;gap:6px}}
.lumina-standalone-mermaid-value{{min-width:48px;text-align:center;color:#626b78}}
.lumina-standalone-mermaid-control{{display:grid;width:30px;height:30px;padding:0;place-items:center;border:1px solid rgba(32,36,44,.16);border-radius:6px;background:#fff;color:#20242c;cursor:pointer}}
.lumina-standalone-mermaid-viewport{{display:grid;flex:1;overflow:hidden;place-items:center;background:radial-gradient(circle,rgba(108,115,126,.22) 0 1px,transparent 1.2px),#eef1f5;background-size:18px 18px,auto;cursor:grab;touch-action:none;user-select:none}}
.lumina-standalone-mermaid-viewport.is-dragging{{cursor:grabbing}}
.lumina-standalone-mermaid-canvas{{transform-origin:center}}
.lumina-standalone-mermaid-canvas svg{{display:block!important;width:auto!important;height:auto!important;max-width:calc(100vw - 48px)!important;max-height:calc(100vh - 92px)!important}}
@media print{{.lumina-standalone-mermaid-expand,.lumina-standalone-mermaid-backdrop{{display:none!important}}}}
</style>
<script>
(() => {{
  const icon = (paths) => '<svg aria-hidden="true" viewBox="0 0 24 24">' + paths + '</svg>';
  const icons = {{
    expand: icon('<path d="M8 3H3v5"></path><path d="M3 3l7 7"></path><path d="M16 3h5v5"></path><path d="m21 3-7 7"></path><path d="M8 21H3v-5"></path><path d="m3 21 7-7"></path><path d="M16 21h5v-5"></path><path d="m21 21-7-7"></path>'),
    close: icon('<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>'),
    reset: icon('<path d="M5 7v5h5"></path><path d="M5.7 12A7 7 0 0 1 17 6.5"></path><path d="M18.3 12A7 7 0 0 1 7 17.5"></path>'),
    plus: icon('<path d="M12 5v14"></path><path d="M5 12h14"></path>'),
    minus: icon('<path d="M5 12h14"></path>')
  }};
  let activeViewer = null;
  const control = (label, iconName, action) => {{
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-standalone-mermaid-control";
    button.setAttribute("aria-label", label);
    button.innerHTML = icons[iconName];
    button.addEventListener("click", action);
    return button;
  }};
  const closeViewer = () => {{
    activeViewer?.close();
    activeViewer = null;
  }};
  const onEscape = (event) => {{ if (event.key === "Escape") closeViewer(); }};
  const openViewer = (svg, trigger) => {{
    closeViewer();
    const previousOverflow = document.body.style.overflow;
    const backdrop = document.createElement("section");
    backdrop.className = "lumina-standalone-mermaid-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    const header = document.createElement("header");
    header.className = "lumina-standalone-mermaid-header";
    const heading = document.createElement("strong");
    heading.textContent = svg.closest("[aria-label]")?.getAttribute("aria-label") || "Mermaid";
    const controls = document.createElement("div");
    controls.className = "lumina-standalone-mermaid-controls";
    const value = document.createElement("output");
    value.className = "lumina-standalone-mermaid-value";
    const viewport = document.createElement("div");
    viewport.className = "lumina-standalone-mermaid-viewport";
    const canvas = document.createElement("div");
    canvas.className = "lumina-standalone-mermaid-canvas";
    const clonedSvg = svg.cloneNode(true);
    const viewBox = String(svg.getAttribute("viewBox") || "").split(/[\\s,]+/).map(Number);
    if (viewBox.length >= 4 && Number.isFinite(viewBox[2]) && Number.isFinite(viewBox[3]) && viewBox[2] > 0 && viewBox[3] > 0) {{
      clonedSvg.setAttribute("width", String(viewBox[2]));
      clonedSvg.setAttribute("height", String(viewBox[3]));
    }}
    canvas.append(clonedSvg);
    viewport.append(canvas);
    let zoom = 1;
    let offsetX = 0;
    let offsetY = 0;
    let drag = null;
    const update = () => {{
      canvas.style.transform = "translate(" + offsetX + "px," + offsetY + "px) scale(" + zoom + ")";
      value.textContent = Math.round(zoom * 100) + "%";
    }};
    const changeZoom = (next) => {{ zoom = Math.min(4, Math.max(.5, next)); update(); }};
    const reset = () => {{ zoom = 1; offsetX = 0; offsetY = 0; update(); }};
    const close = () => {{
      backdrop.remove();
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onEscape);
      trigger.focus();
    }};
    activeViewer = {{ close }};
    const closeButton = control("크게 보기 닫기", "close", closeViewer);
    controls.append(
      control("축소", "minus", () => changeZoom(zoom / 1.2)),
      value,
      control("확대", "plus", () => changeZoom(zoom * 1.2)),
      control("보기 초기화", "reset", reset),
      closeButton
    );
    header.append(heading, controls);
    backdrop.append(header, viewport);
    document.body.append(backdrop);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onEscape);
    viewport.addEventListener("wheel", (event) => {{
      event.preventDefault();
      changeZoom(zoom * (event.deltaY > 0 ? .9 : 1.1));
    }}, {{ passive: false }});
    viewport.addEventListener("pointerdown", (event) => {{
      if (event.button !== 0) return;
      drag = {{ id: event.pointerId, x: event.clientX, y: event.clientY, offsetX, offsetY }};
      viewport.setPointerCapture?.(event.pointerId);
      viewport.classList.add("is-dragging");
    }});
    viewport.addEventListener("pointermove", (event) => {{
      if (!drag || drag.id !== event.pointerId) return;
      offsetX = drag.offsetX + event.clientX - drag.x;
      offsetY = drag.offsetY + event.clientY - drag.y;
      update();
    }});
    const finishDrag = (event) => {{
      if (!drag || drag.id !== event.pointerId) return;
      drag = null;
      viewport.classList.remove("is-dragging");
    }};
    viewport.addEventListener("pointerup", finishDrag);
    viewport.addEventListener("pointercancel", finishDrag);
    closeButton.focus();
    update();
  }};
  const attachZoom = (svg) => {{
    const host = svg.closest(".mermaid");
    if (!host || host.dataset.luminaStandaloneZoomAttached === "true") return;
    host.dataset.luminaStandaloneZoomAttached = "true";
    host.classList.add("lumina-standalone-mermaid-host");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-standalone-mermaid-expand";
    button.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    button.innerHTML = icons.expand;
    button.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      openViewer(svg, button);
    }});
    host.prepend(button);
  }};
  const isMermaidSource = (source) =>
    /^(?:(?:flowchart|graph)\\s+(?:TB|TD|BT|RL|LR)\\b|(?:sequenceDiagram|classDiagram(?:-v2)?|stateDiagram(?:-v2)?|erDiagram|journey|gantt|gitGraph|requirementDiagram|mindmap)\\b)/i.test(source.trim());
  const recoverBareMermaid = () => {{
    document.querySelectorAll("pre").forEach((pre) => {{
      if (pre.closest(".mermaid") || pre.querySelector("code.language-mermaid,code.lang-mermaid,code.language-mmd,code.lang-mmd")) return;
      const source = pre.textContent?.trim() || "";
      if (!isMermaidSource(source)) return;
      const element = document.createElement("div");
      element.className = "mermaid";
      element.textContent = source;
      pre.replaceWith(element);
    }});
  }};
  const start = async () => {{
    if (!window.mermaid) return;
    recoverBareMermaid();
    window.mermaid.initialize({{
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      flowchart: {{ htmlLabels: false }}
    }});
    try {{
      await window.mermaid.run({{ querySelector: ".mermaid" }});
      document.querySelectorAll(".mermaid svg").forEach(attachZoom);
    }} catch (error) {{
      document.querySelectorAll(".mermaid:not([data-processed])").forEach((element) => {{
        element.setAttribute("role", "alert");
        element.textContent = "Mermaid 다이어그램을 렌더링하지 못했습니다.";
      }});
    }}
  }};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {{ once: true }});
  else start();
}})();
</script>
""".strip().encode("utf-8")


def prepare_standalone_html_download(content: bytes, mime_type: str) -> bytes:
    if mime_type != "text/html":
        return content
    if not _RAW_MERMAID_BLOCK.search(content):
        return content
    if _STANDALONE_MARKER in content or _EXISTING_MERMAID_RUNTIME.search(content):
        return content

    closing_body = -1
    for match in _CLOSING_BODY.finditer(content):
        closing_body = match.start()
    insertion = closing_body if closing_body >= 0 else len(content)
    return (
        content[:insertion]
        + b"\n"
        + _STANDALONE_MERMAID_LAYER
        + b"\n"
        + content[insertion:]
    )
