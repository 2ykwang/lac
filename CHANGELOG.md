# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [CalVer](https://calver.org/) (YYYY.MM.PATCH).

## [Unreleased]

## [2026.6.24] - 2026-06-24

### Added
- `lac sync` fast-forwards lac home from its remote (pull-only; never merges,
  commits, or pushes). On divergence it changes nothing and points you to a
  manual `git pull --rebase`.
- `lac register` offers to connect to storage registered on another machine
  instead of creating a duplicate slug, and records the binding in `.git/lac`
  (machine-local) so it survives repo moves and cross-machine sync.
- `doctor`/`list`/`status` distinguish `not-on-this-machine` (registered
  elsewhere) from `orphan` (bound here but the repo is gone).
- `lac status` lists conflicting file paths when lac home is mid-merge.

### Changed
- **Breaking:** the per-machine repo path moved out of the synced `.lac.meta`
  into a gitignored `<slug>/.lac.local`, so pulling lac home no longer
  conflicts on machine-specific paths. Older lac versions read the new
  `.lac.meta` as corrupted — upgrade all machines together, then run
  `lac register` once in each repo per machine.

## [2025.5.15] - 2025-05-15

Initial release.
