import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_chart", TOOLS / "scripts/prepare-chart.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ChartMetadataTests(unittest.TestCase):
    def test_private_copies_preserve_source_and_other_release_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {str(p.relative_to(TOOLS / 'helm')): p.read_bytes() for p in (TOOLS / 'helm').rglob('*') if p.is_file()}
            for name, version in [('api', 'ci-42'), ('web', 'prod-20261005T071920Z')]:
                module.prepare(TOOLS / 'helm', root / name, version)
                for path, content in original.items():
                    if path != 'Chart.yaml':
                        self.assertEqual((root / name / path).read_bytes(), content)
                self.assertIn('appVersion: "' + version + '"', (root / name / 'Chart.yaml').read_text())
            self.assertIn('appVersion: "ci-42"', (root / 'api/Chart.yaml').read_text())
            for path, content in original.items():
                self.assertEqual((TOOLS / 'helm' / path).read_bytes(), content)

    def test_invalid_version_and_shared_chart_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'chart'
            for version in ['', 'dev-latest\nappVersion: bad', 'a' * 129]:
                with self.assertRaises(ValueError):
                    module.prepare(TOOLS / 'helm', destination, version)
                self.assertFalse(destination.exists())
            for path in [TOOLS / 'helm', TOOLS / 'helm/nested']:
                with self.assertRaises(ValueError):
                    module.prepare(TOOLS / 'helm', path, 'ci-42')

    def test_existing_release_copy_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'chart'
            module.prepare(TOOLS / 'helm', destination, 'ci-42')
            with self.assertRaises(FileExistsError):
                module.prepare(TOOLS / 'helm', destination, 'ci-43')
            self.assertIn('appVersion: "ci-42"', (destination / 'Chart.yaml').read_text())
