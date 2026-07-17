# Upstream Sources and Refresh

The detailed SCAMPER, Six Thinking Hats, Design Thinking, Jobs to Be Done, and Five Whys method cards are copied from [`neurofoo/agent-skills`](https://github.com/neurofoo/agent-skills) under its MIT license. The exact commit, file paths, target names, and SHA-256 digests are recorded in `upstream-sources.json`. The included `upstream-neurofoo-license.txt` must remain with redistributed copies.

The upstream cards are reference material. Their `user-invocable` metadata and `$ARGUMENTS` placeholders do not alter this Skill's frontmatter or invocation behavior.

## Verify the Vendored Copy

From the repository root, run:

```powershell
python extensions/skills/idea-orchestrator/scripts/sync_upstream.py --check
```

This performs no network access and fails if a vendored file differs from its pinned digest.

## Refresh from GitHub

1. Review the upstream repository's current license and the diff for every desired source file.
2. Change `revision`, file entries, and expected SHA-256 values in `upstream-sources.json` intentionally. Never point the manifest at a moving branch such as `main`.
3. Run:

   ```powershell
   python extensions/skills/idea-orchestrator/scripts/sync_upstream.py --sync
   python extensions/skills/idea-orchestrator/scripts/sync_upstream.py --check
   ```

4. Review `git diff`, run the Skill validators, and commit the source manifest, license, and refreshed files together.

The sync script accepts only `raw.githubusercontent.com`, writes only declared files inside this Skill's `references/` directory, verifies SHA-256 before replacement, and does not execute downloaded content.
