# go-http-service

This ignition pack generates a stdlib-first Go `net/http` service from YDK component manifests. It uses no web framework. The only third-party module is franz-go, and it is used only when a `ydk:ext:kafka/*` component exists.

## Generated layout

| Path | Source manifests | Contents |
|---|---|---|
| `go.mod` | `ydk:config` title, or the `go_module` / `app_name` init answers | Module, Go 1.22 (method-aware `ServeMux`) |
| `cmd/<app>/main.go` | `ydk:contract`, `ydk:nfr` (id contains `shutdown`) | Config load, slog JSON logger (`LOG_LEVEL`), `http.Server` on `:8080` (or the `http_port` init answer), graceful shutdown on SIGTERM/SIGINT |
| `internal/config/config.go` | `ydk:crosscut` with an `Env var` markdown table | Typed `Config`, `Load()`; required vars fail with `ErrInvalidConfig` |
| `internal/httpapi/` | `ydk:route`, `ydk:error`, `ydk:crosscut` error-format, `ydk:page` | `ServeMux` routes (one handler per route), `writeError` JSON helper, message constants, panic recovery (JSON 500), JSON 404/405 wrapper, `/healthz`, `/readyz` |
| `internal/<ns>/` | `ydk:entity`, `ydk:contract`, `ydk:error` | Structs, interfaces, `New<Contract>()` TODO stubs, sentinel errors, `Fake<Contract>` for ext-backed contracts |
| `internal/adapters/kafka/` | `ydk:ext:kafka/*` | franz-go client constructor, a type per ext-backed contract implementing it, and a `Consumer` when an ext endpoint reads (GET) |
| `web/` | `ydk:page` | `<name>.html` per page, embedded through `go:embed` and served by the page route |

## Conventions

- **TODOs:** every unimplemented handler, stub method and adapter method has the body `panic("not implemented") // <component id>: <description>`. Ignition registers each of these lines as a YDK TODO. The panic recovery middleware turns a TODO panic into a JSON 500, so the app still builds and serves `/healthz`.
- **Ext technology:** the technology comes from the ext id namespace, so `ydk:ext:kafka/cluster` maps to `kafka`. A contract is ext-backed when its description names the technology. Only `kafka` has an adapter template. Other technologies are skipped.
- **Health:** `/healthz` and `/readyz` are always registered, and they are added when no route declares them. `/readyz` returns 503 once shutdown starts.
- **Post-generation:** ignition runs `go get` (franz-go), `go mod tidy`, `go mod vendor`, `gofmt -w`, `go build ./...` and `go vet ./...`.

## Publish gate

`checks/smoke.py` ignites `samples/components` into a temp dir, builds and starts the binary with the required env vars set, and expects `GET /healthz` to return 200 and an unknown path to return a JSON 404. It needs `go` on PATH and network access for franz-go.
