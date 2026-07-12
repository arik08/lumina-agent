import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("completed icon is hidden for tool and model-processing rows", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /\$\{complete \? "without-status-icon" : ""\}/);
  assert.doesNotMatch(app, /showCompletedIcon/);
  assert.match(app, /model-processing-row \$\{running \? "" : "without-status-icon"\}/);
  assert.match(app, /<span className="model-processing-label">/);
  assert.match(app, /\{running \? <LoaderCircle className="status-icon is-running"/);
  assert.match(stylesheet, /\.tool-call-trigger\.without-status-icon\s*\{[^}]*grid-template-columns:/s);
  assert.match(stylesheet, /@media \(max-width: 720px\)[\s\S]*\.tool-call-trigger\.without-status-icon\s*\{[^}]*grid-template-columns:/s);
});
