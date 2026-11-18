"""Dead-man's switch: alert when the pipeline has gone quiet.

    python -m m7.watchdog runs.jsonl

A failing pipeline raises its own incident, but a pipeline that stops running
(GitHub skips or disables the schedule) can't. This runs separately, on its own
schedule, reads the run ledger from the data branch, and raises an incident if
the published data is two or more trading days behind. It exits with status 1
when it alerts, so GitHub's failed-workflow email arrives as well. The pipeline's
next healthy run closes the incident.
"""
import json
import sys
from pathlib import Path

import pandas as pd

from . import incident, sessions

QUIET_SESSIONS = 2


def check(runs, now=None):
    """None when healthy, otherwise a description of what's wrong."""
    published = [r for r in runs if r["status"] in ("published", "degraded") and r.get("as_of")]
    if not published:
        return "The run ledger has no published run."
    latest = published[-1]
    behind = sessions.sessions_behind(latest["as_of"], now)
    if behind < QUIET_SESSIONS:
        return None
    last_run = runs[-1]
    return (f"The published data is {behind} trading days behind: the latest published day is {latest['as_of']}, "
            f"last published by run `{latest['run_id']}` at {latest['finished']}. The most recent run of any kind was "
            f"`{last_run['run_id']}` ({last_run['status']}) at {last_run['finished']}. If there are no recent runs, "
            "the schedule has stopped: check the Actions tab and re-enable 'Update live dashboard'.")


def main(argv=None):
    argv = argv or sys.argv[1:]
    path = Path(argv[0]) if argv else Path("runs.jsonl")
    runs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    problem = check(runs)
    if problem is None:
        print("Pipeline is publishing on schedule.")
        return 0
    print(problem)
    open_issues = json.loads(incident.gh("issue", "list", "--label", incident.LABEL, "--state", "open",
                                         "--json", "number", "--limit", "1"))
    body = f"**Watchdog:** {problem}\n\n- **Status page:** {incident.STATUS_PAGE}\n- **Runbook:** {incident.RUNBOOK}"
    if open_issues:
        incident.gh("issue", "comment", str(open_issues[0]["number"]), "--body", body)
    else:
        incident.gh("label", "create", incident.LABEL, "--color", "E66767", "--description",
                    "Opened and closed by the daily pipeline", "--force")
        day = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        incident.gh("issue", "create", "--label", incident.LABEL, "--title", f"Pipeline incident {day}: no data published recently",
                    "--body", body)
    return 1


if __name__ == "__main__":
    sys.exit(main())
