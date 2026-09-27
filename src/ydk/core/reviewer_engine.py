"""Cached fan-out reviewer engine using the direct Anthropic Messages API.

Replaces the Strands-based reviewer path with direct ``anthropic.Anthropic``
calls that share a cached system prefix across all reviewers.  The first
reviewer call primes the cache; subsequent calls fan out in parallel and
hit the cached prefix, cutting per-reviewer latency from ~10s to ~2-4s.

Uses structured outputs (``messages.parse`` with the :class:`ReviewVerdict`
pydantic model) so every response is schema-valid — no text parsing needed.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import anthropic

from ydk.core.claude_client import DEFAULT_API_KEY_ENV, ClaudeAPIError, build_client, parse_response

logger = logging.getLogger("ydk.reviewer_engine")


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
    """Runs spec reviewers using the Anthropic Messages API with prompt caching."""

    def __init__(self, api_key_env: str = DEFAULT_API_KEY_ENV, *, client: anthropic.Anthropic | None = None):
        self._client = client or build_client(api_key_env, timeout=300.0, max_retries=2)

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_blocks(self, spec_content: str) -> list[dict[str, Any]]:
        """Build system prompt with spec content and cache point."""
        return [
            {
                "type": "text",
                "text": (
                    "You are a specification quality evaluator. "
                    "For each criterion, evaluate the document and respond with: "
                    "score (0-10), reasoning (string), suggestions (list of strings), "
                    "findings (list of objects with line, text, issue keys)."
                ),
            },
            {
                "type": "text",
                "text": f"Here are the specification documents to evaluate:\n\n{spec_content}",
                "cache_control": {"type": "ephemeral"},
            },
        ]

    # ------------------------------------------------------------------
    # Single reviewer call
    # ------------------------------------------------------------------

    def _call_reviewer(
        self,
        system_blocks: list[dict[str, Any]],
        model_id: str,
        reviewer_id: str,
        reviewer_prompt: str,
    ) -> dict[str, Any]:
        """Single Anthropic Messages API call for one reviewer."""
        start = time.monotonic()
        logger.info("Reviewer %s: calling Anthropic (%s)", reviewer_id, model_id)

        response = parse_response(
            self._client,
            ReviewVerdict,
            model=model_id,
            max_tokens=8192,
            system=system_blocks,
            messages=[{"role": "user", "content": reviewer_prompt}],
        )
        verdict = cast("ReviewVerdict", response.parsed_output)
        usage = response.usage

        elapsed = time.monotonic() - start

        # Log cache metrics
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        logger.info(
            "Reviewer %s: done in %.1fs — input=%d, output=%d, cache_read=%d, cache_write=%d",
            reviewer_id,
            elapsed,
            input_tokens,
            output_tokens,
            cache_read,
            cache_write,
        )

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
        model_tiers: dict[str, str],
        max_workers: int = 10,
    ) -> list[dict[str, Any]]:
        """Run all reviewers with per-model-tier cache priming + parallel fan-out.

        Groups reviewers by model_tier so that each tier's cache is primed
        independently.  This ensures Sonnet reviewers hit Sonnet cache and
        Haiku reviewers hit Haiku cache.

        Args:
            spec_content: The specification text to review.
            reviewers: List of reviewer dicts, each with keys:
                id, name, system_prompt, model_tier, threshold, group.
            model_tiers: Map of tier name to Anthropic model ID
                (e.g. ``{"smart": "claude-sonnet-4-6"}``).
            max_workers: Maximum parallel threads for fan-out phase.

        Returns:
            Sorted list of result dicts (by reviewer_id).
        """
        from collections import defaultdict

        total_start = time.monotonic()

        if not reviewers:
            return []

        # Build cached prefix (shared across all reviewers)
        system_blocks = self._build_system_blocks(spec_content)

        # Group reviewers by model tier
        by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rev in reviewers:
            by_tier[rev.get("model_tier", "smart")].append(rev)

        results: list[dict[str, Any]] = []

        # Process each tier: prime cache with first reviewer, fan out rest
        for tier, tier_reviewers in by_tier.items():
            model_id = model_tiers.get(tier, model_tiers.get("smart", ""))

            # Step 1: Prime cache for this tier (synchronous)
            first = tier_reviewers[0]
            logger.info(
                "Priming cache for tier=%s model=%s with reviewer %s",
                tier,
                model_id,
                first["id"],
            )

            first_result = self._call_reviewer(
                system_blocks=system_blocks,
                model_id=model_id,
                reviewer_id=first["id"],
                reviewer_prompt=first["system_prompt"],
            )
            first_result["name"] = first["name"]
            first_result["passed"] = first_result.get("score", 0) >= first.get("threshold", 8)
            results.append(first_result)

            # Step 2: Fan out remaining reviewers for this tier in parallel
            remaining = tier_reviewers[1:]
            if remaining:
                logger.info(
                    "Fanning out %d remaining tier=%s reviewers in parallel",
                    len(remaining),
                    tier,
                )
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures: dict[Any, dict[str, Any]] = {}
                    for rev in remaining:
                        future = executor.submit(
                            self._call_reviewer,
                            system_blocks=system_blocks,
                            model_id=model_id,
                            reviewer_id=rev["id"],
                            reviewer_prompt=rev["system_prompt"],
                        )
                        futures[future] = rev

                    for future in as_completed(futures):
                        rev = futures[future]
                        try:
                            result = future.result()
                            result["name"] = rev["name"]
                            result["passed"] = result.get("score", 0) >= rev.get("threshold", 8)
                            results.append(result)
                        except ClaudeAPIError:
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

        total_elapsed = time.monotonic() - total_start
        logger.info("All reviewers completed in %.1fs", total_elapsed)

        results.sort(key=lambda r: r.get("reviewer_id", ""))
        return results
