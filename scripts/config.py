"""Validate project configuration and emit safely quoted Bash bindings."""
import json, re, shlex, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
c = json.loads((root / 'platform.json').read_text())
assert c['schemaVersion'] == 1, 'Unsupported platform.json schemaVersion'
apps = c['applications']
assert apps, 'At least one application is required'
def name(v):
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,52}', v), f'Invalid resource name: {v}'
    return v
def path(v):
    p = Path(v)
    assert not p.is_absolute() and '..' not in p.parts and (root/p).exists(), f'Invalid project path: {v}'
    return v
def bind(k, v): print(f'{k}={shlex.quote(str(v))}')
for a, meta in apps.items():
    name(a)
    for field in ('dockerfile', 'values'): path(meta[field])
    assert re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9./:_-]*', meta['image']), 'Invalid image repository'
    for field in ('port', 'localPort'): assert type(meta[field]) is int and 1 <= meta[field] <= 65535
for check in c['checks']:
    assert check['service'] in apps and check['path'].startswith('/')
    assert ('body' in check) != ('contains' in check), 'Use exactly one check assertion'
db = c['database']
assert db['client'] in apps
for k in ('release','statefulset','secret','pvc'): name(db[k])
for k in ('values','outageCheck'): path(db[k])
if 'serviceAccountManifest' in db: path(db['serviceAccountManifest'])
bind('CLUSTER', name(c['cluster'])); bind('NAMESPACE', name(c['namespace']))
bind('KIND_CONFIG', path(c['kindConfig']) if 'kindConfig' in c else Path(__file__).resolve().parents[1] / 'defaults/kind.yaml')
bind('NAMESPACE_MANIFEST', path(c['namespaceManifest']) if 'namespaceManifest' in c else '')
bind('APPS', ' '.join(apps))
print('BUILD_CONTEXT=('+' '.join(shlex.quote(path(p)) for p in c['buildContext'])+')')
for key, field in {'DB_RELEASE':'release','DB_VALUES':'values','DB_STATEFULSET':'statefulset','DB_PVC':'pvc','DB_SECRET':'secret','DB_USER':'developmentUser','DB_PASSWORD':'developmentPassword','DB_CLIENT':'client','DB_OUTAGE_CHECK':'outageCheck'}.items(): bind(key,db[field])
bind('DB_ACCOUNT', db.get('serviceAccountManifest', ''))
for field in ('release','statefulset','pvc'): bind('LEGACY_'+field.upper(), name(c['legacy'][field]) if c.get('legacy',{}).get(field) else '')
for field in ('dockerfile','image','values','port','localPort'):
    print(f'app_{field}() {{ case "$1" in')
    for a, meta in apps.items(): print(f'{shlex.quote(a)}) printf \'%s\\n\' {shlex.quote(str(meta[field]))} ;;')
    print('*) return 1 ;; esac; }')
