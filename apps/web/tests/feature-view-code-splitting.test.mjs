import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");


test("secondary feature views load only when their workspace is opened", () => {
  for (const view of [
    "AdminView",
    "ArtifactLibraryView",
    "HelpCenterView",
    "MarketplaceView",
    "MemoryView",
    "ProjectFilesView",
    "ProjectSettings",
    "SchedulesView",
  ]) {
    assert.match(app, new RegExp(`const ${view} = lazy\\(\\(\\) => import\\(\\"\\./components/${view}\\"\\)`));
    assert.doesNotMatch(app, new RegExp(`import \\{ ${view} \\} from \\"\\./components/${view}\\"`));
  }
  assert.match(app, /<Suspense fallback=\{<FeatureViewLoading \/>\}>/);
  assert.match(app, /className="feature-view feature-view-loading" aria-label="화면 로딩" aria-busy="true"/);
});
