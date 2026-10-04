"""Verify administrative provisioning commands without contacting Kubernetes."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]


class ProvisionTests(unittest.TestCase):
    def test_explicit_context_and_repeated_apply_without_deleting_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            credential = root / 'admin config'
            credential.write_text('fixture')
            mock = root / 'kubectl'
            mock.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                            'with open(os.environ["TRACE"], "a") as log: log.write(json.dumps(sys.argv[1:])+"\\n")\n')
            mock.chmod(0o755)
            env = dict(os.environ, KUBECONFIG=str(credential), TRACE=str(root / 'trace'),
                       PATH=str(root)+os.pathsep+os.environ['PATH'])
            for _ in range(2):
                subprocess.run(['bash', str(TOOLS / 'scripts/provision-cluster.sh')], env=env, check=True)
            calls = [json.loads(line) for line in (root / 'trace').read_text().splitlines()]
            prefix = ['--kubeconfig', str(credential), '--context', 'kind-testkube-samples']
            expected = [
                prefix + ['apply', '-f', str(TOOLS / 'defaults/namespaces.yaml')],
                prefix + ['-n', 'app-ci', 'apply', '-f', str(TOOLS / 'defaults/ci-access.yaml')],
                prefix + ['-n', 'app-dev', 'apply', '-f', str(TOOLS / 'defaults/development-access.yaml')],
                prefix + ['-n', 'app-prod', 'apply', '-f', str(TOOLS / 'defaults/production-access.yaml')],
                prefix + ['get', 'namespaces', 'app-ci', 'app-dev', 'app-prod'],
            ]
            self.assertEqual(calls, expected * 2)

    def test_missing_credential_stops_before_kubectl(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, KUBECONFIG=str(Path(temporary) / 'missing'))
            result = subprocess.run(['bash', str(TOOLS / 'scripts/provision-cluster.sh')], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('existing file', result.stderr)
