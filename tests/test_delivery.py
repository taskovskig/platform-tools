"""Exercise the real deployment script with traced CLI boundaries and a local HTTP check."""
import http.server
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]

MOCK = '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ['TRACE'], 'a') as log: log.write(json.dumps([name, *args])+'\\n')
if name == 'git': print('abc1234')
if name == 'docker' and args[:2] == ['image', 'inspect'] and '--format' in args:
    fmt=args[-1]
    if fmt == '{{.Id}}': print('sha256:' + ('b' if args[2].endswith(':ci-passed') and os.environ.get('UNTESTED') else 'a')*64)
    elif 'source-tree' in fmt: print('wrong' if os.environ.get('WRONG_TREE') else 'abc1234')
    elif 'ci-build' in fmt: print('ci-42')
    else: print(args[2].rsplit(':', 1)[0]+'@sha256:'+'a'*64)
if name == 'docker' and 'manifest' in args and os.environ.get('PRIVATE_IMAGE'):
    sys.exit(1)
if name == 'kind':
    if not os.environ.get('ALLOW_LOCAL'): sys.exit('Shared-cluster lifecycle operation attempted')
    if args[:2] == ['get', 'clusters']: print('disposable')
    if args[:2] == ['export', 'kubeconfig']: pathlib.Path(args[-1]).write_text('local config')
if name == 'kubectl':
    if 'get' in args and ('secret' in args or 'pvc' in args): sys.exit(1)
    if 'port-forward' in args:
        print('Forwarding from 127.0.0.1:'+os.environ['HTTP_PORT']+' -> 3000', flush=True)
        time.sleep(30)
'''


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'file').write_text('fixture')
        (self.root / 'kubeconfig').write_text('credential fixture')
        self.config = {
            'schemaVersion': 1, 'cluster': 'disposable', 'namespace': 'local',
            'buildContext': ['file'],
            'applications': {'frontend': {'dockerfile': 'file', 'values': 'file', 'image': 'sample', 'port': 3000, 'localPort': 4300}},
            'checks': [{'service': 'frontend', 'path': '/', 'body': 'ok'}],
            'database': {'release': 'db', 'statefulset': 'db', 'secret': 'database', 'pvc': 'data-db-0', 'values': 'file', 'client': 'frontend', 'outageCheck': 'file', 'developmentUser': 'user', 'developmentPassword': 'password'},
            'environments': {'app-ci': {'cluster': 'testkube-samples', 'context': 'kind-testkube-samples', 'namespace': 'app-ci', 'imagePrefix': 'ghcr.io/example/project'}},
        }
        self.config['environments']['app-dev'] = dict(self.config['environments']['app-ci'], namespace='app-dev')
        (self.root / 'platform.json').write_text(json.dumps(self.config))
        (self.root / 'bin').mkdir()
        for tool in ['kubectl', 'helm', 'docker', 'kind', 'git', 'shasum']:
            path = self.root / 'bin' / tool
            path.write_text(MOCK)
            path.chmod(0o755)
        (self.root / '.platform').mkdir()
        (self.root / '.platform/postgres-1.6.8.tgz').write_text('chart fixture')
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = dict(os.environ, PROJECT_ROOT=str(self.root), PLATFORM_ENVIRONMENT='app-ci', GH_BUILD_NUMBER='42', DB_NAME='ci-db', DB_USER='ci-user', DB_PASSWORD='ci-pass',
                        KUBECONFIG=str(self.root / 'kubeconfig'), TRACE=str(self.root / 'trace'),
                        HTTP_PORT=str(self.server.server_port), PATH=str(self.root / 'bin')+os.pathsep+os.environ['PATH'])

    def run_platform(self, command, **environment):
        return subprocess.run(['bash', str(TOOLS / 'scripts/platform.sh'), command], env=dict(self.env, **environment), capture_output=True, text=True, timeout=15)

    def trace(self):
        path = self.root / 'trace'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_application_version(self, calls, expected):
        application = [call for call in calls if call[0] == 'helm' and 'upgrade' in call and 'frontend' in call]
        self.assertEqual(len(application), 2)  # Server dry-run and real upgrade.
        chart_paths = {call[call.index('frontend') + 1] for call in application}
        self.assertEqual(len(chart_paths), 1)
        chart = Path(chart_paths.pop())
        self.assertNotEqual(chart, TOOLS / 'helm')
        self.assertIn('appVersion: ' + json.dumps(expected), (chart / 'Chart.yaml').read_text())
        self.assertIn(['helm', 'lint', str(chart), '--strict', '-f', 'file'], calls)
        self.assertIn('appVersion: "1.0.0"', (TOOLS / 'helm/Chart.yaml').read_text())

    def test_deploy_publishes_digest_and_never_manages_shared_cluster(self):
        result = self.run_platform('ci-up')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.trace()
        self.assertFalse(any(call[0] == 'kind' for call in calls))
        for tag in ['ci-42', 'ci-latest']:
            self.assertTrue(any(call[:2] == ['docker', 'push'] and call[-1].endswith(':'+tag) for call in calls))
        self.assertTrue(any('--platform' in call and 'linux/amd64' in call for call in calls))
        for call in calls:
            if call[0] in ('kubectl', 'helm') and '--kubeconfig' in call:
                self.assertIn('kind-testkube-samples', call)
                self.assertEqual(call[call.index('-n')+1], 'app-ci')
        self.assert_application_version(calls, 'ci-42')
        upgrades = [call for call in calls if call[0] == 'helm' and 'upgrade' in call]
        application = [call for call in upgrades if 'frontend' in call]
        self.assertTrue(application)
        for call in application:
            self.assertIn('image=ghcr.io/example/project/frontend:ci-42@sha256:'+'a'*64, call)
        self.assertFalse(any('namespace.json' in argument for call in calls for argument in call))
        self.assertFalse(any('app-prod' in call for call in calls))

    def test_local_up_keeps_kind_loading_and_local_image_tags(self):
        result = self.run_platform('up', PLATFORM_ENVIRONMENT='local', ALLOW_LOCAL='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.trace()
        self.assertTrue(any(call[:3] == ['kind', 'load', 'docker-image'] for call in calls))
        self.assertFalse(any(call[:2] == ['docker', 'push'] for call in calls))
        for call in calls:
            if call[0] in ('kubectl', 'helm') and '--kubeconfig' in call:
                self.assertIn('kind-disposable', call)
                self.assertEqual(call[call.index('-n')+1], 'local')
        self.assertTrue(any(argument.startswith('image=sample:') for call in calls for argument in call))
        self.assert_application_version(calls, (self.root / '.platform/built-tag').read_text().strip())

    def test_up_and_down_refuse_existing_cluster_before_any_tool_call(self):
        for command in ['up', 'down']:
            with self.subTest(command=command):
                result = self.run_platform(command, CONFIRM='testkube-samples')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.trace(), [])

    def test_private_package_stops_before_database_or_application_mutations(self):
        result = self.run_platform('ci-up', PRIVATE_IMAGE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('public', result.stderr)
        calls = self.trace()
        self.assertFalse(any(call[0] == 'helm' and 'upgrade' in call for call in calls))
        self.assertFalse(any(call[0] == 'kubectl' and ('apply' in call or 'create' in call) for call in calls))

    def test_ci_reset_removes_releases_pvc_and_secret_only_in_ci(self):
        result = self.run_platform('ci-reset')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.trace()
        self.assertEqual([call[call.index('uninstall')+1] for call in calls if 'uninstall' in call], ['frontend', 'db'])
        self.assertTrue(any('delete' in call and 'pvc' in call and 'data-db-0' in call for call in calls))
        self.assertTrue(any('delete' in call and 'secret' in call and 'database' in call for call in calls))
        for call in calls:
            self.assertEqual(call[call.index('-n')+1], 'app-ci')
        before = list(calls)
        result = self.run_platform('ci-reset', PLATFORM_ENVIRONMENT='app-dev')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.trace())

    def test_promotion_retags_without_building_or_deleting(self):
        result = self.run_platform('promote', PLATFORM_ENVIRONMENT='app-dev')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.trace()
        self.assertTrue(any(call[:2] == ['docker', 'pull'] and call[-1].endswith(':ci-latest') for call in calls))
        self.assertTrue(any(call[:2] == ['docker', 'push'] and call[-1].endswith(':dev-latest') for call in calls))
        self.assertFalse(any('build' in call or 'uninstall' in call or 'delete' in call or call[0]=='kind' for call in calls))
        self.assertTrue(any('image=ghcr.io/example/project/frontend:dev-latest@sha256:'+'a'*64 in call for call in calls))
        self.assert_application_version(calls, 'ci-42')
        for call in calls:
            if call[0] in ('kubectl', 'helm') and '--kubeconfig' in call:
                self.assertEqual(call[call.index('-n')+1], 'app-dev')

    def test_unpassed_or_wrong_source_images_cannot_be_promoted(self):
        for flag in ['UNTESTED', 'WRONG_TREE']:
            with self.subTest(flag=flag):
                result = self.run_platform('promote', PLATFORM_ENVIRONMENT='app-dev', **{flag:'1'})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] in (['docker','tag'], ['docker','push']) or 'upgrade' in call for call in self.trace()))

    def test_local_tests_refuse_workflow_or_shared_environment(self):
        for values in [dict(CI='true', PLATFORM_ENVIRONMENT='local'), dict(CI='', PLATFORM_ENVIRONMENT='app-ci')]:
            result = subprocess.run(['bash', str(TOOLS/'scripts/local-tests.sh')], env=dict(self.env, **values), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.trace(), [])

    def test_local_tests_run_acceptance_in_order(self):
        for tool in ['make', 'npm', 'npx']:
            path = self.root / 'bin' / tool
            path.write_text(MOCK)
            path.chmod(0o755)
        result = subprocess.run(['bash', str(TOOLS/'scripts/local-tests.sh')], env=dict(self.env, CI='', PLATFORM_ENVIRONMENT='local'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace(), [
            ['make', 'doctor'], ['npm', 'ci'], ['npx', 'cypress', 'install'],
            ['make', 'test'], ['make', 'chart-test'], ['make', 'up'],
            ['make', 'helm-test'], ['make', 'resilience'], ['make', 'browser-ci'],
        ])

    def test_production_deploy_records_timestamp_version_and_keeps_digest(self):
        self.config['environments']['app-prod'] = dict(self.config['environments']['app-ci'], namespace='app-prod')
        (self.root / 'platform.json').write_text(json.dumps(self.config))
        tag = 'prod-20261005T071920Z'
        images = self.root / '.platform/images'
        images.mkdir()
        reference = 'ghcr.io/example/project/frontend:' + tag + '@sha256:' + 'a' * 64
        (images / 'frontend').write_text(reference)
        source = (TOOLS / 'scripts/platform.sh').read_text()
        function = source[source.index('deploy() {', source.index('\ndeploy() {')):source.index('\nFORWARD_PIDS=')]
        script = 'source "' + str(TOOLS / 'scripts/common.sh') + '"\nlegacy_guard() { :; }\n' + function + '\nTAG=' + tag + '\ndeploy'
        result = subprocess.run(['bash', '-eu', '-c', script], env=dict(self.env, PLATFORM_ENVIRONMENT='app-prod'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_application_version(self.trace(), tag)
        self.assertTrue(any('image=' + reference in call for call in self.trace()))
