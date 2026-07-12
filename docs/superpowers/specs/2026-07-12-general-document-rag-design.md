# General Document RAG Design

## Goal

Convert `extensions/mcp/vector_db` and its `vector-db-rag` skill from an organization-work GraphRAG into a general-purpose local document RAG system. Users can place ordinary documents in the documents directory, index them, and search their contents without preparing organization-specific headings or metadata.

The previous organization hierarchy concept is removed. Backward compatibility for `explore_org`, `org_unit`, and `org_path` is not required.

## Supported Documents

The initial implementation supports:

- Markdown (`.md`, `.markdown`)
- Plain text (`.txt`)
- PDF (`.pdf`)
- Word (`.docx`)
- PowerPoint (`.pptx`)
- Excel (`.xlsx`)
- CSV (`.csv`)
- HTML (`.html`, `.htm`)

Encrypted files, legacy binary Office formats, image-only PDFs, and OCR are outside this change. A file that cannot be extracted is reported as an indexing failure without preventing other files from being indexed.

## Architecture

The indexer has three explicit stages:

1. A format-specific extractor reads a source file and emits normalized sections.
2. A shared chunker splits sections into retrieval-sized chunks while preserving source locations.
3. The SQLite store persists documents, sections, chunks, graph relationships, and deterministic local embeddings.

Each extractor emits the same logical section contract:

```text
ExtractedSection
├─ title
├─ section_path
├─ text
├─ location_kind
├─ location_start
├─ location_end
└─ optional structured metadata
```

The store remains local and incremental. Unchanged files are retained, changed files are replaced atomically, and records for deleted source files are removed.

## Format Extraction

- Markdown: headings form the section hierarchy; body text and tables remain searchable.
- TXT: paragraphs become sections with line ranges.
- HTML: scripts, styles, and non-content markup are removed; headings form the hierarchy.
- PDF: extracted text is grouped by page, with page numbers retained.
- DOCX: document headings form the hierarchy; paragraphs and tables are included.
- PPTX: each slide is a section; slide title and shape text are included.
- XLSX: each worksheet is a top-level section; bounded row groups form child sections and retain sheet name and row range.
- CSV: bounded row groups form sections and retain row ranges. Encoding is detected from a small safe fallback set rather than silently discarding undecodable content.

The implementation uses the document libraries already declared by the server project where possible. HTML parsing uses the Python standard library unless a demonstrated extraction requirement justifies another dependency.

## Storage Contract

Organization-specific columns and response fields are replaced by generic document fields. A retrieval result includes:

- `document_id`
- `document_name`
- `source_path`
- `file_type`
- `section_path`
- `location_kind`
- `location_start`
- `location_end`
- `source_label`
- `citation`
- `source_chip`
- `excerpt`
- `score`

Locations are expressed in the source document's natural unit: line, page, slide, sheet row, or section. Visible citations prefer the document name and natural location rather than database identifiers.

Because the schema meaning changes, the implementation may rebuild an existing database instead of migrating organization-specific data. Source documents remain the recoverable source of truth.

## Search and MCP Tools

The MCP server exposes four tools:

### `retrieve_context`

Searches all indexed documents or one selected document. It accepts a query, optional document filter, search mode, and result limit. Hybrid mode combines deterministic vector similarity with section graph context and is the default.

### `explore_document`

Browses a selected document's section structure and retrieves neighboring or child sections around a section query. It replaces `explore_org` and never interprets terms as organization units.

### `list_sources`

Lists indexed files, types, section and chunk counts, index timestamps, and any relevant extraction metadata.

### `store_status`

Reports database location, supported formats, total counts, and whether the store is ready.

The CLI mirrors these operations with `index`, `search`, `explore-document`, `sources`, `status`, and `clear` commands.

## Skill Behavior

The `vector-db-rag` skill describes a general local document knowledge base. It triggers for questions that require searching, comparing, summarizing, or locating evidence across indexed documents.

The skill instructs the agent to:

1. Check `store_status` or `list_sources` before relying on the index.
2. Use `retrieve_context` for factual questions, comparisons, and cross-document synthesis.
3. Use `explore_document` for document structure, section context, and nearby passages.
4. Preserve the returned source identifiers and natural locations in answers.
5. State clearly when evidence is missing, extraction failed, or the index is empty.

No organization, department, role, or company-work assumptions remain in the skill, MCP description, catalog translation, README, tool docstrings, or examples.

## Errors and Safety

- Path traversal and files outside the configured documents directory are rejected.
- Generated databases and source documents remain local-only and ignored by Git.
- One malformed or unsupported file produces a structured per-file error while other files continue indexing.
- Password-protected or encrypted documents are reported as unsupported.
- Extracted text is treated as untrusted document content, not as agent instructions.
- Search results do not imply that retrieved document text is authoritative or safe to execute.

## Testing

Implementation follows test-driven development. Tests cover:

- One representative fixture for every supported format.
- Normalized section and natural-location metadata.
- Hybrid retrieval across multiple document types.
- Exact document filtering.
- `explore_document` hierarchy and neighboring context.
- Incremental indexing of unchanged, changed, and deleted sources.
- Isolation and reporting of malformed files.
- Removal of organization-specific MCP and CLI contracts.
- Source labels, chips, excerpts, and natural-location citations.
- MCP overview and repository catalog descriptions.

Tests use small generated fixtures and do not commit private or real business documents.

## Scope Boundary

This change does not add a document-upload UI, hosted vector database, OCR, semantic reranking service, external embedding API, background indexing service, access-control model, or cross-project shared index. Those require separate product and security designs.
