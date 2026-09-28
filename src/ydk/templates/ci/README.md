# CI workflow templates

Package data for `ydk ci init` (see `src/ydk/core/ci_generator.py`). Each `*.yml` here is registered
as a `CiTarget` in `CI_TARGETS` and rendered into `.github/workflows/`.

Placeholders (plain substitution, no Jinja): `{{YDK_VERSION}}`, `{{STACK}}`, `{{SPEC_LOCATION}}`,
`{{COMPONENTS_PATH}}`, `{{SCHEMAS_PATH}}`. GitHub expressions such as `${{ github.ref }}` pass through untouched.
