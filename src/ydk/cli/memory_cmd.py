"""ydk memory — knowledge management and memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from ydk.cli._helpers import format_or_echo
from ydk.output.console import console

if TYPE_CHECKING:
    from ydk.models.config import YdkConfig

memory_app = typer.Typer(name="memory", help="Knowledge management and memory")


def _load_memory_config() -> YdkConfig:
    """Load config and return the full YdkConfig."""
    from ydk.core.config import load_config

    return load_config()


def _get_engine(cfg: YdkConfig) -> object:  # type: ignore[return-type]  # MemoryEngine is optional dep
    """Lazily import and construct MemoryEngine. Fails gracefully if chromadb missing."""
    try:
        from ydk.core.memory import MemoryEngine  # type: ignore[import-untyped]
    except ImportError:
        console.print("[red]chromadb is not installed.[/red] Install with: uv pip install 'ydk[memory]'")
        raise typer.Exit(code=1) from None

    return MemoryEngine(
        chroma_path=cfg.memory.chroma_path,
        embedding_model=cfg.memory.embedding_model,
    )


def _get_extractor(cfg: YdkConfig | None = None) -> object:  # type: ignore[return-type]  # MemoryExtractor is optional dep
    """Lazily import MemoryExtractor. Fails gracefully if strands missing."""
    try:
        from ydk.core.extractor import MemoryExtractor  # type: ignore[import-untyped]
    except ImportError:
        console.print("[red]strands-agents is not installed.[/red] Install with: uv pip install 'ydk[ai]'")
        raise typer.Exit(code=1) from None

    return MemoryExtractor()


@memory_app.command()
def index() -> None:
    """Build/rebuild ChromaDB index from project knowledge files."""
    cfg = _load_memory_config()
    engine = _get_engine(cfg)
    result = engine.index_all(cfg)  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep
    console.print(f"[green]Indexed {result['files']} files[/green]")
    console.print(f"  Chunks created: {result.get('chunks', 0)}")
    console.print(f"  Skipped: {result.get('skipped', 0)}")


@memory_app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
    verified_only: bool = typer.Option(False, "--verified-only", help="Only show verified memories"),
) -> None:
    """Semantic search across all project knowledge."""
    cfg = _load_memory_config()
    engine = _get_engine(cfg)
    results = engine.search(query)  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep

    if verified_only:
        results = [r for r in results if r.get("verified") is True]

    if format_or_echo(ctx, results):
        return

    if not results:
        console.print("No results found.")
        return
    for i, hit in enumerate(results, 1):
        score = hit.get("score", 0.0)
        source = hit.get("source", "unknown")
        section = hit.get("section", "")
        snippet = hit.get("snippet", "")
        source_type = hit.get("source_type", "")
        verified = hit.get("verified", False)
        console.print(f"\n[bold]{i}.[/bold] {source}")
        if section:
            console.print(f"   Section: {section}")
        console.print(f"   Score: {score:.3f}")
        if source_type:
            verified_label = " [green]verified[/green]" if verified else ""
            console.print(f"   Source: {source_type}{verified_label}")
        console.print(f"   {snippet[:200]}")


@memory_app.command()
def bootstrap(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Assemble relevant memories for a task."""
    from ydk.repositories.factory import get_task_repository

    cfg = _load_memory_config()
    engine = _get_engine(cfg)
    repo = get_task_repository()
    task = repo.get_task(task_id)
    description = task.title
    if hasattr(task, "description") and task.description:
        description = task.description
    spec_refs: list[str] = []
    if hasattr(task, "spec_refs"):
        spec_refs = task.spec_refs or []
    context = engine.bootstrap(description, spec_refs)  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep
    console.print(f"[green]Bootstrap context for {task_id}: {len(context)} entries[/green]")
    for entry in context:
        console.print(
            f"  - [{entry.get('collection', 'memory')}] "
            f"{entry.get('source', 'unknown')}: {entry.get('snippet', '')[:100]}"
        )


@memory_app.command()
def extract(
    task_id: str = typer.Argument(..., help="Task ID"),
    jsonl: Path | None = typer.Option(None, "--jsonl", help="Path to Claude Code session JSONL"),  # noqa: B008
) -> None:
    """Extract learnings from a completed task's transcript."""
    cfg = _load_memory_config()
    engine = _get_engine(cfg)
    extractor = _get_extractor(cfg)

    # Determine JSONL path
    jsonl_path = jsonl
    if jsonl_path is None:
        # Try conventional location
        candidate = Path(f".ydk/sessions/{task_id}.jsonl")
        if candidate.is_file():
            jsonl_path = candidate
        else:
            console.print(f"[yellow]No session JSONL found for {task_id}.[/yellow] Use --jsonl to specify a path.")
            raise typer.Exit(code=1)

    memories = extractor.extract_from_jsonl(jsonl_path=jsonl_path, task_context=task_id)  # ty: ignore[unresolved-attribute]  # MemoryExtractor is optional dep
    if memories:
        # Store extracted memories in ChromaDB
        for m in memories:
            engine.add_extraction(  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep
                task_id=task_id,
                extraction_type=m.memory_type,
                content=m.content,
                related_files=m.related_files,
            )
        console.print(f"[green]Extracted {len(memories)} memories from {task_id}:[/green]")
        for m in memories:
            console.print(f"  - [{m.memory_type}] {m.content[:100]}")
    else:
        console.print(f"No learnings extracted from {task_id}.")


@memory_app.command()
def get(
    ctx: typer.Context,
    memory_id: str = typer.Argument(..., help="Memory ID to retrieve"),
) -> None:
    """Retrieve full details for a specific memory by ID."""
    cfg = _load_memory_config()
    engine = _get_engine(cfg)
    results = engine.get_memory_details([memory_id])  # ty: ignore[unresolved-attribute]
    if format_or_echo(ctx, results):
        return
    if not results:
        console.print(f"[yellow]No memory found with ID: {memory_id}[/yellow]")
        return
    for entry in results:
        console.print(f"\n[bold]ID:[/bold] {entry.get('id', '')}")
        console.print(f"[bold]Content:[/bold] {entry.get('content', '')}")


@memory_app.command("record-decision")
def record_decision(
    ctx: typer.Context,
    topic: str = typer.Argument(..., help="Decision topic"),
) -> None:
    """Show the current (latest) decision for a topic."""
    from ydk.core.decision_store import DecisionStore

    store = DecisionStore()
    current = store.get_current(topic)
    if format_or_echo(ctx, current.model_dump() if current else {}):
        return
    if not current:
        console.print(f"[yellow]No decision found for topic: {topic}[/yellow]")
        return
    console.print(f"\n[bold]Topic:[/bold] {current.topic}")
    console.print(f"[bold]Version:[/bold] v{current.version}")
    console.print(f"[bold]Content:[/bold] {current.content}")
    console.print(f"[bold]Rationale:[/bold] {current.rationale}")


@memory_app.command(name="decision-history")
def decision_history(
    ctx: typer.Context,
    topic: str = typer.Argument(..., help="Decision topic"),
) -> None:
    """Show all versions of a decision for a topic (newest first)."""
    from ydk.core.decision_store import DecisionStore

    store = DecisionStore()
    history = store.get_history(topic)
    if format_or_echo(ctx, [d.model_dump() for d in history]):
        return
    if not history:
        console.print(f"[yellow]No decision history for topic: {topic}[/yellow]")
        return
    for d in history:
        console.print(f"\n  v{d.version} -- {d.created_at}: {d.content}")


@memory_app.command()
def retrospective(
    sprint: str | None = typer.Option(None, help="Sprint/milestone to review"),
) -> None:
    """Sprint retrospective — aggregate learnings across tasks using LLM analysis."""
    from ydk.repositories.factory import get_task_repository

    repo = get_task_repository()
    tasks = repo.list_tasks(state="closed")

    if sprint:
        tasks = [t for t in tasks if getattr(t, "milestone", None) == sprint]

    if not tasks:
        console.print("No completed tasks found for retrospective.")
        return

    shipped = [t for t in tasks if getattr(t, "status", "") in ("done", "closed", "merged")]
    console.print(f"[bold]Sprint Retrospective[/bold]{f' -- {sprint}' if sprint else ''}")
    console.print(f"\n  Tasks completed: {len(shipped)}")
    console.print("\n  [bold]Shipped:[/bold]")
    for t in shipped:
        console.print(f"    - {t.id}: {t.title}")

    # Try LLM retrospective analysis
    proposals = _run_llm_retrospective(shipped, sprint)
    if proposals:
        console.print("\n  [bold]AI Analysis:[/bold]")
        for proposal in proposals.get("patterns", []):
            console.print(f"    Pattern: {proposal}")
        for template in proposals.get("templates", []):
            console.print(f"    Template suggestion: {template}")
        for rule in proposals.get("rules", []):
            console.print(f"    Rule suggestion: {rule}")

        # Save to proofs directory
        proofs_dir = Path(".ydk/proofs")
        proofs_dir.mkdir(parents=True, exist_ok=True)
        sprint_label = sprint or "current"
        output_path = proofs_dir / f"retrospective-{sprint_label}.json"
        output_path.write_text(json.dumps(proposals, indent=2))
        console.print(f"\n  [dim]Saved to {output_path}[/dim]")
    else:
        console.print("\n  [bold]Patterns & Learnings:[/bold]")
        console.print("    Run `ydk memory search <topic>` to find specific learnings.")
        console.print("    Review extracted memories in .ydk/memory/ for aggregate insights.")


def _run_llm_retrospective(
    tasks: list,  # type: ignore[type-arg]
    sprint: str | None,
) -> dict | None:
    """Run LLM analysis on sprint data. Returns structured proposals or None."""
    from ydk.core.config import load_config
    from ydk.core.llm_provider import get_llm_provider

    provider = get_llm_provider(load_config())
    if provider is None:
        return None

    system_prompt = (
        "You are a sprint retrospective analyst. "
        "Given completed task data, identify patterns, suggest templates, "
        "and recommend rules for future sprints.\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"patterns": ["..."], "templates": ["..."], "rules": ["..."], "summary": "..."}'
    )

    task_data = "\n".join(f"- {t.id}: {t.title}" for t in tasks)
    prompt = (
        f"{system_prompt}\n\n"
        f"Sprint: {sprint or 'current'}\n"
        f"Completed tasks:\n{task_data}\n\n"
        "Analyze this sprint data. What patterns emerged? "
        "What should be templated? What rules should be added?"
    )

    try:
        response_text = provider.invoke(prompt)
    except Exception:
        return None

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx < 0 or end_idx <= start_idx:
            return None
        try:
            parsed = json.loads(response_text[start_idx:end_idx])
        except json.JSONDecodeError:
            return None

    return parsed if isinstance(parsed, dict) else None


@memory_app.command()
def audit(
    prompt_id: str | None = typer.Option(None, "--prompt-id", help="Prompt ID to report on (procedural report)"),
) -> None:
    """Comprehensive memory health audit -- stale research, duplicates, and procedural reports."""
    import datetime

    cfg = _load_memory_config()
    research_dir = Path(cfg.project.research_location)

    stale: list[str] = []
    now = datetime.datetime.now(tz=datetime.UTC)
    expiry_days = 90

    if research_dir.is_dir():
        for f in sorted(research_dir.glob("**/*.md")):
            stat = f.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC)
            age = (now - mtime).days
            if age > expiry_days:
                stale.append(f"{f} (last modified {age} days ago)")

    console.print("[bold]Memory Audit[/bold]")

    if stale:
        console.print(f"\n  [yellow]Stale research ({len(stale)} files older than {expiry_days} days):[/yellow]")
        for entry in stale:
            console.print(f"    - {entry}")
    else:
        console.print("\n  [green]No stale research files found.[/green]")

    try:
        from ydk.core.memory_consolidation import MemoryConsolidator

        engine = _get_engine(cfg)
        store = _MemoryEngineAdapter(engine)
        consolidator = MemoryConsolidator(store=store)
        report = consolidator.audit()

        console.print(f"\n  Total memories: {report.total_memories}")
        console.print(f"  Duplicates: {report.duplicate_count}")
        console.print(f"  Stale (>90 days): {report.stale_count}")

        if report.groups:
            console.print(f"\n  [yellow]{len(report.groups)} duplicate group(s) found.[/yellow]")
            console.print("  Run `ydk memory consolidate` to merge them.")
    except Exception:
        console.print("\n  [dim]Memory health check skipped (chromadb not available).[/dim]")

    if prompt_id:
        try:
            from ydk.core.procedural_memory import ProceduralMemory

            proc = ProceduralMemory()
            proc_report = proc.get_report(prompt_id)

            console.print(f"\n  [bold]Procedural Report: {proc_report.prompt_id}[/bold]")
            console.print(f"  Total executions: {proc_report.total_executions}")
            console.print(f"  Successes: {proc_report.successes}")
            console.print(f"  Failures: {proc_report.failures}")
            console.print(f"  Effectiveness: {proc_report.effectiveness:.0%}")

            if proc_report.suggestion:
                console.print(f"\n  [yellow]Suggested improvement:[/yellow] {proc_report.suggestion}")
        except Exception:
            console.print(f"\n  [dim]Procedural report for {prompt_id} not available.[/dim]")


@memory_app.command()
def consolidate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be merged without merging"),
    threshold: float = typer.Option(0.9, "--threshold", help="Similarity threshold for duplicate detection"),
) -> None:
    """Find and merge duplicate memories."""
    from ydk.core.memory_consolidation import MemoryConsolidator

    cfg = _load_memory_config()
    engine = _get_engine(cfg)

    store = _MemoryEngineAdapter(engine)
    consolidator = MemoryConsolidator(store=store)

    groups = consolidator.find_duplicates(threshold=threshold)

    if not groups:
        console.print("[green]No duplicates found.[/green]")
        return

    console.print(f"[bold]Found {len(groups)} duplicate group(s):[/bold]")
    for g in groups:
        console.print(f"  Keep: {g.canonical_id}")
        for dup in g.duplicate_ids:
            console.print(f"    Remove: {dup} (similarity: {g.similarity:.2f})")

    if dry_run:
        console.print("\n[yellow]Dry run — no changes made.[/yellow]")
        return

    removed = consolidator.merge_duplicates(groups)
    console.print(f"\n[green]Merged {removed} duplicate(s).[/green]")


class _MemoryEngineAdapter:
    """Adapts MemoryEngine to the VectorStore protocol used by MemoryConsolidator."""

    def __init__(self, engine: object) -> None:
        self._engine = engine

    def get_all(self, collection: str) -> list[dict]:
        col = self._engine._get_collection(collection)  # ty: ignore[unresolved-attribute]
        result = col.get(include=["documents", "metadatas"])
        docs: list[dict] = []
        for i, doc_id in enumerate(result.get("ids", [])):
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            text = result["documents"][i] if result.get("documents") else ""
            docs.append({"id": doc_id, "text": text, "topic": meta.get("extraction_type", ""), **meta})
        return docs

    def query_similar(self, collection: str, document: str, n_results: int) -> list[dict]:
        col = self._engine._get_collection(collection)  # ty: ignore[unresolved-attribute]
        results = col.query(query_texts=[document], n_results=n_results)
        docs: list[dict] = []
        if results and results.get("ids"):
            for i, doc_id in enumerate(results["ids"][0]):
                dist = results["distances"][0][i] if results.get("distances") else 0
                docs.append({"id": doc_id, "similarity": 1 - dist})
        return docs

    def delete(self, collection: str, ids: list[str]) -> None:
        col = self._engine._get_collection(collection)  # ty: ignore[unresolved-attribute]
        col.delete(ids=ids)

    def update_metadata(self, collection: str, doc_id: str, metadata: dict) -> None:
        col = self._engine._get_collection(collection)  # ty: ignore[unresolved-attribute]
        existing = col.get(ids=[doc_id])
        if existing and existing.get("ids"):
            old_meta = existing["metadatas"][0] if existing.get("metadatas") else {}
            col.update(ids=[doc_id], metadatas=[{**old_meta, **metadata}])
