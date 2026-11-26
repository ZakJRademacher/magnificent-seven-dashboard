# Security policy

## Supported versions

Only the live dashboard and the latest release get security fixes.

| Version | Supported |
| --- | --- |
| 1.x (latest) | Yes |
| Older | No |

## Reporting a vulnerability

Please report security problems privately, not in a public issue.

1. Go to the repository's **Security** tab and choose **Report a vulnerability**. This opens a private advisory that only the maintainer can see.
2. Describe the problem, the affected page or file, and how to reproduce it.

You should get a reply within 7 days. Once a fix is released, the advisory is published with credit to you, unless you'd rather stay anonymous.

## Scope

These are in scope:

- The live dashboard, including script injection.
- The data pipeline and its workflows, including anything that could let untrusted input change published figures or the `data` branch.
- Secrets or private data committed to the repository, the GitHub Actions workflows, and pinned dependencies.

Out of scope are problems in the market data provider and GitHub themselves, and disagreements about the analysis (open an issue for those).
