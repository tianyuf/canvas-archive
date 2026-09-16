# Contributing

Use the repository's issue forms for reproducible bugs and focused feature requests. For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Development

The project requires Python 3.10 or newer and has no third-party runtime dependencies.

Before opening a pull request, run:

```bash
python3 -m unittest -v
node --check web/app.js
python3 scripts/check_repository_privacy.py
```

## Test Data

Use only synthetic Canvas records in tests. Do not copy, redact, or anonymize a real export for use as a fixture because metadata and signed URLs are easy to miss.

## Changes

- Keep all Canvas API operations read-only unless a separate proposal explains the need.
- Preserve the local-only server binding and attachment allowlist.
- Add tests for new API fields, file routes, and archive states.
- Avoid third-party dependencies when the Python or browser standard library is sufficient.
- Update the README when commands, output paths, or privacy behavior change.
