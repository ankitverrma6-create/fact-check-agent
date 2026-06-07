"""Fact-checking orchestration and trust scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.credibility import CATEGORY_SCORES, aggregate_source_credibility, classify_domain
from src.gemini_client import GeminiClient, SourceCitation

STATUS_WEIGHTS = {
    "Verified": 1.0,
    "Inaccurate": 0.45,
    "False": 0.0,
}


@dataclass
class VerifiedClaim:
    claim: str
    claim_type: str
    status: str
    confidence_score: float
    correct_fact: str
    source_urls: list[str]
    reasoning: str
    source_credibility_score: float
    source_details: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class FactCheckReport:
    filename: str
    page_count: int
    claims: list[VerifiedClaim]
    trust_score: float
    source_credibility_score: float
    verified_count: int
    inaccurate_count: int
    false_count: int
    generated_at: str


def compute_trust_score(claims: list[VerifiedClaim]) -> float:
    """Compute document trust score (0-100)."""
    if not claims:
        return 0.0

    weighted_total = 0.0
    for item in claims:
        status_weight = STATUS_WEIGHTS.get(item.status, 0.25)
        confidence_factor = item.confidence_score / 100.0
        source_factor = item.source_credibility_score / 100.0 if item.source_credibility_score else 0.5
        claim_score = status_weight * confidence_factor * (0.7 + 0.3 * source_factor)
        weighted_total += claim_score

    raw_score = (weighted_total / len(claims)) * 100
    return round(min(max(raw_score, 0.0), 100.0), 1)


def _score_citation(citation: SourceCitation) -> dict[str, str | int]:
    domain = citation.domain or citation.url
    category = classify_domain(domain)
    return {
        "url": citation.url,
        "domain": domain,
        "category": category.value,
        "credibility_score": CATEGORY_SCORES[category],
    }


def _enrich_with_source_details(sources: list[SourceCitation]) -> tuple[list[dict], float]:
    details = [_score_citation(source) for source in sources]
    if not details:
        return [], 0.0
    scores = [int(item["credibility_score"]) for item in details]
    return details, round(sum(scores) / len(scores), 1)


class FactChecker:
    """End-to-end fact-checking pipeline (2 Gemini API calls per PDF)."""

    def __init__(
        self,
        gemini: GeminiClient,
        *,
        max_claims: int = 3,
    ) -> None:
        self.gemini = gemini
        self.max_claims = min(max_claims, 3)

    def run(
        self,
        document_text: str,
        *,
        filename: str,
        page_count: int,
        progress_callback=None,
    ) -> FactCheckReport:
        """Extract claims, verify in one batch call, and build a report."""
        if progress_callback:
            progress_callback("Extracting claims (1 Gemini call)...", 0.15)

        extracted = self.gemini.extract_claims(document_text, max_claims=self.max_claims)
        if not extracted:
            raise ValueError("No verifiable claims were found in the document.")

        if progress_callback:
            progress_callback(
                f"Verifying {len(extracted)} claims with Google Search (1 Gemini call)...",
                0.5,
            )

        results = self.gemini.verify_claims(extracted)
        verified_claims: list[VerifiedClaim] = []

        for claim, result in zip(extracted, results):
            source_details, source_avg = _enrich_with_source_details(result.sources)
            verified_claims.append(
                VerifiedClaim(
                    claim=result.claim,
                    claim_type=claim.claim_type,
                    status=result.status,
                    confidence_score=round(result.confidence_score, 1),
                    correct_fact=result.correct_fact,
                    source_urls=result.source_urls,
                    reasoning=result.reasoning,
                    source_credibility_score=source_avg,
                    source_details=source_details,
                )
            )

        if progress_callback:
            progress_callback("Calculating trust scores...", 0.9)

        trust_score = compute_trust_score(verified_claims)
        all_urls = [url for claim in verified_claims for url in claim.source_urls]
        overall_source_credibility = aggregate_source_credibility(all_urls)

        verified_count = sum(1 for c in verified_claims if c.status == "Verified")
        inaccurate_count = sum(1 for c in verified_claims if c.status == "Inaccurate")
        false_count = sum(1 for c in verified_claims if c.status == "False")

        if progress_callback:
            progress_callback("Analysis complete.", 1.0)

        return FactCheckReport(
            filename=filename,
            page_count=page_count,
            claims=verified_claims,
            trust_score=trust_score,
            source_credibility_score=overall_source_credibility,
            verified_count=verified_count,
            inaccurate_count=inaccurate_count,
            false_count=false_count,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
