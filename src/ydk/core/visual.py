"""Visual companion engine — manages Vite sessions for browser-based design annotation."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from ydk.models.visual import (
    ElementAnnotationEvent,
    RectangleAnnotationEvent,
    SelectionEvent,
    SessionStatus,
    VisualSession,
)

if TYPE_CHECKING:
    from ydk.models.visual import FeedbackEvent

_OVERLAY_DIR = Path(__file__).resolve().parent.parent / "visual" / "overlay"


def _find_free_port() -> int:
    """Find a free TCP port by binding to port 0."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _sessions_root(project_dir: Path) -> Path:
    """Root directory for all visual sessions under a project."""
    return project_dir / ".ydk" / "visual"


def _session_dir(project_dir: Path, session_id: str) -> Path:
    """Directory for a specific session."""
    return _sessions_root(project_dir) / session_id


_EVENT_PARSERS: dict[str, type[SelectionEvent | ElementAnnotationEvent | RectangleAnnotationEvent]] = {
    "selection": SelectionEvent,
    "element_annotation": ElementAnnotationEvent,
    "rectangle_annotation": RectangleAnnotationEvent,
}

_PACKAGE_JSON_TEMPLATE = """{
  "private": true,
  "type": "module",
  "devDependencies": {
    "vite": "^6"
  },
  "scripts": {
    "dev": "vite"
  }
}
"""


def _vite_config_template(content_dir: str, state_dir: str, port: int) -> str:
    """Generate vite.config.ts content with annotation overlay injection."""
    overlay_js = (_OVERLAY_DIR / "annotation-overlay.js").read_text()
    overlay_css = (_OVERLAY_DIR / "annotation-styles.css").read_text()
    wireframe_css = (_OVERLAY_DIR / "wireframe.css").read_text()

    escaped_js = json.dumps(overlay_js)
    escaped_css = json.dumps(overlay_css)
    escaped_wireframe = json.dumps(wireframe_css)
    escaped_state = json.dumps(state_dir)

    return f"""import {{ defineConfig }} from "vite";
import fs from "node:fs";
import path from "node:path";

const STATE_DIR = {escaped_state};
const OVERLAY_JS = {escaped_js};
const OVERLAY_CSS = {escaped_css};
const WIREFRAME_CSS = {escaped_wireframe};

export default defineConfig({{
  root: "{content_dir}",
  server: {{
    port: {port},
    strictPort: true,
    open: false,
  }},
  plugins: [
    {{
      name: "ydk-visual-overlay",
      transformIndexHtml(html) {{
        return html +
          `<style>${{WIREFRAME_CSS}}</style>` +
          `<style>${{OVERLAY_CSS}}</style>` +
          `<script>${{OVERLAY_JS}}</script>`;
      }},
      configureServer(server) {{
        server.middlewares.use("/api/feedback", (req, res) => {{
          if (req.method === "POST") {{
            let body = "";
            req.on("data", (chunk) => {{ body += chunk; }});
            req.on("end", () => {{
              const feedbackPath = path.join(STATE_DIR, "feedback.jsonl");
              fs.appendFileSync(feedbackPath, body.trim() + "\\n");
              res.writeHead(200, {{ "Content-Type": "application/json" }});
              res.end(JSON.stringify({{ ok: true }}));
            }});
          }} else {{
            res.writeHead(405);
            res.end("Method Not Allowed");
          }}
        }});
      }},
    }},
  ],
}});
"""


def _default_index_html() -> str:
    """Default index.html placeholder for new sessions."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YDK Visual Companion</title>
</head>
<body>
  <div class="mock-content" style="padding: 2rem; text-align: center;">
    <h1>YDK Visual Companion</h1>
    <p>Push content with <code>ydk visual push</code> to begin.</p>
  </div>
</body>
</html>
"""


class VisualEngine:
    """Manages visual companion sessions backed by Vite dev servers."""

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = (project_dir or Path.cwd()).resolve()

    def start_session(self) -> VisualSession:
        """Create a session directory, write server files, and start the Vite subprocess."""
        session_id = uuid.uuid4().hex[:12]
        base = _session_dir(self._project_dir, session_id)
        content_dir = base / "content"
        state_dir = base / "state"
        content_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        (base / "screenshots").mkdir(parents=True, exist_ok=True)

        port = _find_free_port()

        content_str = str(content_dir)
        state_str = str(state_dir)

        (base / "package.json").write_text(_PACKAGE_JSON_TEMPLATE)
        (base / "vite.config.ts").write_text(_vite_config_template(content_str, state_str, port))
        (content_dir / "index.html").write_text(_default_index_html())

        proc = subprocess.Popen(
            ["npx", "vite", "--config", str(base / "vite.config.ts")],
            cwd=str(base),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        session = VisualSession(
            id=session_id,
            port=port,
            url=f"http://localhost:{port}",
            content_dir=content_str,
            state_dir=state_str,
            pid=proc.pid,
            status=SessionStatus.running,
        )

        server_info = session.model_dump()
        (state_dir / "server-info.json").write_text(json.dumps(server_info, indent=2))

        return session

    def stop_session(self, session_id: str) -> None:
        """Kill the Vite process and write a sentinel file."""
        session = self.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        if session.pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.name != "nt":
                    os.killpg(os.getpgid(session.pid), signal.SIGTERM)
                else:
                    os.kill(session.pid, signal.SIGTERM)

        state_dir = Path(session.state_dir)
        (state_dir / "server-stopped").touch()

        server_info_path = state_dir / "server-info.json"
        if server_info_path.exists():
            data = json.loads(server_info_path.read_text())
            data["status"] = SessionStatus.stopped.value
            server_info_path.write_text(json.dumps(data, indent=2))

    def push_content(self, session_id: str, content: str, filename: str = "index.html") -> Path:
        """Write a content file to the session's content directory."""
        session = self.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        content_path = Path(session.content_dir) / filename
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text(content)
        return content_path

    def read_feedback(self, session_id: str) -> list[FeedbackEvent]:
        """Read and parse all feedback events from feedback.jsonl."""
        session = self.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        if not feedback_path.exists():
            return []

        events: list[FeedbackEvent] = []
        for line in feedback_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type")
            parser = _EVENT_PARSERS.get(event_type) if isinstance(event_type, str) else None
            if parser is None:
                continue
            try:
                events.append(parser.model_validate(data))
            except Exception:
                continue

        return events

    def clear_feedback(self, session_id: str) -> None:
        """Clear the feedback file for a session."""
        session = self.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        if feedback_path.exists():
            feedback_path.write_text("")

    def get_session(self, session_id: str) -> VisualSession | None:
        """Read session state from disk."""
        state_file = _session_dir(self._project_dir, session_id) / "state" / "server-info.json"
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text())
            return VisualSession.model_validate(data)
        except (json.JSONDecodeError, Exception):
            return None

    def list_sessions(self) -> list[VisualSession]:
        """List all sessions (active and stopped)."""
        root = _sessions_root(self._project_dir)
        if not root.is_dir():
            return []

        sessions: list[VisualSession] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            session = self.get_session(child.name)
            if session is not None:
                sessions.append(session)
        return sessions

    def capture_screenshot(self, session_id: str, url: str, output: Path) -> Path:
        """Capture a screenshot using playwright CLI."""
        session = self.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["python", "-m", "playwright", "screenshot", "--wait-for-timeout", "2000", url, str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        return output
