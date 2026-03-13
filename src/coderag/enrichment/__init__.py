"""CodeRAG enrichment modules.

Provides post-extraction enrichment phases:
- GitEnricher: git metadata (change frequency, co-change, ownership, churn)
- PHPStanEnricher: PHP type information from PHPStan static analysis
"""

from coderag.enrichment.git_enricher import GitEnricher
from coderag.enrichment.phpstan import EnrichmentReport, PHPStanEnricher, PHPStanResult

__all__ = ["GitEnricher", "PHPStanEnricher", "PHPStanResult", "EnrichmentReport"]
