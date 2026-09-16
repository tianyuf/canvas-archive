# Security Policy

## Sensitive Data

Canvas exports can contain protected educational records, private messages, account identifiers, calendar feed URLs, signed download URLs, and submitted documents.

Never include any of the following in a GitHub issue, pull request, commit, test fixture, screenshot, or workflow artifact:

- A `canvas-export-*` directory or any file from it
- A Canvas API access token
- A Canvas calendar feed URL
- A signed or verifier-bearing Canvas download URL
- Real student names, IDs, email addresses, grades, comments, or submissions

Use synthetic records in tests and bug reports.

## Reporting A Vulnerability

Use GitHub private vulnerability reporting if it is enabled for the repository. Otherwise, contact the repository owner privately outside GitHub issues.

Include reproduction steps and affected source files, but do not include real Canvas data. If a token was exposed, revoke it immediately from **Account > Settings > Approved Integrations** before reporting the problem.

## Supported Version

Only the latest revision on the default branch is supported.

## Local Server

The archive browser binds to `127.0.0.1` by default. Do not change it to `0.0.0.0` or expose its port through a tunnel, reverse proxy, public cloud service, or shared development environment while viewing a real archive.
