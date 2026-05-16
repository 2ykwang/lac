# Contributing to lac

## Development setup

```bash
git clone https://github.com/2ykwang/lac.git
cd lac
uv sync                # creates .venv with deps + dev tools
uv run lac --help      # verify installation
```

Requires Python 3.11+, git, and [uv](https://docs.astral.sh/uv/).

## Four gates before commit

```bash
uv run ruff check                       # lint
uv run ruff format                      # format
uv run pytest                           # tests
bash .claude/scripts/lint-comments.sh   # comment objectivity check
```

All four must pass before opening a PR.

## Code style

See [`.claude/rules/style.md`](.claude/rules/style.md) for code conventions.

## Testing

See [`.claude/rules/testing.md`](.claude/rules/testing.md) for test conventions. Two test categories:

- **Spec tests** (`tests/test_spec.py`) — one decision per test.
- **Scenario tests** (`tests/test_e2e.py`) — one user workflow per test.

## License

By contributing, you agree your contributions are licensed under MIT.
