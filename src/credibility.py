"""Source credibility scoring based on domain classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class SourceCategory(str, Enum):
    GOVERNMENT = "Government"
    RESEARCH = "Research Paper"
    MAJOR_NEWS = "Major News"
    BLOG = "Blog"


CATEGORY_SCORES: dict[SourceCategory, int] = {
    SourceCategory.GOVERNMENT: 100,
    SourceCategory.RESEARCH: 90,
    SourceCategory.MAJOR_NEWS: 75,
    SourceCategory.BLOG: 50,
}

GOVERNMENT_PATTERNS = (
    r"\.gov(\.|$)",
    r"\.gov\.uk",
    r"\.gc\.ca",
    r"\.europa\.eu",
    r"\.gov\.au",
    r"\.gob\.",
    r"who\.int",
    r"un\.org",
    r"cdc\.gov",
    r"nih\.gov",
    r"fda\.gov",
    r"sec\.gov",
    r"census\.gov",
    r"bls\.gov",
)

RESEARCH_PATTERNS = (
    r"\.edu(\.|$)",
    r"arxiv\.org",
    r"pubmed\.ncbi\.nlm\.nih\.gov",
    r"ncbi\.nlm\.nih\.gov",
    r"doi\.org",
    r"nature\.com",
    r"science\.org",
    r"sciencedirect\.com",
    r"springer\.com",
    r"wiley\.com",
    r"jstor\.org",
    r"researchgate\.net",
    r"acm\.org",
    r"ieee\.org",
)

MAJOR_NEWS_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "cnn.com",
    "npr.org",
    "economist.com",
    "aljazeera.com",
    "pbs.org",
    "abcnews.go.com",
    "cbsnews.com",
    "nbcnews.com",
    "time.com",
    "forbes.com",
    "cnbc.com",
}


@dataclass(frozen=True)
class SourceInfo:
    url: str
    domain: str
    category: SourceCategory
    credibility_score: int


def normalize_domain(url: str) -> str:
    """Extract and normalize hostname from URL."""
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = (parsed.netloc or parsed.path).lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def classify_domain(domain: str) -> SourceCategory:
    """Classify a domain into a credibility category."""
    if not domain:
        return SourceCategory.BLOG

    for pattern in GOVERNMENT_PATTERNS:
        if re.search(pattern, domain):
            return SourceCategory.GOVERNMENT

    for pattern in RESEARCH_PATTERNS:
        if re.search(pattern, domain):
            return SourceCategory.RESEARCH

    if domain in MAJOR_NEWS_DOMAINS or any(
        domain.endswith(f".{news}") for news in MAJOR_NEWS_DOMAINS
    ):
        return SourceCategory.MAJOR_NEWS

    return SourceCategory.BLOG


def score_source(url: str) -> SourceInfo:
    """Return credibility metadata for a source URL."""
    domain = normalize_domain(url)
    category = classify_domain(domain)
    return SourceInfo(
        url=url,
        domain=domain,
        category=category,
        credibility_score=CATEGORY_SCORES[category],
    )


def aggregate_source_credibility(urls: list[str]) -> float:
    """Average credibility score across unique source URLs."""
    if not urls:
        return 0.0
    unique_urls = list(dict.fromkeys(urls))
    scores = [score_source(url).credibility_score for url in unique_urls]
    return round(sum(scores) / len(scores), 1)
