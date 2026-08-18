"""Cached fan-out reviewer engine using direct boto3 Converse API.

Replaces the Strands-based reviewer path with direct ``boto3.converse()``
calls that share a cached system prefix across all reviewers.  The first
reviewer call primes the cache; subsequent calls fan out in parallel and
hit the cached prefix, cutting per-reviewer latency from ~10s to ~2-4s.

Uses Bedrock tool-use with forced ``toolChoice`` to guarantee structured
JSON output — no fragile text-parsing needed.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger("ydk.reviewer_engine")

# Tool schema that forces the model to return structured JSON.
REVIEW_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": "submit_review",
        "description": "Submit the structured review evaluation result",
        "inputSchema": {
            "json": {
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
            }
        },
    }
}


class ReviewerEngine:
    """Runs spec reviewers using Bedrock Converse API with prompt caching."""

    def __init__(self, aws_profile: str | None = None, region: str = "us-east-1"):
        boto_config = BotoConfig(
            read_timeout=300,
            connect_timeout=10,
            retries={"max_attempts": 2, "mode": "adaptive"},
        )
        session = boto3.Session(
            profile_name=aws_profile or None,
            region_name=region,
        )
        self._client = session.client("bedrock-runtime", config=boto_config)

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_blocks(self, spec_content: str) -> list[dict[str, Any]]:
        """Build system prompt with spec content and cache point."""
        return [
            {
                "text": (
                    "You are a specification quality evaluator. "
                    "For each criterion, evaluate the document and call the submit_review tool with: "
                    "score (0-10), reasoning (string), suggestions (list of strings), "
                    "findings (list of objects with line, text, issue keys)."
                ),
            },
            {
                "text": f"Here are the specification documents to evaluate:\n\n{spec_content}",
            },
            {"cachePoint": {"type": "default"}},
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
        """Single Bedrock Converse call for one reviewer."""
        start = time.monotonic()
        logger.info("Reviewer %s: calling Bedrock (%s)", reviewer_id, model_id)

        try:
            response = self._client.converse(
                modelId=model_id,
                system=system_blocks,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": reviewer_prompt}],
                    },
                ],
                toolConfig={
                    "tools": [REVIEW_TOOL_SPEC],
                    "toolChoice": {"tool": {"name": "submit_review"}},
                },
                inferenceConfig={"maxTokens": 8192, "temperature": 0.0},
            )

            elapsed = time.monotonic() - start

            # Log cache metrics
            usage = response.get("usage", {})
            cache_read = usage.get("cacheReadInputTokens", 0)
            cache_write = usage.get("cacheWriteInputTokens", 0)
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            logger.info(
                "Reviewer %s: done in %.1fs — input=%d, output=%d, cache_read=%d, cache_write=%d",
                reviewer_id,
                elapsed,
                input_tokens,
                output_tokens,
                cache_read,
                cache_write,
            )

            # Extract structured data from toolUse block
            content = response.get("output", {}).get("message", {}).get("content", [])
            for block in content:
                if "toolUse" in block:
                    data = block["toolUse"]["input"]
                    return {
                        "reviewer_id": reviewer_id,
                        "score": int(data.get("score", 0)),
                        "reasoning": str(data.get("reasoning", "")),
                        "suggestions": [str(s) for s in data.get("suggestions", [])],
                        "findings": data.get("findings", []),
                        "elapsed_seconds": elapsed,
                    }

            # No toolUse block found — should not happen with forced toolChoice
            logger.warning("Reviewer %s: no toolUse block in response", reviewer_id)
            return {
                "reviewer_id": reviewer_id,
                "score": 0,
                "reasoning": "No toolUse block in Bedrock response (unexpected)",
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
                "reasoning": f"BEDROCK ERROR after {elapsed:.1f}s: {type(exc).__name__}: {str(exc)[:200]}",
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
            model_tiers: Map of tier name to Bedrock model ID
                (e.g. ``{"smart": "us.anthropic.claude-sonnet-4-6-v1:0"}``).
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
