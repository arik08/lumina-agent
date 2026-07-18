from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..providers.types import ProviderAdapter, ProviderMessage, ProviderRequest


KNOWLEDGE_EXTRACTOR_VERSION = "knowledge-structured-v1"
MAX_EVIDENCE_SEGMENTS = 40
MAX_INPUT_CHARACTERS = 60_000
MAX_ENTITIES = 80
MAX_STATEMENTS = 160


class _ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    entity_type: str = Field(
        alias="entityType",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    )
    canonical_name: str = Field(alias="canonicalName", min_length=1, max_length=500)
    description: str = Field(default="", max_length=2_000)


class _ExtractedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_key: str = Field(alias="subjectKey", min_length=1, max_length=80)
    predicate_key: str = Field(
        alias="predicateKey",
        min_length=1,
        max_length=160,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    object_key: str = Field(alias="objectKey", min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    evidence_segment_ids: list[str] = Field(
        alias="evidenceSegmentIds", min_length=1, max_length=8
    )


class _ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[_ExtractedEntity] = Field(max_length=MAX_ENTITIES)
    statements: list[_ExtractedStatement] = Field(max_length=MAX_STATEMENTS)


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    id: str
    text: str
    locator: dict[str, object]


@dataclass(frozen=True, slots=True)
class KnowledgeExtraction:
    entities: tuple[_ExtractedEntity, ...]
    statements: tuple[_ExtractedStatement, ...]
    input_segment_count: int
    input_character_count: int
    input_tokens: int
    output_tokens: int


def _response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "knowledge_source_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "maxItems": MAX_ENTITIES,
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "entityType": {"type": "string"},
                                "canonicalName": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": [
                                "key",
                                "entityType",
                                "canonicalName",
                                "description",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "statements": {
                        "type": "array",
                        "maxItems": MAX_STATEMENTS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "subjectKey": {"type": "string"},
                                "predicateKey": {"type": "string"},
                                "objectKey": {"type": "string"},
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "evidenceSegmentIds": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 8,
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "subjectKey",
                                "predicateKey",
                                "objectKey",
                                "confidence",
                                "evidenceSegmentIds",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["entities", "statements"],
                "additionalProperties": False,
            },
        },
    }


def _bounded_evidence(evidence: list[EvidenceInput]) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    character_count = 0
    for item in evidence[:MAX_EVIDENCE_SEGMENTS]:
        remaining = MAX_INPUT_CHARACTERS - character_count
        if remaining <= 0:
            break
        text = item.text[:remaining]
        rows.append({"id": item.id, "locator": item.locator, "text": text})
        character_count += len(text)
    return rows, character_count


async def extract_knowledge(
    *,
    provider: ProviderAdapter,
    model: str,
    source_title: str,
    evidence: list[EvidenceInput],
) -> KnowledgeExtraction:
    rows, character_count = _bounded_evidence(evidence)
    if not rows:
        raise ValueError("Knowledge extraction requires at least one evidence segment")
    prompt = (
        "Extract a compact evidence-grounded knowledge graph from the supplied source. "
        "Use short stable ASCII keys, conservative entity types, and uppercase snake-case "
        "predicates. Every statement must reference one or more supplied evidence segment "
        "IDs that directly support it. Do not infer unsupported facts, create literal-only "
        "claims, or return duplicate entities or statements. Return empty arrays when the "
        "source has no reliable relationships. Keep Korean names and descriptions in Korean.\n\n"
        f"Source title: {source_title}\nEvidence:\n"
        + json.dumps(rows, ensure_ascii=False)
    )
    chunks: list[str] = []
    input_tokens = 0
    output_tokens = 0
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content=(
                        "You extract a reviewable knowledge graph. Return only the strict JSON schema."
                    ),
                ),
                ProviderMessage(role="user", content=prompt),
            ),
            response_format=_response_format(),
            max_output_tokens=5_000,
            temperature=0,
            metadata={
                "purpose": "knowledge_ingestion",
                "extractor_version": KNOWLEDGE_EXTRACTOR_VERSION,
            },
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
        elif event.type == "usage" and event.usage is not None:
            input_tokens = event.usage.input_tokens
            output_tokens = event.usage.output_tokens
    try:
        payload = _ExtractionPayload.model_validate_json("".join(chunks).strip())
    except ValidationError as exc:
        raise ValueError("Provider returned invalid Knowledge extraction JSON") from exc

    evidence_ids = {str(row["id"]) for row in rows}
    entity_keys: set[str] = set()
    entities: list[_ExtractedEntity] = []
    for entity in payload.entities:
        if entity.key in entity_keys:
            continue
        entity_keys.add(entity.key)
        entities.append(entity)

    statements: list[_ExtractedStatement] = []
    statement_keys: set[tuple[str, str, str]] = set()
    for statement in payload.statements:
        edge_key = (
            statement.subject_key,
            statement.predicate_key,
            statement.object_key,
        )
        if (
            statement.subject_key not in entity_keys
            or statement.object_key not in entity_keys
            or not set(statement.evidence_segment_ids).issubset(evidence_ids)
            or edge_key in statement_keys
        ):
            continue
        statement_keys.add(edge_key)
        statements.append(statement)
    return KnowledgeExtraction(
        entities=tuple(entities),
        statements=tuple(statements),
        input_segment_count=len(rows),
        input_character_count=character_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
