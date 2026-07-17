# Contributing to agent-recall

We welcome issues and pull requests in both Japanese and English.

## Reporting Issues

- Check existing issues first to avoid duplicates
- Use clear titles and descriptions
- Include your environment (OS, Claude Code version, Python version)
- Provide minimal reproduction steps when possible

## Pull Requests

- Direct pushes to `main` are not allowed — changes must go through a PR with a green CI.
- One PR per feature or fix
- Include tests for any new functionality
- Ensure all tests pass: `uv run pytest`
- Ensure hook tests pass: `bash hooks/check-setup.test.sh` and `bash hooks/archive-session.test.sh`
- Keep commit messages atomic and descriptive (Japanese or English)

## Testing

All changes must maintain test coverage:

```bash
# Unit tests
uv run pytest

# Hook validation
bash hooks/check-setup.test.sh
bash hooks/archive-session.test.sh
```

## Code Style

- Follow PEP 8 for Python code
- Use descriptive variable and function names
- Include comments explaining the "why" (not the "what")

## Questions?

Feel free to open an issue with the `question` label or discuss in pull request comments.
