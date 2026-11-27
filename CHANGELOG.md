# Changelog

## Unreleased

- A daily note: three plain-English bullets about the latest trading day, written by Claude Opus 5.5 from a fact sheet. The model refers to figures by placeholder and code fills in every number; a guard rejects any note with a typed number, an untrue or untagged claim, another company's name, advice or predictions. Written only on scheduled and manual runs of `main`, once per day's facts; a failure is a non-blocking `note` warning and the previous note stays up. See the README's "Daily note" section.
- `evals/`: 30 past trading days with independently worked-out answers; the release gate is every note passing the guard with every tagged claim correct.
- Dry runs (pull requests, other branches) now run with read-only permissions and no saved credentials, in their own job.

## 1.0.0 (2026-11-20)

First numbered release. Earlier history is in the git log.

- A dividend whose ex-date falls on a day left out as incomplete is now recognized and logged instead of blocking publication (the Nov 20, 2026 incident).
- The page footer shows the version.
- GitHub Pages actions updated to configure-pages v6, upload-pages-artifact v5 and deploy-pages v5 (Node 24).
