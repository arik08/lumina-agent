import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const sourceUrl = new URL("../src/mermaid-source.ts", import.meta.url);
const typescriptSource = await readFile(sourceUrl, "utf8");
const javascriptSource = ts.transpileModule(typescriptSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { repairMermaidSource } = await import(`data:text/javascript;base64,${Buffer.from(javascriptSource).toString("base64")}`);

test("quotes unquoted flowchart labels so parentheses remain label text", () => {
  const source = `flowchart TD
    A[문제가 무엇인가?] --> B{방정식 f(x)=0을 푸는가?}
    B -->|Yes| C[Newton-Raphson]
    B -->|No| D{미분방정식 dy/dt를 푸는가?}`;

  assert.equal(repairMermaidSource(source), `flowchart TD
    A["문제가 무엇인가?"] --> B{"방정식 f(x)=0을 푸는가?"}
    B -->|Yes| C["Newton-Raphson"]
    B -->|No| D{"미분방정식 dy/dt를 푸는가?"}`);
});

test("preserves authored quoted labels and non-flowchart diagrams", () => {
  assert.equal(
    repairMermaidSource('flowchart LR\nA["Already (quoted)"] --> B{`Markdown **label**`}'),
    'flowchart LR\nA["Already (quoted)"] --> B{`Markdown **label**`}',
  );
  assert.equal(
    repairMermaidSource("sequenceDiagram\nAlice->>Bob: f(x)"),
    "sequenceDiagram\nAlice->>Bob: f(x)",
  );
});

test("leaves labels with embedded quotes unchanged instead of guessing escapes", () => {
  const source = 'flowchart LR\nA[Press "Run" (now)] --> B[Done]';
  assert.equal(repairMermaidSource(source), 'flowchart LR\nA[Press "Run" (now)] --> B["Done"]');
});
