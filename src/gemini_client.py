"""Google Gemini client for claim extraction and verification."""

from __future__ import annotations

import json
import re
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from src.config import configure_gemini_environment

MAX_DOCUMENT_CHARS = 8_000

STATUS_ALIASES = {
    "verified": "Verified",
    "correct": "Verified",
    "true": "Verified",
    "accurate": "Verified",
    "inaccurate": "Inaccurate",
    "incorrect": "Inaccurate",
    "partially correct": "Inaccurate",
    "partially incorrect": "Inaccurate",
    "misleading": "Inaccurate",
    "false": "False",
    "untrue": "False",
    "debunked": "False",
}

EXTRACTION_PROMPT = """Extract up to {max_claims} verifiable factual claims (stats, dates, percentages, figures).
Skip opinions. Each claim must stand alone.
Return JSON only: {{"claims":[{{"claim":"...","claim_type":"statistic|percentage|date|financial|general","context":"..."}}]}}

Text:
{document_text}"""

BATCH_VERIFICATION_PROMPT = """Fact-check every claim below using Google Search.
For each claim return: claim, status (Verified|Inaccurate|False), confidence_score (0-100), correct_fact, reasoning (1 sentence).
Return JSON only: {{"results":[{{"claim":"...","status":"...","confidence_score":85,"correct_fact":"...","reasoning":"..."}}]}}

Claims:
{claims_block}"""


class ExtractedClaim(BaseModel):
    claim: str
    claim_type: str = Field(
        description="One of: statistic, percentage, date, financial, general"
    )
    context: str = ""


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


class SourceCitation(BaseModel):
    url: str
    domain: str = ""


class VerificationResult(BaseModel):
    claim: str
    status: str = Field(description="Verified, Inaccurate, or False")
    confidence_score: float = Field(ge=0, le=100)
    correct_fact: str
    source_urls: list[str] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    reasoning: str = ""


class BatchVerificationResult(BaseModel):
    results: list[VerificationResult]


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract and parse JSON from model response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("Model did not return valid JSON.")
        return json.loads(match.group())


def _normalize_status(status: str) -> str:
    normalized = status.strip()
    mapped = STATUS_ALIASES.get(normalized.lower())
    if mapped:
        return mapped
    capitalized = normalized.capitalize()
    if capitalized in {"Verified", "Inaccurate", "False"}:
        return capitalized
    return "Inaccurate"


def _extract_grounding_sources(response: Any) -> list[SourceCitation]:
    """Collect citation URLs and domains from Gemini grounding metadata."""
    citations: list[SourceCitation] = []
    seen: set[str] = set()

    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        if not metadata:
            continue
        for chunk in getattr(metadata, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            if not web or not web.uri or web.uri in seen:
                continue
            seen.add(web.uri)
            citations.append(
                SourceCitation(url=web.uri, domain=(web.title or "").strip())
            )
    return citations


def _build_claims_block(claims: list[ExtractedClaim]) -> str:
    lines: list[str] = []
    for index, claim in enumerate(claims, start=1):
        context = f" | {claim.context}" if claim.context else ""
        lines.append(f"{index}. [{claim.claim_type}] {claim.claim}{context}")
    return "\n".join(lines)


def _attach_sources(
    result: VerificationResult,
    grounding_sources: list[SourceCitation],
) -> VerificationResult:
    urls = list(dict.fromkeys(result.source_urls + [s.url for s in grounding_sources]))
    sources = list(grounding_sources)
    if not sources and urls:
        sources = [SourceCitation(url=url, domain="") for url in urls]
    return result.model_copy(
        update={
            "status": _normalize_status(result.status),
            "source_urls": urls,
            "sources": sources,
        }
    )


class GeminiClient:
    """Wrapper around Google Gemini for extraction and verification."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = configure_gemini_environment(api_key)
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required for Google AI Studio.")
        self.client = genai.Client(vertexai=False, api_key=self.api_key)
        self.model = model

    def generate_text(self, prompt: str) -> str:
        """Generate plain-text output (Google AI Studio generateContent)."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        text = response.text or ""
        if not text.strip():
            raise ValueError("Empty response from Gemini.")
        return text

    def _generate(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        text = response.text or ""
        if not text.strip():
            raise ValueError("Empty response from Gemini.")
        return text

    def _generate_with_google_search(self, prompt: str) -> Any:
        """Generate content with Google Search grounding enabled."""
        return self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

    def extract_claims(self, document_text: str, *, max_claims: int = 3) -> list[ExtractedClaim]:
        """Extract verifiable claims from document text (single API call)."""
        prompt = EXTRACTION_PROMPT.format(
            max_claims=max_claims,
            document_text=document_text[:MAX_DOCUMENT_CHARS],
        )
        raw = self._generate(prompt)
        data = _parse_json_response(raw)

        try:
            parsed = ClaimExtractionResult.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid claim extraction response: {exc}") from exc

        return parsed.claims[:max_claims]

    def verify_claims(self, claims: list[ExtractedClaim]) -> list[VerificationResult]:
        """Verify all claims in a single Google Search grounding call."""
        if not claims:
            return []

        prompt = BATCH_VERIFICATION_PROMPT.format(claims_block=_build_claims_block(claims))
        response = self._generate_with_google_search(prompt)
        raw = response.text or ""
        if not raw.strip():
            raise ValueError("Empty verification response from Gemini.")

        data = _parse_json_response(raw)
        grounding_sources = _extract_grounding_sources(response)

        try:
            parsed = BatchVerificationResult.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid batch verification response: {exc}") from exc

        by_claim = {item.claim.strip().lower(): item for item in parsed.results}
        verified: list[VerificationResult] = []

        for claim in claims:
            result = by_claim.get(claim.claim.strip().lower())
            if result is None:
                for candidate in parsed.results:
                    if candidate.claim.strip().lower() in claim.claim.lower() or claim.claim.lower() in candidate.claim.strip().lower():
                        result = candidate
                        break
            if result is None and len(parsed.results) == len(claims):
                result = parsed.results[len(verified)]
            if result is None:
                result = VerificationResult(
                    claim=claim.claim,
                    status="Inaccurate",
                    confidence_score=0.0,
                    correct_fact="Unable to verify this claim.",
                    reasoning="No verification result returned for this claim.",
                )
            verified.append(_attach_sources(result.model_copy(update={"claim": claim.claim}), grounding_sources))

        return verified
