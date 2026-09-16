# Private GitHub Repository Setup

The repository should contain source code only. Keep all `canvas-export-*` directories on the local computer.

## Before Initializing Git

Run the complete local verification:

```bash
python3 scripts/check_repository_privacy.py
python3 -m unittest -v
node --check web/app.js
```

If macOS blocks Git because the Xcode license has not been accepted, review it first:

```bash
sudo xcodebuild -license
```

## Initialize And Inspect

```bash
git init -b main
git add .gitattributes .gitignore .github CONTRIBUTING.md GITHUB_SETUP.md README.md SECURITY.md
git add archive_browser.py export_canvas.py scripts test_archive_browser.py test_export_canvas.py web
git status --short
git diff --cached --stat
git diff --cached --name-only
```

The staged file list must not contain:

- `canvas-export-*`
- `.env` files
- downloaded assignments or attachments
- logs, caches, or partial files

Inspect the staged diff before committing. Do not rely on the repository being private as a substitute for this check.

## Create The Private Repository

After reviewing the staged content:

```bash
git commit -m "Initial private release"
gh repo create canvas-archive --private --source=. --remote=origin --push
```

The GitHub Actions workflow runs the privacy scanner, Python tests, and JavaScript syntax check after the push.

## Recommended Repository Settings

- Keep repository visibility set to **Private**.
- Enable secret scanning and push protection when available.
- Enable private vulnerability reporting.
- Require the `verify` workflow before merging changes into the default branch.
- Do not enable GitHub Pages for this repository.
- Do not upload exports as workflow artifacts or release assets.
