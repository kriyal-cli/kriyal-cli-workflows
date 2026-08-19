# kriyal-cli-workflows

Generic, product-agnostic reusable GitHub Actions workflows. This repo is
public **on purpose** so it can be called cross-organization — GitHub only
allows a private repo's reusable workflows to be called from within the
same org, and these workflows are shared by repos spread across multiple
orgs.

Nothing here is product-specific: no hardcoded repo names, crate names,
secrets, or internal architecture. Callers pass all of that in via inputs.
Anything product-specific (security scanning, policy gates, custom test
suites) belongs in a private workflow in the *caller's* org that chains
after these jobs — keeping this repo generic is what lets it stay public
and change rarely.

## Workflows

### `reusable-verify.yml`

Tiered verification for a Rust workspace — `fast` (fmt, clippy, artefact
parse/lint, dependency hygiene) → `deep` (+ Kani proofs per crate that carries
`#[kani::proof]` harnesses, + `cargo geiger`, both cache-gated) → `nightly`
(deep with the cache disabled). `verify-caller.yml` is the caller that
`sync-verify-caller.yml` propagates into every tracked Rust repo as
`.github/workflows/verify.yml`, so new repos inherit it with no action. Full
notes: [VERIFY.md](VERIFY.md).

### `reusable-build.yml`

Build/test/lint/release pipeline for a Rust workspace, optionally spanning
multiple sibling repos.

Example caller (`.github/workflows/ci.yml` in a consuming repo):

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  build:
    uses: kriyal-cli/kriyal-cli-workflows/.github/workflows/reusable-build.yml@main
    with:
      checkout-repo: my-org/my-repo
      clone-repos: 'my-org/other-repo:other-repo'
      target-crates: 'my-crate other-crate'
      target-name: 'my-repo'
      run-tests: true
    secrets:
      CHECKOUT_TOKEN: ${{ secrets.CHECKOUT_TOKEN }}
```

See the `inputs:`/`secrets:` block at the top of the workflow file for the
full list of options.
