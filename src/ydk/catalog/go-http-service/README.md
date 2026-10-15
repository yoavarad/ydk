# go-http-service

This ignition pack generates a stdlib-first Go `net/http` service from YDK component manifests. It uses no web framework. The only third-party module is franz-go, and it is used only when a `ydk:ext:kafka/*` component exists.

## Generated layout

| Path | Source manifests | Contents |
|---|---|---|
| `go.mod` | `ydk:config` title, or the `go_module` / `app_name` init answers | Module, Go 1.22 (method-aware `ServeMux`) |
| `cmd/<app>/main.go` | `ydk:contract`, `ydk:nfr` (id contains `shutdown`) | Config load, slog JSON logger (`LOG_LEVEL`), `http.Server` on port 8080 (or the `http_port` init answer), bound to `LISTEN_HOST` (default: all interfaces), graceful shutdown on SIGTERM/SIGINT |
| `internal/config/config.go` | `ydk:crosscut` with an `Env var` markdown table | Typed `Config`, `Load()`; required vars fail with `ErrInvalidConfig` |
| `internal/httpapi/` | `ydk:route`, `ydk:error`, `ydk:crosscut` error-format, `ydk:page` | `ServeMux` routes (one handler per route), `writeError` JSON helper, message constants, panic recovery (JSON 500), JSON 404/405 wrapper, `/healthz`, `/readyz` |
| `internal/<ns>/` | `ydk:entity`, `ydk:contract`, `ydk:error` | Structs, interfaces, `New<Contract>()` TODO stubs, sentinel errors, `Fake<Contract>` for ext-backed contracts |
| `internal/adapters/kafka/` | `ydk:ext:kafka/*` | franz-go client constructor, a type per ext-backed contract implementing it, and a `Consumer` when an ext endpoint reads (GET) |
| `web/` | `ydk:page` | `<name>.html` per page, embedded through `go:embed` and served by the page route |
| `Dockerfile`, `.dockerignore` | phase `ops`; `ydk:config` title | Multi-stage build: `golang` builder, `CGO_ENABLED=0`, `-mod=vendor`, `GOPROXY=off`, `RUN --network=none`, `-ldflags "-X main.version=${VERSION}"`; runtime from the `runtime_image` init answer (default `scratch` plus CA roots), builder from `builder_image` (default `golang:1`), `USER 1001`, group-0 ownership |
| `charts/<app>/` | phase `ops`; `ydk:crosscut` env table (`Helm value` column), `ydk:nfr` cpu/memory/shutdown, `ydk:req` single-replica | Helm chart v2: `values.schema.json` closed at every level (`additionalProperties: false`), Deployment, Service, optional Route (`openshift.enabled=true`) or Ingress (`ingress.enabled`), optional NetworkPolicy |

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

## Ops phase

The manifest's `ops` phase runs `generators/ops.py` after the top-level generators.

- **Values:** each `Env var` row with a `Helm value` maps to the Deployment env:
  - a dotted path (`kafka.bootstrapServers`) becomes a string value. A required value, or one with a literal default, is always set. An optional value without a literal default is `null`, and the env var is left unset so the app default applies.
  - `<base>.existingSecret + <key>` becomes a `secretKeyRef` from an existing Secret. There is no value field for the secret itself.
  - `<base>.existingSecret or <base>.configMap + <key>` becomes a read-only volume. The env var holds the file path. The mount path comes from an absolute path in the row's rule, otherwise `/etc/<app>/<name>`.
  - `(fixed ...)` sets the table default directly in the Deployment.
- **Pod security:** compatible with SCC restricted-v2. `runAsNonRoot`, `seccompProfile: RuntimeDefault`, no `runAsUser` or `fsGroup`, all capabilities dropped, `readOnlyRootFilesystem: true`, no service account token.
- **Replicas:** a `ydk:req` whose id contains `single-replica` fixes `replicas: 1` with strategy `Recreate`. Otherwise the chart uses `replicaCount` with `RollingUpdate`.
- **Resources and grace period:** requests and limits come from `ydk:nfr` targets whose id names cpu or memory (`request 50m, limit 500m`). The grace period comes from the shutdown nfr (`terminationGracePeriodSeconds N`), otherwise it is the shutdown timeout plus 5 s.
- **Exposure:** nothing is exposed by default. With `ingress.enabled=true`, the chart renders a Route with edge TLS when `openshift.enabled=true`, and an Ingress otherwise.
- **NetworkPolicy:** rendered when `networkPolicy.enabled` is true. It defaults to true when a `ydk:req` or `ydk:crosscut` mentions NetworkPolicy. It has one ingress rule on the HTTP port, from the namespaces matched by `networkPolicy.ingressNamespaceSelector`. An empty selector matches every namespace.
- **Images:** the `builder_image` and `runtime_image` init answers set the Dockerfile defaults, for example a UBI 9 micro runtime. Without them the defaults are `golang:1` and `scratch`, and the CA roots are copied from the builder. `--build-arg BUILDER_IMAGE=… RUNTIME_IMAGE=…` overrides them at build time.
- **Generic:** the app name, port, resources, replicas and env come from manifests or init answers. Nothing in the ops phase is specific to the sample project. Resources default to 100m/128Mi requests and 500m/256Mi limits.

## Publish gate

`checks/smoke.py` ignites `samples/components` into a temp dir, builds and starts the binary with the required env vars set, and expects `GET /healthz` to return 200 and an unknown path to return a JSON 404. It needs `go` on PATH and network access for franz-go. When `helm` is on PATH, it also runs `helm lint --strict` and `helm template` with `openshift.enabled` set to true and to false, and checks that an unknown values key fails lint.
