# CI workflow generation: `ydk ci init` with installed-ydk process checks

**Status:** proposed

YDK-managed repos get no CI today, so anything that bypasses local hooks goes unchecked and post-merge bookkeeping (closing tasks, story/epic rollup, retiring linked issues) depends on someone running it by hand. We're adding a new `ci` CLI group with `ydk ci init [--force]`, which writes GitHub Actions workflows into `.github/workflows/`; `ydk init` calls it automatically when `remote == github`, and it runs standalone to retrofit existing repos. Workflows split into stack-agnostic **process** checks (branch name, conventional commits, PR body, post-merge task/issue sync, merged-branch deletion, spec integrity) and one **stack** job (`ci.yml`): a real template for python and dotnet, and a generic `ydk verify run --trigger git:pre-push` fallback for other stacks. Process checks install ydk in CI (`uv tool install git+https://github.com/yoavarad/ydk@v<version>`, pinned to the generating ydk version) and call ydk commands, so CI runs the exact code the local plugins run. Two small entry points are added for this: `ydk verify pr-body --body-file` and `ydk task sync-issues`. Existing workflow files are skipped unless `--force`. Full detail: [spec](../specs/ci-workflow-generation.md).

## Considered options

- **Self-contained bash/YAML checks (no ydk in CI)** — what YDK's own `pr-body-check.yml` does today. No install step, but it re-implements `pr-body-validation/check.py` in bash and has already drifted in kind (no screenshot rule). Rejected: two sources of truth for every rule.
- **Install ydk from `@main` / latest** — always current, but a ydk change could break every managed repo's CI with no change in that repo. Rejected in favor of a pinned tag bumped by re-running `ydk ci init --force`.
- **Publish ydk to PyPI and `uv tool install ydk==X`** — cleaner install line, but adds a release channel YDK doesn't have. Deferred; the git+tag URL is swappable later without changing workflow structure.
- **Reusable workflows (`uses: yoavarad/ydk/.github/workflows/x.yml@vX`)** — less generated YAML, but ties managed repos to YDK's repo layout at runtime and makes local edits impossible. Rejected for v1; generated files are plain YAML the repo owns.
- **One big workflow file** — fewer files, but PR-body must re-run on `edited` while other checks shouldn't, and permissions would have to be the union (e.g. `issues: write` on every PR). Rejected: one file per trigger/permission shape.
- **Also generate for GitLab** — out of scope; GitLab support is a separate epic covering init, hooks and CI together.

## Consequences

- Managed repos need network access to GitHub for the install step; `yoavarad/ydk` is public, so no token is required.
- The B2 fallback skips the LLM-backed plugins (`ai-code-review`, `spec-alignment`) via a new `ydk verify run --skip-plugin`, keeping CI secret-free.
- Pinned versions go stale; upgrading ydk in CI means `ydk ci init --force` (which also discards local edits to generated files) or editing `YDK_VERSION`.
- The B2 fallback is weak for nextjs/terraform: runners may lack the toolchain the plugins shell out to. Documented in the generated file; proper templates are follow-up work.
- `ydk init`'s PR template is fixed to include `## Summary` / `## Test Plan`, and a test ties it to `validate_pr_body`.
- The `sync_issue_state.py` skill logic moves into the package; YDK's own `pr-body-check.yml` and `sync-linked-issues.yml` switch to the new CLI commands, and `ci-cd.mdx` is brought up to date.
- Release/version-from-tag workflows and Dependabot are not generated in v1.
