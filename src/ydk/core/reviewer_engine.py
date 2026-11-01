"""Cached fan-out reviewer engine running spec reviewers through an LLM provider.

Every reviewer shares the same system instruction and a cacheable context
block holding the spec.  With the Anthropic provider that block is marked
``cache_control: ephemeral``: the first reviewer call per model tier primes
the cache and the rest fan out in parallel and hit the cached prefix.  With
the subagent provider each reviewer becomes a request file; the engine
collects every pending request and raises one ``SubagentHandoff`` for all.

Responses are validated against the :class:`ReviewVerdict` pydantic model.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ydk.core.claude_client import ClaudeAPIError
from ydk.core.llm_provider import SubagentHandoff, SubagentResponseError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ydk.core.llm_provider import StructuredLLMProvider

logger = logging.getLogger("ydk.reviewer_engine")

SYSTEM_PROMPT = (
    "You are a specification quality evaluator. "
    "For each criterion, evaluate the document and respond with: "
    "score (0-10), reasoning (string), suggestions (list of strings), "
    "findings (list of objects with line, text, issue keys)."
)


def spec_context(spec_content: str) -> str:
    """Return the cacheable context block that carries the spec to every reviewer."""
    return f"Here are the specification documents to evaluate:\n\n{spec_content}"


class ReviewFinding(BaseModel):
    """One specific problem found in the spec."""

    line: int = Field(description="Line number")
    text: str = Field(description="The problematic text")
    issue: str = Field(description="What's wrong")


class ReviewVerdict(BaseModel):
    """Structured review evaluation returned by each reviewer call."""

    score: int = Field(description="Score from 0-10")
    reasoning: str = Field(description="Explanation for the score")
    suggestions: list[str] = Field(description="Specific actionable suggestions for improvement")
    findings: list[ReviewFinding] = Field(description="Specific findings with line numbers")


class ReviewerEngine:
    """Runs spec reviewers through a structured LLM provider chosen per model tier."""

    def __init__(self, provider_for_tier: Callable[[str], StructuredLLMProvider]) -> None:
        self._provider_for_tier = provider_for_tier
        self._providers: dict[str, StructuredLLMProvider] = {}

    def _provider(self, tier: str) -> StructuredLLMProvider:
        if tier not in self._providers:
            self._providers[tier] = self._provider_for_tier(tier)
        return self._providers[tier]

    # ------------------------------------------------------------------
    # Single reviewer call
    # ------------------------------------------------------------------

    def _call_reviewer(
        self,
        provider: StructuredLLMProvider,
        spec_content: str,
        reviewer_id: str,
        reviewer_prompt: str,
    ) -> dict[str, Any]:
        """One structured provider call for one reviewer."""
        start = time.monotonic()
        logger.info("Reviewer %s: calling %s", reviewer_id, type(provider).__name__)

        verdict = provider.invoke_structured(
            reviewer_prompt,
            ReviewVerdict,
            system=SYSTEM_PROMPT,
            cacheable_context=spec_context(spec_content),
        )

        elapsed = time.monotonic() - start
        logger.info("Reviewer %s: done in %.1fs", reviewer_id, elapsed)

        return {
            "reviewer_id": reviewer_id,
            "score": verdict.score,
            "reasoning": verdict.reasoning,
            "suggestions": verdict.suggestions,
            "findings": [f.model_dump() for f in verdict.findings],
            "elapsed_seconds": elapsed,
        }

    # ------------------------------------------------------------------
    # Orchestration: prime per-tier + fan-out
    # ------------------------------------------------------------------

    def run_all(
        self,
        spec_content: str,
        reviewers: list[dict[str, Any]],
        max_workers: int = 10,
    ) -> list[dict[str, Any]]:
        """Run all reviewers with per-model-tier cache priming + parallel fan-out.

        Groups reviewers by model_tier so that each tier's cache is primed
        independently.  Reviewers whose answer is handed off to a subagent
        are collected; once every reviewer has run, a single
        ``SubagentHandoff`` listing all pending requests is raised.

        Args:
            spec_content: The specification text to review.
            reviewers: List of reviewer dicts, each with keys:
                id, name, system_prompt, model_tier, threshold, group.
            max_workers: Maximum parallel threads for fan-out phase.

        Returns:
            Sorted list of result dicts (by reviewer_id).
        """
        total_start = time.monotonic()

        if not reviewers:
            return []

        by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rev in reviewers:
            by_tier[rev.get("model_tier", "review")].append(rev)

        results: list[dict[str, Any]] = []
        pending: list[Path] = []

        def record(rev: dict[str, Any], result: dict[str, Any]) -> None:
            result["name"] = rev["name"]
            result["passed"] = result.get("score", 0) >= rev.get("threshold", 8)
            results.append(result)

        for tier, tier_reviewers in by_tier.items():
            provider = self._provider(tier)

            # Step 1: Prime cache for this tier (synchronous)
            first = tier_reviewers[0]
            logger.info("Priming cache for tier=%s with reviewer %s", tier, first["id"])
            try:
                record(first, self._call_reviewer(provider, spec_content, first["id"], first["system_prompt"]))
            except SubagentHandoff as handoff:
                pending.extend(handoff.request_paths)

            # Step 2: Fan out remaining reviewers for this tier in parallel
            remaining = tier_reviewers[1:]
            if not remaining:
                continue
            logger.info("Fanning out %d remaining tier=%s reviewers in parallel", len(remaining), tier)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._call_reviewer, provider, spec_content, rev["id"], rev["system_prompt"]): rev
                    for rev in remaining
                }
                for future in as_completed(futures):
                    rev = futures[future]
                    try:
                        record(rev, future.result())
                    except SubagentHandoff as handoff:
                        pending.extend(handoff.request_paths)
                    except (ClaudeAPIError, SubagentResponseError):
                        raise
                    except Exception as exc:
                        results.append(
                            {
                                "reviewer_id": rev["id"],
                                "name": rev["name"],
                                "score": 0,
                                "passed": False,
                                "reasoning": f"THREAD ERROR: {type(exc).__name__}: {str(exc)[:200]}",
                                "suggestions": [],
                                "findings": [],
                                "elapsed_seconds": 0,
                            }
                        )

        if pending:
            raise SubagentHandoff(sorted(set(pending)))

        logger.info("All reviewers completed in %.1fs", time.monotonic() - total_start)
        results.sort(key=lambda r: r.get("reviewer_id", ""))
        return results
