import json, sys, time, urllib.request
from pathlib import Path
config=json.loads(Path('platform.json').read_text())
origins=dict(pair.split('=',1) for pair in sys.argv[1:])
for check in config['checks']:
    url=origins[check['service']]+check['path']
    error=None
    for _ in range(6):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body=response.read().decode()
                assert response.status == 200
                assert body == check['body'] if 'body' in check else check['contains'] in body
            break
        except Exception as exc:
            error=exc
            time.sleep(1)
    else:
        raise SystemExit(f'FAIL: {url}: response did not satisfy application contract ({error})')
print('PASS: all application HTTP contracts.')
