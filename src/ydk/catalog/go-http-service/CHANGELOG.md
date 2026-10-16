# Changelog

## Unreleased

- Explicit ext binding: contracts bind to an ext with `ext_ref: ydk:ext:<ns>/<name>` (description matching is a deprecated fallback that warns); `main.go` wires the generated adapter per bound ext when its technology has a template (kafka: `Connect()` from `KAFKA_BOOTSTRAP_SERVERS`), else the stub. The error-format crosscut and shutdown nfr are selected by `kind: error-format` / `tags: [shutdown]` (id matching is a deprecated fallback that warns).
- Pluggable ext technologies: discovered from `templates/adapters/<tech>.go.j2` with optional `<tech>.deps`; an unknown technology warns (naming manifest and technology) and still gets port interfaces + fakes; franz-go is required only when a kafka ext exists; neutral catalog description/tags.
- `env` generator: POSIX `Makefile` + `scripts/` (lint, test, build, scan, e2e, publish, deploy, smoke, env-up/down), kind config, Strimzi Kafka/KafkaTopic/KafkaUser manifests and an e2e `sh` skeleton from `ydk:crosscut` ops/local-environment, `ydk:ext:kafka` and `ydk:test` e2e components.
- Phase `ops`: multi-stage offline Dockerfile (vendor; builder/runtime images from init answers, default `golang:1` / `scratch`; non-root, group 0), `.dockerignore`, and a Helm chart with a closed values schema, optional Route/Ingress and NetworkPolicy, and restricted-v2 pod security.
- `main.go` binds `LISTEN_HOST` (default all interfaces); the smoke check binds 127.0.0.1. Version injected with `-ldflags -X main.version`. The smoke check runs helm lint/template when helm is installed.

## 0.1.0

- Initial pack: stdlib `net/http` skeleton (config, slog, graceful shutdown, JSON errors, health), domain packages, franz-go Kafka adapter, embedded pages, publish smoke check.
