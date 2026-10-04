import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/render-infrastructure.py'


class InfrastructureTests(unittest.TestCase):
    def test_generated_resources_use_project_names_and_platform_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'infrastructure'
            subprocess.run(['python3', str(SCRIPT), str(output), 'example', 'storage', 'credentials'], check=True)
            namespace = json.loads((output / 'namespace.json').read_text())
            account = json.loads((output / 'db-serviceaccount.json').read_text())
            values = json.loads((output / 'db.values.json').read_text())
            self.assertEqual(namespace['metadata']['name'], 'example')
            self.assertEqual(namespace['metadata']['labels']['pod-security.kubernetes.io/enforce'], 'restricted')
            self.assertEqual(account['metadata'], {'name': 'storage', 'namespace': 'example'})
            self.assertFalse(account['automountServiceAccountToken'])
            self.assertEqual(values.pop('env'), [{'name': name, 'valueFrom': {'secretKeyRef': {'name': 'credentials', 'key': 'POSTGRES_DB'}}} for name in ['POSTGRES_DB', 'PGDATABASE']])
            self.assertEqual(values, {'fullnameOverride': 'storage', 'settings': {'existingSecret': 'credentials'}, 'serviceAccount': {'name': 'storage'}})
            self.assertNotIn('image', values)  # Database image version belongs to the application.
