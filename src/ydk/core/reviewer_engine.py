"""Cached fan-out reviewer engine using the direct Anthropic Messages API.

Replaces the Strands-based reviewer path with direct ``anthropic.Anthropic``
calls that share a cached system prefix across all reviewers.  The first
reviewer call primes the cache; subsequent calls fan out in parallel and
hit the cached prefix, cutting per-reviewer latency from ~10s to ~2-4s.

Uses Anthropic tool-use with forced ``tool_choice`` to guarantee structured
JSON output — no fragile text-parsing needed.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

import anthropic

logger = logging.getLogger("ydk.reviewer_engine")

# Tool schema that forces the model to return structured JSON.
REVIEW_TOOL_SPEC: dict[str, Any] = {
    "name": "submit_review",
    "description": "Submit the structured review evaluation result",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "Score from 0-10"},
            "reasoning": {"type": "string", "description": "Explanation for the score"},
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific actionable suggestions for improvement",
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "line": {"type": "number", "description": "Line number"},
                        "text": {"type": "string", "description": "The problematic text"},
                        "issue": {"type": "string", "description": "What's wrong"},
                    },
                },
                "description": "Specific findings with line numbers",
            },
        },
        "required": ["score", "reasoning", "suggestions", "findings"],
    },
}


class ReviewerEngine:
    """Runs spec reviewers using the Anthropic Messages API with prompt caching."""

    def __init__(self, api_key: str | None = None):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=2)

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
                    "For each criterion, evaluate the document and call the submit_review tool with: "
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

        try:
            response = self._client.messages.create(
                model=model_id,
                max_tokens=8192,
                temperature=0.0,
                system=cast("Any", system_blocks),
                messages=[
                    {
                        "role": "user",
                        "content": reviewer_prompt,
                    },
                ],
                tools=cast("Any", [REVIEW_TOOL_SPEC]),
                tool_choice={"type": "tool", "name": "submit_review"},
            )

            elapsed = time.monotonic() - start

            # Log cache metrics
            usage = response.usage
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

            # Extract structured data from tool_use block
            tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
            if tool_use_block is not None:
                data = cast("dict[str, Any]", cast("Any", tool_use_block).input)
                return {
                    "reviewer_id": reviewer_id,
                    "score": int(data.get("score", 0)),
                    "reasoning": str(data.get("reasoning", "")),
                    "suggestions": [str(s) for s in data.get("suggestions", [])],
                    "findings": data.get("findings", []),
                    "elapsed_seconds": elapsed,
                }

            # No tool_use block found — should not happen with forced tool_choice
            logger.warning("Reviewer %s: no tool_use block in response", reviewer_id)
            return {
                "reviewer_id": reviewer_id,
                "score": 0,
                "reasoning": "No tool_use block in Anthropic response (unexpected)",
                "suggestions": [],
                "findings": [],
                "elapsed_seconds": elapsed,
            }

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(
                "Reviewer %s: FAILED after %.1fs — %s: %s",
                reviewer_id,
                elapsed,
                type(exc).__name__,
                exc,
            )
            return {
                "reviewer_id": reviewer_id,
                "score": 0,
                "passed": False,
                "reasoning": f"ANTHROPIC ERROR after {elapsed:.1f}s: {type(exc).__name__}: {str(exc)[:200]}",
                "suggestions": [],
                "findings": [],
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
