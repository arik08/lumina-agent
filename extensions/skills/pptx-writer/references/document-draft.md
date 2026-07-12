# Document-To-PPT Draft Workflow

Use this for PDF, DOCX, Markdown, URL, transcript, or source dossier inputs that should become an editable presentation draft.

## Draft Contract

Call the output an editable draft unless the user explicitly requests final polish and enough evidence/assets are available. PPT Master-style workflows remove blank-page work; they do not guarantee board-ready polish without QA.

## Steps

1. Convert or extract the source into structured Markdown/text.
2. Separate message from raw material:
   - thesis
   - audience decision
   - sections
   - slide-level claims
   - evidence/source mapping
   - risks/caveats
3. Plan an executive deck before creating slides.
4. Generate editable PPTX with PptxGenJS/template path.
5. Run QA and final reviewer pass.

## Useful Vendored References

- `vendor/ppt-master/references/strategist.md`
- `vendor/ppt-master/references/executor-general.md`
- `vendor/ppt-master/references/shared-standards.md`
- `vendor/ppt-master/scripts/source_to_md/`
- `vendor/ppt-master/scripts/svg_to_pptx/`

## Security and Source Handling

- Do not send confidential source content to external APIs unless the user explicitly approves.
- Use local extraction first for internal documents.
- Preserve source traceability with short slide notes or source rails when the deck uses specific claims.

