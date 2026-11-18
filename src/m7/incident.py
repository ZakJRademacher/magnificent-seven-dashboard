"""Open, update and close pipeline incidents as GitHub issues.

    python -m m7.incident run.json

A failed run (or one more than a session behind) opens an issue labelled
`pipeline-incident`, or comments on the one already open. The first healthy run
afterwards comments with how long the incident lasted and closes it.
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

LABEL = "pipeline-incident"
STATUS_PAGE = "https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html"
RUNBOOK = "https://github.com/ZakJRademacher/magnificent-seven-dashboard/blob/main/docs/OPERATIONS.md"


def unhealthy(record):
    return record is None or record["status"] in ("failed", "degraded")


def describe(record, run_url):
    if record is None:
        return "The pipeline crashed before it could record the run.", f"Run log: {run_url}"
    reason = record["error"] or next((f"{c['name']}: {c['detail']}" for c in record["checks"] if c["status"] == "fail"),
                                     "unknown")
    headline = ("Run failed; the last good data is still live." if record["status"] == "failed"
                else "Published, but the data is more than one trading day behind.")
    body = "\n".join([
        headline, "",
        f"- **Reason:** {reason}",
        f"- **Data as of:** {record['as_of']}",
        f"- **Run:** `{record['run_id']}` ({record['trigger']}) finished {record['finished']}",
        f"- **Log:** {run_url}",
        f"- **Status page:** {STATUS_PAGE}",
        f"- **Runbook:** {RUNBOOK}",
    ])
    return headline, body


def decide(record, open_issue, run_url, now=None):
    """What to do, as (action, payload). Pure, so it can be tested without GitHub.

    open_issue: None or {"number", "createdAt"} for the currently open incident.
    """
    if unhealthy(record):
        headline, body = describe(record, run_url)
        if open_issue:
            return "comment", {"number": open_issue["number"], "body": "Still unhealthy.\n\n" + body}
        day = record["started"][:10] if record else pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        return "open", {"title": f"Pipeline incident {day}: {headline.split(';')[0].rstrip('.')}", "body": body}
    if open_issue:
        now = pd.Timestamp(now or record["finished"])
        lasted = now - pd.Timestamp(open_issue["createdAt"])
        hours = lasted.total_seconds() / 3600
        body = (f"Recovered: run `{record['run_id']}` published data as of {record['as_of']}, "
                f"{record['rows_added']} new day(s). The incident lasted {hours:.1f} hours.\n\nLog: {run_url}")
        return "close", {"number": open_issue["number"], "body": body}
    return "none", {}


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main(argv=None):
    argv = argv or sys.argv[1:]
    path = Path(argv[0]) if argv else Path("run.json")
    record = json.loads(path.read_text()) if path.exists() else None
    import os
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    issues = json.loads(gh("issue", "list", "--label", LABEL, "--state", "open", "--json", "number,createdAt", "--limit", "1"))
    action, payload = decide(record, issues[0] if issues else None, run_url)
    if action == "open":
        gh("label", "create", LABEL, "--color", "E66767", "--description", "Opened and closed by the daily pipeline", "--force")
        print(gh("issue", "create", "--label", LABEL, "--title", payload["title"], "--body", payload["body"]).strip())
    elif action == "comment":
        gh("issue", "comment", str(payload["number"]), "--body", payload["body"])
    elif action == "close":
        gh("issue", "close", str(payload["number"]), "--comment", payload["body"])
    print(f"Incident action: {action}")


if __name__ == "__main__":
    main()
