# Tiered verification

Shared, **product-agnostic** verification for Rust workspaces: one reusable
workflow, three tiers, propagated to every tracked repo (including repos
created later) by `sync-verify-caller.yml`.

## Why these live in a PUBLIC repo

GitHub only lets a **private** repo's reusable workflows be called from repos in
the **same org**; cross-org reuse requires the workflow repo to be public
(`internal` needs Enterprise). The repos that consume this are spread across
several orgs (see `orgs.txt`), so a workflow hosted in a private repo could
only ever be called from inside that one org — i.e. nobody would inherit it.
Hence the split this repo's top-level README already states, and which these
files keep to:

| public (here) | private (each product repo) |
|---|---|
| the MECHANISM: which tools run, in what tier, with what cache key | the POLICY: which operations are approved, which advisories are accepted, what consumes the output |
| `cargo fmt/clippy/kani/geiger`, shellcheck/actionlint, parse checks | approval lists, advisory acceptances, downstream evidence pipelines |

Nothing in these files names a repo, a crate, an internal path, or a secret.
Every product-specific value arrives as an input from the caller.

Propagation uses the same shape as `sync-dependabot.yml`: `sync-verify-caller.yml`
pushes `verify-caller.yml` into each tracked repo as `.github/workflows/verify.yml`.
Two rules make that safe for a workflow (as opposed to a config file):

* **Rust repos only** — a repo with no root `Cargo.toml` is skipped. Pushing a
  Rust gate into a docs or JS repo would hand it a permanently red Actions tab,
  which teaches people to ignore red.
* **Opt-out is honoured** — a repo whose `verify.yml` contains
  `# kriyal-sync: off` has taken ownership; the sync never touches it again.

New repos need no action: the next weekly run (or a manual
`workflow_dispatch`, `dry-run: true` to preview) picks them up.

## Files

| path | what |
|---|---|
| `.github/workflows/reusable-verify.yml` | the tiered gate: `fast` (cheap) → `deep` (PR) → `nightly` (cold, no cache) |
| `.github/actions/kani-discover/action.yml` | composite action: scan a checkout for `#[kani::proof]` and emit a crate matrix |
| `verify-caller.yml` | the 40-line caller synced into every tracked Rust repo |
| `.github/workflows/sync-verify-caller.yml` | the propagator (weekly + on change + manual, with `dry-run`) |

## Tiers

| tier | runs | intended trigger |
|---|---|---|
| `fast` | fmt, clippy `-D`, artifact audit (shell/YAML/JSON/TOML/JS parse + shellcheck + actionlint + kubeconform), dependency hygiene | every push / draft PR |
| `deep` | everything in `fast` + Kani proofs (one job per discovered crate) + `cargo geiger`, both **cache-gated** | PR ready-for-review, merge queue |
| `nightly` | `deep` with the cache disabled | scheduled |

The cache is what makes `deep` affordable: a crate's proof verdict and a
workspace's geiger totals are pure functions of (sources | lockfile) + toolchain
versions, so an unchanged subject replays in milliseconds. `nightly` runs cold
because a cache is an assumption, and the nightly is where assumptions get
checked.

## Caller example

```yaml
name: Verify
on:
  pull_request:
  push: { branches: [main] }
  schedule: [{ cron: "17 4 * * *" }]

jobs:
  verify:
    uses: kriyal-cli/kriyal-cli-workflows/.github/workflows/reusable-verify.yml@main
    with:
      tier: ${{ github.event_name == 'schedule' && 'nightly' || (github.event_name == 'pull_request' && 'deep' || 'fast') }}
      clippy-args: '-D warnings -D clippy::correctness -D clippy::suspicious -D clippy::perf -D clippy::complexity'
      kani-enforce: true
```
