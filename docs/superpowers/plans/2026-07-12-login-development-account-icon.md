# Login Development Account Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the development-account text helper with a discreet accessible icon button that reveals its label on hover or keyboard focus.

**Architecture:** Keep the existing development-only button and click handler inside `LoginScreen`, changing only its rendered icon and accessible tooltip markup. Style the button and tooltip in the login stylesheet without introducing a shared component because this helper exists on only one screen.

**Tech Stack:** React 19, TypeScript, lucide-react, CSS, Node.js built-in test runner

---

### Task 1: Add a failing UI contract test

**Files:**
- Create: `apps/web/tests/login-development-account-icon.test.mjs`

- [ ] **Step 1: Write the failing test**

Create a Node test that reads `LoginScreen.tsx` and `login.css` and asserts that the development helper uses `UserPlus`, exposes `aria-label="개발 계정 admin@posco.com 채우기"`, renders a `role="tooltip"` element, and has hover and focus-visible tooltip selectors. It must also assert that the helper text is no longer a direct text child of the button.

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test apps/web/tests/login-development-account-icon.test.mjs`

Expected: FAIL because `UserPlus`, tooltip markup, and tooltip visibility styles do not exist yet.

### Task 2: Implement the accessible icon helper

**Files:**
- Modify: `apps/web/src/components/LoginScreen.tsx:1,84-99`
- Modify: `apps/web/src/login.css:117-127`

- [ ] **Step 1: Implement the minimal JSX**

Import `UserPlus`, add the full Korean label as `aria-label` on the existing button, render `<UserPlus aria-hidden="true" />`, and add a tooltip span with `role="tooltip"`. Keep the development-only condition, disabled behavior, field values, and password focus unchanged.

- [ ] **Step 2: Implement the minimal CSS**

Make `.login-dev-account` a compact 30px circular icon button with a subtle cobalt-tinted background and visible keyboard focus. Position the tooltip above the button, hidden by default, and reveal it from both `:hover` and `:focus-visible`. Keep the tooltip on one line and disable pointer events.

- [ ] **Step 3: Run the contract test and verify GREEN**

Run: `node --test apps/web/tests/login-development-account-icon.test.mjs`

Expected: PASS with one passing test and zero failures.

### Task 3: Verify compilation and rendered behavior

**Files:**
- Verify: `apps/web/src/components/LoginScreen.tsx`
- Verify: `apps/web/src/login.css`

- [ ] **Step 1: Run frontend typecheck**

Run: `npm --prefix apps/web run typecheck`

Expected: exit code 0 with no TypeScript errors.

- [ ] **Step 2: Run frontend production build**

Run: `npm --prefix apps/web run build`

Expected: exit code 0 and a completed Vite build.

- [ ] **Step 3: Inspect the actual UI in the Codex app browser**

Open the development login page in the Codex app browser. Verify that only the icon is visible at rest, the tooltip appears on hover and keyboard focus, clicking fills `admin` and `posco.com` and focuses the password field, no text overlaps or clips at desktop and mobile widths, and the console has no errors.

- [ ] **Step 4: Review the scoped diff**

Run: `git diff --check -- apps/web/src/components/LoginScreen.tsx apps/web/src/login.css apps/web/tests/login-development-account-icon.test.mjs`

Expected: no whitespace errors. Do not commit or push.
