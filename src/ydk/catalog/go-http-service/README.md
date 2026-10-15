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
- **Validation:** the generator fails ignition, naming the components involved, when:
  - two manifests would generate the same Go identifier in one package, struct, interface, `httpapi.Deps` or the `Config` struct
  - a route path is not a valid ServeMux pattern
  - two routes conflict under Go 1.22 ServeMux rules: a duplicate, or an overlap where neither is more specific (`GET` also covers `HEAD`)
- **Env tables:** every `Env var` table in every `ydk:crosscut` is read. A variable listed more than once keeps its first definition, in crosscut id order.
- **Re-ignite:** unchanged generator output is not rewritten, even after `gofmt` reformatted it on disk. TODOs are registered once per file and line.
- **Post-generation:** ignition runs `go get` (franz-go), `go mod tidy`, `go mod vendor`, `gofmt -w`, `go build ./...` and `go vet ./...`.

## Env phase (Makefile and scripts)

The `env` generator writes a `Makefile` whose targets each run `scripts/<target>.sh` (POSIX `sh`, `set -eu`): `lint`, `test`, `test-integration`, `build`, `scan`, `e2e`, `publish`, `deploy`, `smoke`, `env-up`, `env-down` (`make` alone prints them). `scripts/env.sh` holds overridable defaults (`APP`, `CLUSTER`, `NAMESPACE`, `HOST_PORT`, `IMAGE_REPO`, `VERSION`, `IMAGE`, `CHART_DIR`, plus `KAFKA_CLUSTER` and `STRIMZI_VERSION` with Kafka).

- The `ydk:crosscut` whose id ends in `local-environment` drives the kind cluster name and port mapping (`deploy/local/kind-config.yaml`) and the Helm releases (`Release <name>: ... ingress host <host>`) in `deploy.sh`/`smoke.sh`. Without it there is one release named after the app, host `<app>.local`.
- Per-release `--set` values from the env-var table (instance name, Kafka settings) are set only when its `Helm value` column names their key.
- Only with a `ydk:ext:kafka/*` component: `deploy/local/kafka.yaml`, `kafka-topics.yaml` and `kafka-users.yaml` (Strimzi `kafka.strimzi.io/v1`, from the crosscut's Strimzi/KafkaTopic/KafkaUser lines), the Strimzi install and SCRAM credential Secrets in `env-up`, and the Kafka values in `deploy.sh`.
- `make smoke` waits for the readiness route (GET path ending in `readyz`, default `/readyz`) on every release, then runs any `test/smoke/*.sh` (app-specific round trips go there). `test/e2e/lib.sh` has `http_get`, `http_post_json`, `http_status`, `poll_until`, `fail` and one `HOST_<RELEASE>` variable per release.
- Each `ydk:test` with `level: e2e` becomes `test/e2e/<name>.sh`: one failing function per case, marked `# ydk:test:<id> case=<name>`, using the curl helpers in `test/e2e/lib.sh`.
- `make lint`, `make test` and `make build` need only Go. Cluster targets need kind, docker, kubectl, helm and curl.

## Publish gate

`checks/smoke.py` ignites `samples/components` into a temp dir, builds and starts the binary with the required env vars set, and expects `GET /healthz` to return 200 and an unknown path to return a JSON 404. It needs `go` on PATH and network access for franz-go.
