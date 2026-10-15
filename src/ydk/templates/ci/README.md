# CI workflow templates

Package data for `ydk ci init` (see `src/ydk/core/ci_generator.py`). Each `*.yml` here is registered
as a `CiTarget` in `CI_TARGETS` and rendered into `.github/workflows/`.

Placeholders (plain substitution, no Jinja): `{{YDK_VERSION}}`, `{{STACK}}`, `{{SPEC_LOCATION}}`,
`{{COMPONENTS_PATH}}`, `{{SCHEMAS_PATH}}`. GitHub expressions such as `${{ github.ref }}` pass through untouched.

Make-wrapper templates (`ci-go.yml`, `ci-make.yml`) also take `{{MAKE_STEPS}}`: one `make <target>` step per
`ci.make_targets` entry (go defaults to `lint test`). `gitlab-ci.yml.j2` is the one Jinja template; it renders
`.gitlab-ci.yml` for `ydk ci init --gitlab` (stages = make targets, image from `ci.gitlab.image`, no includes).
