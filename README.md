# Canvas Personal Archive

[![Test](https://github.com/tianyuf/canvas-personal-archive/actions/workflows/test.yml/badge.svg)](https://github.com/tianyuf/canvas-personal-archive/actions/workflows/test.yml)

A read-only Canvas LMS exporter and local browser for grades, feedback, submissions, files, discussions, quizzes, and Inbox conversations.

The project uses only the Python standard library. Exported records remain on your computer and are excluded from Git by default.

[Export](#export-your-data) | [Browse](#browse-an-export) | [Limitations](#limitations) | [Security](SECURITY.md) | [Contributing](CONTRIBUTING.md)

> [!CAUTION]
> Canvas exports contain private educational records, messages, account identifiers, and signed file URLs. Never commit an export directory or access token, even to a private repository.

## Features

- Per-assignment grades, comments, rubric assessments, and submission history
- Submitted files, personal files, discussion attachments, and Inbox attachments
- Classic Quiz attempts and answers when Canvas permits access
- Read-only local browser with course, feedback, file, and Inbox views
- Unified search across courses, assignments, comments, files, and messages
- Clear distinctions between empty, exporting, unavailable, and access-limited data
- Responsive comfortable and compact layouts

## Requirements

- Python 3.10 or newer
- A Canvas account that permits personal API tokens
- A modern web browser

No Python or JavaScript packages are required.

## Canvas Compatibility

The exporter uses standard Instructure Canvas REST API endpoints and supports institution-hosted, custom-domain, and `instructure.com` Canvas sites. Stanford is only the default host; pass your Canvas root URL with `--base-url` for another institution.

Your institution must permit personal API tokens or provide a compatible bearer token. Institution policies, course retention settings, and Canvas feature availability determine which records the API returns.

## Create A Canvas Token

1. Sign in to your institution's Canvas site.
2. Open **Account**, then **Settings**.
3. Find **Approved Integrations** and select **New Access Token**.
4. Use a short expiration date and copy the token when Canvas displays it.

Do not use your institutional password in this project. Do not put the token in source code, a shell command, an `.env` file, an issue, or a pull request.

If the **New Access Token** button is unavailable, contact your institution's Canvas administrator or privacy office and request a complete data export.

## Export Your Data

Run the exporter from the repository directory:

```bash
python3 export_canvas.py
```

The default Canvas host is `https://canvas.stanford.edu`. For another institution:

```bash
python3 export_canvas.py --base-url https://canvas.example.edu
```

The script prompts for the token with hidden input and keeps it only in process memory. It creates a timestamped `canvas-export-*` directory.

For a smaller test, use the numeric course ID from its Canvas URL:

```bash
python3 export_canvas.py --course-id 12345 --no-files
```

Run `python3 export_canvas.py --help` for all options.

## Browse An Export

Start the local browser:

```bash
python3 archive_browser.py
```

The application opens at <http://127.0.0.1:8765>. It binds only to the local computer and serves downloaded attachments through an allowlist. Raw account JSON and access credentials are not exposed through HTTP.

By default, the browser opens the newest `canvas-export-*` directory. To select another archive or port:

```bash
python3 archive_browser.py ./canvas-export-YYYYMMDD-HHMMSS --port 9000
```

Press `Ctrl-C` to stop the foreground server.

## Export Contents

- `all-grades.csv`: assignment grades across accessible courses
- `all-comments.csv`: assignment comments across accessible courses
- `courses/`: assignments, submissions, rubrics, quizzes, discussions, and files by course
- `inbox/`: Canvas Inbox conversations and attachments
- `personal-files/`: files stored in the Canvas account
- `manifest.json`: counts, limitations, and API requests Canvas refused

JSON files preserve details that do not fit cleanly into CSV, including rubrics, submission history, and quiz attempts.

## Limitations

Canvas only returns information the account can currently access. Course retention policies, concluded-course restrictions, and instructor settings can block older records. New Quizzes and external learning tools use separate services. DocViewer annotations may require a separate manual PDF download.

## Privacy And GitHub

This repository is designed to store source code only. `.gitignore` excludes:

- Every `canvas-export-*` directory
- Environment and token files
- Partial downloads
- Python caches, build output, test coverage, and editor files

Run the privacy check before staging files:

```bash
python3 scripts/check_repository_privacy.py
```

GitHub Pages is not supported. The browser depends on a local Python API, and deploying a real archive as static data would publish private educational records. Keep the repository private and run the browser locally.

## Tests

```bash
python3 -m unittest -v
node --check web/app.js
python3 scripts/check_repository_privacy.py
```

GitHub Actions runs the same checks on every push and pull request.

## Repository Layout

```text
archive_browser.py          Local read-only web server and archive model
export_canvas.py            Canvas API exporter
scripts/                    Repository privacy checks
test_archive_browser.py     Browser and HTTP security tests
test_export_canvas.py       Export normalization tests
web/                        Static HTML, CSS, and JavaScript interface
```

## Security

See [SECURITY.md](SECURITY.md) before reporting a problem. Never attach an export, Canvas token, student record, or signed Canvas URL to a GitHub issue.

## Contributing

Bug reports and feature requests use privacy-aware GitHub issue forms. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and use only synthetic Canvas records in tests and examples.
