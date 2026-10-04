"""Validate project configuration and emit safely quoted Bash bindings."""
import json, os, re, shlex, sys
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
environment = os.environ.get('PLATFORM_ENVIRONMENT', 'local')
assert environment in ('local', 'app-ci', 'app-dev'), 'Only local, app-ci and app-dev are supported; production deployment is disabled'
bind('PLATFORM_ENVIRONMENT', environment)
bind('IMAGE_PLATFORM', 'linux/amd64')
if environment != 'local':
    target = c['environments'][environment]
    assert target['namespace'] == environment, 'Environment and namespace must match'
    c['cluster'] = name(target['cluster'])
    c['namespace'] = target['namespace']
    assert target['context'] == 'kind-' + c['cluster'], 'Context must match the configured kind cluster'
    prefix = target['imagePrefix']
    assert re.fullmatch(r'ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._/-]*', prefix) and not prefix.endswith('/'), 'Invalid GHCR image prefix'
    for app, meta in apps.items():
        meta['image'] = prefix + '/' + name(app)
    # Shared infrastructure is pre-provisioned; project manifests cannot target another namespace.
    c.pop('namespaceManifest', None)
    c['database'].pop('serviceAccountManifest', None)
    bind('KUBE_CONTEXT', target['context'])
else:
    bind('KUBE_CONTEXT', 'kind-' + name(c['cluster']))
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
for key, field in {'DB_RELEASE':'release','DB_VALUES':'values','DB_STATEFULSET':'statefulset','DB_PVC':'pvc','DB_SECRET':'secret','DB_CLIENT':'client','DB_OUTAGE_CHECK':'outageCheck'}.items(): bind(key,db[field])
bind('DB_ACCOUNT', db.get('serviceAccountManifest', ''))
for field in ('release','statefulset','pvc'): bind('LEGACY_'+field.upper(), name(c['legacy'][field]) if c.get('legacy',{}).get(field) else '')
for field in ('dockerfile','image','values','port','localPort'):
    print(f'app_{field}() {{ case "$1" in')
    for a, meta in apps.items(): print(f'{shlex.quote(a)}) printf \'%s\\n\' {shlex.quote(str(meta[field]))} ;;')
    print('*) return 1 ;; esac; }')

for key, field, default in [('DB_NAME', 'developmentName', 'api-db'), ('DB_USER', 'developmentUser', ''), ('DB_PASSWORD', 'developmentPassword', '')]:
    value = db.get(field, default) if environment == 'local' else os.environ.get(key, '')
    assert value, f'Set {key} in the selected GitHub environment'
    bind(key, value)
