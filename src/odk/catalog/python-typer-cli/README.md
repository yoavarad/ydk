# python-typer-cli

ODK ignition pack for generating a Python CLI tool backed by a REST API. The generated project uses Typer for command parsing, httpx for HTTP communication, Rich for output formatting, and pytest with respx for testing.

## Overview

This pack generates a complete, working CLI application that wraps a REST API. Given a contract component describing command groups, endpoints, arguments, and options, it produces:

- A Typer-based CLI with command groups and subcommands
- An httpx HTTP client with configurable auth, timeouts, and typed error handling
- A test suite using `typer.testing.CliRunner` and `respx` for HTTP mocking
- A `pyproject.toml` with all dependencies and tool configuration

The generated CLI follows a strict layered architecture where commands never construct URLs or manage HTTP details directly -- all HTTP concerns are encapsulated in the client layer.

## Inputs

| Component Type | Required | Description |
|---|---|---|
| contract | yes | CLI command definitions: groups, commands, endpoints, arguments, options, response types |
| entity | no | Domain entity definitions (used for richer output formatting when present) |

Components are declared in `catalog.yaml` and resolved at ignition time via `odk ignite`.

## Architecture

The generated project follows a 3-layer architecture with strict import boundaries.

### Layer 1: CLI Layer (`src/commands/`, `src/main.py`)

Each command group is a separate Typer app in `src/commands/{group}.py`. The main entry point (`src/main.py`) registers all group apps:

```python
app = typer.Typer(
    name="myapp",
    help="myapp command-line interface",
    no_args_is_help=True,
)

app.add_typer(users_app, name="users", help="Manage users")
app.add_typer(projects_app, name="projects", help="Manage projects")
```

Each command file follows the same structure:

- A module-level `app = typer.Typer(no_args_is_help=True)` for the group
- A `_get_client()` helper that creates an `ApiClient` instance
- A `_output(data, pretty)` helper that serializes data to JSON
- One `@app.command()` function per CLI command

Commands handle argument parsing, output formatting, and error display. They delegate all HTTP work to the client layer:

```python
@app.command("list")
def list_users(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print output"),
    output_json: bool = typer.Option(True, "--json/--no-json", help="Output as JSON"),
) -> None:
    """List all users."""
    from ..client.http_client import ApiError

    client = _get_client()
    try:
        params = {}
        if status is not None:
            params["status"] = status
        result = client.request("GET", "/users", params=params or None)
        _output(result, pretty=pretty)
    except ApiError as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=1)
    finally:
        client.close()
```

### Layer 2: HTTP Client Layer (`src/client/`)

The client layer contains two files:

**`http_client.py`** -- httpx-based client with configurable base URL, timeouts, and retry:

```python
class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url or os.environ.get("MYAPP_BASE_URL", "http://localhost:8000")
        self.timeout = timeout

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialize the httpx client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                event_hooks={"request": [apply_auth]},
            )
        return self._client

    def request(self, method, path, *, params=None, json_body=None) -> Any:
        response = self.client.request(method, path, params=params, json=json_body)
        return self._handle_response(response)
```

**`auth.py`** -- Authentication applied via httpx event hooks. The auth strategy is selected at ignition time via the `auth_strategy` variable (`api_key`, `oauth_token`, or `none`):

```python
# api_key strategy
def apply_auth(request: httpx.Request) -> httpx.Request:
    api_key = os.environ.get("MYAPP_API_KEY", "")
    if api_key:
        request.headers["X-API-Key"] = api_key
    return request

# oauth_token strategy
def apply_auth(request: httpx.Request) -> httpx.Request:
    token = os.environ.get("MYAPP_AUTH_TOKEN", "")
    if token:
        request.headers["Authorization"] = f"Bearer {token}"
    return request

# none strategy
def apply_auth(request: httpx.Request) -> httpx.Request:
    return request
```

### Layer 3: Configuration

All configuration is loaded from environment variables. No config files, no CLI flags for base URLs or tokens. The variable names are derived from the `app_name` and `base_url_env` fields in the contract component:

| Variable | Purpose | Default |
|---|---|---|
| `{APP_NAME}_BASE_URL` | REST API base URL | `http://localhost:8000` |
| `{APP_NAME}_API_KEY` | API key (when `auth_strategy=api_key`) | empty |
| `{APP_NAME}_AUTH_TOKEN` | OAuth bearer token (when `auth_strategy=oauth_token`) | empty |
| `{APP_NAME}_TIMEOUT` | Request timeout in seconds | `30.0` |

## Output Strategy

All commands produce JSON to stdout by default. Two output flags are available on every generated command:

- `--json` (default, on): raw JSON output -- one JSON document per invocation, suitable for piping to `jq` or other tools
- `--pretty`: human-readable indented JSON output via `json.dumps(data, indent=2)`
- `--no-json`: disable JSON output

Output goes to stdout. Errors and progress messages go to stderr via `typer.echo(..., err=True)`. This separation ensures CLI output is always machine-parseable even when errors occur.

For commands with `response_type: empty` (e.g., DELETE operations returning 204), the command prints `Done.` to stdout instead of JSON.

## Error Handling

The HTTP client defines a typed exception hierarchy in `src/client/http_client.py`:

```python
class ApiError(Exception):
    """Base API error."""
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message

class NotFoundError(ApiError):
    """Resource not found (404)."""

class AuthError(ApiError):
    """Authentication or authorization failure (401/403)."""

class ServerError(ApiError):
    """Server-side error (5xx)."""
```

The `_handle_response` method in `ApiClient` maps HTTP status codes to these exceptions:

| Status Code | Exception | Default Message |
|---|---|---|
| 404 | `NotFoundError` | `"Resource not found"` |
| 401, 403 | `AuthError` | `"Authentication failed"` |
| 5xx | `ServerError` | `"Server error"` |
| other 4xx | `ApiError` | response body text |

Every generated command catches `ApiError` at the top level, prints a user-friendly message to stderr, and exits with code 1:

```python
except ApiError as e:
    typer.echo(f"Error: {e.message}", err=True)
    raise typer.Exit(code=1)
finally:
    client.close()
```

## Import Rules

The generated project enforces strict layer boundaries:

- `src/commands/` imports from `src/client/` only
- `src/client/` has no imports from `src/commands/`
- `tests/` imports from both layers (commands via the Typer app, client for error types)

These boundaries are enforced by the `hexagonal-architecture` and `python-quality` verification sets.

## Generators

| Generator ID | Purpose | Output Files |
|---|---|---|
| `resolve-commands` | Resolve CLI commands from contract + optional OpenAPI spec into full cli-commands structure | `.odk/resolved/cli-commands.yaml` |
| `cli-client` | httpx-based HTTP client with auth and typed error handling | `src/client/http_client.py`, `src/client/auth.py`, `src/client/__init__.py` |
| `cli-main` | Main Typer app entry point with group registration | `src/main.py` |
| `cli-commands` | Command group files, one per group | `src/commands/{group}.py` per group |
| `cli-tests` | Test files using CliRunner and respx | `tests/conftest.py`, `tests/test_{group}.py` per group |
| `cli-pyproject` | Project configuration with all dependencies | `pyproject.toml` |

Generator execution order is defined in `manifest.yaml`. The `resolve-commands` generator runs first when an OpenAPI spec is available, producing a resolved cli-commands file that downstream generators consume. If no OpenAPI spec is present, the contract component is used directly.

All generators follow the ODK protocol: read input from `ODK_COMPONENTS_*` environment variables, emit a JSON array of `{"path": "...", "content": "..."}` objects to stdout.

## Testing

### Tools

- **pytest** -- test runner
- **typer.testing.CliRunner** -- invokes CLI commands in-process without subprocess overhead
- **respx** -- native httpx mock library, intercepts HTTP requests at the transport level

### Test Structure

```
tests/
  conftest.py          # Shared fixtures: runner, cli_app
  test_{group}.py      # One file per command group
```

`conftest.py` provides shared fixtures:

```python
import pytest
from typer.testing import CliRunner
from src.main import app

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def cli_app():
    return app
```

### Test Pattern

Each command gets at minimum two tests: a happy-path test and a 404 error-handling test. Here is the full pattern for a command:

```python
import respx
from httpx import Response
from typer.testing import CliRunner
from src.main import app

runner = CliRunner()
BASE_URL = "http://localhost:8000"


@respx.mock
def test_users_list_success():
    """Test users list -- happy path."""
    respx.get(f"{BASE_URL}/users").mock(
        return_value=Response(200, json=[{"id": "1"}])
    )
    result = runner.invoke(app, ["users", "list"])
    assert result.exit_code == 0


@respx.mock
def test_users_list_not_found():
    """Test users list -- 404 error handling."""
    respx.get(f"{BASE_URL}/users").mock(
        return_value=Response(404, text="Not found")
    )
    result = runner.invoke(app, ["users", "list"])
    assert result.exit_code == 1


@respx.mock
def test_users_get_success():
    """Test users get -- happy path with path argument."""
    respx.get(f"{BASE_URL}/users/test-id").mock(
        return_value=Response(200, json={"id": "test-id"})
    )
    result = runner.invoke(app, ["users", "get", "test-id"])
    assert result.exit_code == 0


@respx.mock
def test_users_get_not_found():
    """Test users get -- 404 error handling."""
    respx.get(f"{BASE_URL}/users/missing-id").mock(
        return_value=Response(404, text="Not found")
    )
    result = runner.invoke(app, ["users", "get", "missing-id"])
    assert result.exit_code == 1
```

### What Tests Verify

- **Happy path**: correct exit code (0), command produces output
- **Error handling (404)**: `NotFoundError` is caught, exit code is 1
- **Error handling (401/403)**: `AuthError` is caught, exit code is 1
- **Error handling (5xx)**: `ServerError` is caught, exit code is 1
- **Arguments**: path parameters are passed correctly to the endpoint
- **Options**: query parameters and request body fields are forwarded
- **Output format**: JSON is written to stdout, errors to stderr

### Running Tests

```bash
# Run all tests
pytest

# Run tests for a specific command group
pytest tests/test_users.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src
```

### Coverage Target

100% of generated command functions have at least one test. Every command gets a happy-path test and a 404 error-handling test by default. Additional auth (401) and server error (5xx) tests should be added for commands where those failure modes are expected.

## Verification Sets

- **python-quality** (>= 1.0.0) -- ruff format, ruff lint, import ordering
- **odk-default-reviewers** (>= 1.0.0) -- spec review gates

## Manifest Variables

| Variable | Prompt | Type | Choices | Default |
|---|---|---|---|---|
| `auth_strategy` | Authentication strategy for the REST API? | choice | `api_key`, `oauth_token`, `none` | `none` |
