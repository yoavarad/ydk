# go-quality

Go code quality verification set. Runs gofmt, go vet, go test -race with a
per-package coverage gate, and a vendor/ freshness + `go build -mod=vendor`
check as part of the YDK verification pipeline.

Shipped with YDK. See `src/ydk/verifications/go-fmt/`, `go-vet/`, `go-test/`
and `go-vendor/` for the actual verification plugins. Configure under
`verification.go` (`coverage_min`, `coverage_packages`, `test_tags`, `race`).
