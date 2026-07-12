---
name: openweb
description: >
  Structured OpenWeb access for supported web platforms. Use when the user asks
  for a supported platform URL, handle, profile, page, repository/package, paper,
  or platform-scoped search on services such as X/Twitter, Reddit, YouTube,
  GitHub, Stack Overflow, Medium, Substack, LinkedIn, Wikipedia, arXiv, npm,
  PyPI, Google Search, Google Scholar, shopping/travel/social platforms, and
  other sites listed by the OpenWeb catalog. Prefer this before generic
  web_search/web_fetch when the target platform is clear. Do not use for broad
  ordinary web searches where no supported platform is specified, or for
  YouTube caption/transcript extraction where a dedicated helper is available.
---

# OpenWeb

Use OpenWeb as the normal structured access path for supported platforms. It is
not a WAF bypass skill; if OpenWeb lacks the needed operation, requires login, or
returns insufficient data for a blocked source, switch to `insane-search`.

## Workflow

1. Inspect the catalog before guessing site or operation names.
   ```powershell
   python .skills/openweb/scripts/openweb_call.py sites
   python .skills/openweb/scripts/openweb_call.py youtube
   ```
2. Choose a read/search operation that matches the request. Avoid write actions
   such as posting, liking, following, commenting, or issue creation unless the
   user explicitly asks for that action.
3. Inspect operation parameters before calling it.
   ```powershell
   python .skills/openweb/scripts/openweb_call.py arxiv searchPapers
   python .skills/openweb/scripts/openweb_call.py wikipedia getPageSummary
   ```
4. Call the operation through the wrapper using `key=value` parameters. This
   avoids PowerShell JSON quote corruption.
   ```powershell
   python .skills/openweb/scripts/openweb_call.py arxiv searchPapers "search_query=all:agent web api" max_results=3
   python .skills/openweb/scripts/openweb_call.py wikipedia getPageSummary title=World_Wide_Web
   ```
5. If OpenWeb cannot satisfy the request, report the reason briefly and continue
   with the next appropriate path:
   - `web_search` when the task is a normal broad search.
   - `insane-search` when the source is blocked/sparse and important.
   - A platform-specific helper when it is more reliable, such as the
     `insane-search` YouTube transcript helper for caption-based video analysis.

## Routing Rules

- Use this skill directly for a known OpenWeb-supported platform URL, handle, or
  platform-scoped search.
- Use normal `web_search` first for broad research with no clear supported
  platform.
- Do not treat OpenWeb failure as final failure. If the source matters and access
  is blocked, invoke `insane-search`.
- Treat login/session requirements as a risk boundary. Explain the limitation
  before using account state or asking the user for authenticated access.
