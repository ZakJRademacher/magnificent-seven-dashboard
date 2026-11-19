"""Exercise the deployed repository's issue permissions with a fixture run."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from m7 import data, incident, ledger, pipeline


def run():
    if (os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_REF')) != (
        'ZakJRademacher/magnificent-seven-dashboard', 'refs/heads/ops/verify-incident-issues'
    ):
        raise RuntimeError('Run the verification from the designated GitHub Actions branch.')
    run_id = os.environ['GITHUB_RUN_ID']
    title = f'[Drill {run_id}]'
    label = 'pipeline-incident-drill'
    original_decide = incident.decide

    def identify_drill(record, open_issue, run_url):
        action, message = original_decide(record, open_issue, run_url, now=datetime.now(timezone.utc))
        if action == 'open':
            message['title'] = f'{title} Fixture failure and recovery verification'
            message['body'] = 'This check uses fixture prices and a simulated failure.\n\n' + message['body']
        return action, message

    def issues():
        result = incident.gh('issue', 'list', '--label', label, '--state', 'open', '--json', 'number,title')
        return json.loads(result)

    def wait_for(check, diagnosis):
        for _ in range(15):
            if result := check():
                return result
            time.sleep(2)
        raise RuntimeError(diagnosis)

    pending = issues()
    if pending:
        if len(pending) != 1 or not re.fullmatch(
            r'\[Drill [0-9]+\] Fixture failure and recovery verification', pending[0]['title']
        ):
            raise RuntimeError('The drill label contains an unexpected open issue.')
        previous_title = pending[0]['title']
        number = str(pending[0]['number'])
        if json.loads(incident.gh('issue', 'view', number, '--json', 'comments'))['comments']:
            raise RuntimeError('The previous fixture incident has comments and needs manual review.')
    else:
        previous_title = None
    try:
        with TemporaryDirectory() as temp, patch.object(incident, 'LABEL', label), patch.object(
            incident, 'decide', identify_drill
        ):
            root = Path(temp)
            prices, rates = data.load_cache()
            prices = prices[data.SERIES]
            previous = prices.iloc[:-1]
            ledger.State(root / 'state').save(previous, rates.reindex(previous.index))
            bad = prices.drop(prices.index[-10])
            stamp = f'{prices.index[-1]:%Y-%m-%d}T22:17:00Z'
            record_file = root / 'run.json'

            def replay(history):
                result = pipeline.run(root / 'state', root / 'site',
                                      fetch=lambda: (history, rates), now=stamp, trigger='fixture drill')
                record_file.write_text(json.dumps(result), encoding='utf-8')
                return result

            failed = replay(bad)
            assert (failed['status'], failed['as_of']) == ('failed', f'{previous.index[-1]:%Y-%m-%d}')
            if previous_title:
                print(f'Resuming the fixture-only incident opened by the previous run, #{number}.')
            else:
                incident.main([str(record_file)])
                opened = wait_for(issues, 'GitHub issue listing did not catch up after issue creation.')
                assert len(opened) == 1 and opened[0]['title'].startswith(title), opened
                number = str(opened[0]['number'])
            incident.main([str(record_file)])
            recovered = replay(prices)
            assert (recovered['status'], recovered['rows_added']) == ('published', 1), recovered
            incident.main([str(record_file)])
            def closed_with_comments():
                saved = json.loads(incident.gh('issue', 'view', number, '--json', 'state,comments,url'))
                if saved['state'] == 'CLOSED' and len(saved['comments']) == 2:
                    return saved

            saved = wait_for(closed_with_comments, 'GitHub did not show the closed issue and both comments.')
            assert saved['comments'][0]['body'].startswith('Still unhealthy.')
            assert saved['comments'][1]['body'].startswith('Recovered:')
            print(f"Fixture incident opened, commented, and closed using the workflow token. {saved['url']}")
    finally:
        for issue in issues():
            if issue['title'].startswith(title) or issue['title'] == previous_title:
                incident.gh('issue', 'close', str(issue['number']), '--comment',
                            'The fixture run ended before normal cleanup.')


if __name__ == '__main__':
    run()
