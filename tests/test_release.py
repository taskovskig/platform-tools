import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/release.py'


class ReleaseTests(unittest.TestCase):
    def test_ignored_credentials_are_not_part_of_the_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'scripts').mkdir()
            shutil.copy(SCRIPT, root / 'scripts/release.py')
            (root / 'VERSION').write_text('v0.3.0\n')
            (root / '.gitignore').write_text('.kube/\n')
            (root / '.kube').mkdir()
            (root / '.kube/config').write_text('sensitive fixture')
            subprocess.run(['python3', str(root / 'scripts/release.py')], check=True, stdout=subprocess.DEVNULL)
            manifest = json.loads((root / 'distribution.json').read_text())['files']
            self.assertIn('scripts/release.py', manifest)
            self.assertNotIn('.kube/config', manifest)
            subprocess.run(['git', '-C', str(root), 'add', '-f', '.kube/config'], check=True)
            result = subprocess.run(['python3', str(root / 'scripts/release.py')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Kubeconfig directories must not be packaged', result.stderr)
