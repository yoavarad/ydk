# Changelog

## Unreleased

- Phase `ops`: multi-stage offline Dockerfile (vendor; builder/runtime images from init answers, default `golang:1` / `scratch`; non-root, group 0), `.dockerignore`, and a Helm chart with a closed values schema, optional Route/Ingress and NetworkPolicy, and restricted-v2 pod security.
- `main.go` binds `LISTEN_HOST` (default all interfaces); the smoke check binds 127.0.0.1. Version injected with `-ldflags -X main.version`. The smoke check runs helm lint/template when helm is installed.

## 0.1.0

- Initial pack: stdlib `net/http` skeleton (config, slog, graceful shutdown, JSON errors, health), domain packages, franz-go Kafka adapter, embedded pages, publish smoke check.
