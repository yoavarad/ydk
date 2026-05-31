"""Playwright-based video recording for E2E flow verification.

Produces WebM videos of browser sessions for inclusion in proof artifacts.
Playwright is an optional dependency; importing this module when playwright
is not installed will raise ``ImportError`` at class instantiation time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class VideoCapture:
    """Record browser sessions as video using Playwright."""

    def record_session(
        self,
        url: str,
        actions: list[dict[str, object]],
        output_dir: Path,
    ) -> Path:
        """Open *url* in a browser, execute *actions*, and return the video path.

        Actions are dicts with a ``type`` key:
        - ``{"type": "click", "selector": "#btn"}``
        - ``{"type": "fill", "selector": "#email", "value": "a@b.com"}``
        - ``{"type": "wait", "ms": 1000}``
        - ``{"type": "screenshot", "name": "after-submit"}``

        Returns the path to the recorded ``.webm`` video.
        """
        from playwright.sync_api import sync_playwright  # optional dep

        output_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(record_video_dir=str(output_dir))
            page = context.new_page()
            page.goto(url)

            for action in actions:
                self._execute_action(page, action, output_dir)

            # Close context to flush video
            page.close()
            context.close()
            browser.close()

        # Playwright writes the video into output_dir
        videos = sorted(output_dir.glob("*.webm"))
        if not videos:
            msg = f"No video produced in {output_dir}"
            raise FileNotFoundError(msg)
        return videos[-1]

    def record_page(
        self,
        url: str,
        output_dir: Path,
        wait_ms: int = 3000,
    ) -> Path:
        """Simple page capture: navigate to *url*, wait, record video.

        A convenience wrapper around :meth:`record_session` with a single
        wait action.
        """
        actions: list[dict[str, object]] = [{"type": "wait", "ms": wait_ms}]
        return self.record_session(url, actions, output_dir)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_action(
        page: object,
        action: dict[str, object],
        output_dir: Path,
    ) -> None:
        """Dispatch a single action dict to the Playwright page."""
        action_type = action["type"]

        if action_type == "click":
            page.click(str(action["selector"]))  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        elif action_type == "fill":
            page.fill(str(action["selector"]), str(action["value"]))  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        elif action_type == "wait":
            ms = action.get("ms", 1000)
            page.wait_for_timeout(int(str(ms)))  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        elif action_type == "screenshot":
            name = str(action.get("name", "screenshot"))
            ss_dir = output_dir / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ss_dir / f"{name}.png"))  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        else:
            msg = f"Unknown action type: {action_type}"
            raise ValueError(msg)
