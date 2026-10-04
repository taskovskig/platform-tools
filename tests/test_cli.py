"""Tests for the installed release CLI; no network or cluster."""
import hashlib, importlib.util, io, json, os, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from platform_tools import cli as b

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir()
        (self.source/'VERSION').write_text('v0.1.0\n')
        (self.source/'scripts').mkdir()
        (self.source/'scripts/entry.sh').write_text('echo verified\n')
        files={p.relative_to(self.source).as_posix():b.sha(p) for p in self.source.rglob('*') if p.is_file()}
        (self.source/'distribution.json').write_text(json.dumps({'files':files}))
        self.lock={'schemaVersion':1,'repository':'example/platform','tag':'v0.1.0','manifestSha256':b.sha(self.source/'distribution.json')}
        self.archive=self.root/'source.tgz'
        with tarfile.open(self.archive,'w:gz') as t: t.add(self.source,arcname='platform-commit')
    def test_download_tag_verify_and_cached_reuse(self):
        data=self.archive.read_bytes()
        with patch.object(b.urllib.request,'urlopen',return_value=io.BytesIO(data)) as fetch:
            cache=b.obtain(self.root,self.lock)
            self.assertTrue((cache/'scripts/entry.sh').is_file())
            self.assertIn('/tarball/refs/tags/v0.1.0',fetch.call_args.args[0].full_url)
        with patch.object(b.urllib.request,'urlopen',side_effect=AssertionError('cache should avoid network')):
            self.assertEqual(cache,b.obtain(self.root,self.lock))
    def test_tampered_archive_is_not_cached(self):
        (self.source/'scripts/entry.sh').write_text('echo tampered')
        with tarfile.open(self.archive,'w:gz') as t: t.add(self.source,arcname='platform-commit')
        with patch.object(b.urllib.request,'urlopen',return_value=io.BytesIO(self.archive.read_bytes())):
            with self.assertRaisesRegex(ValueError,'checksum mismatch'): b.obtain(self.root,self.lock)
        self.assertFalse((self.root/'.platform/tools'/self.lock['manifestSha256']).exists())
    def test_cache_tampering_is_rejected(self):
        with patch.object(b.urllib.request,'urlopen',return_value=io.BytesIO(self.archive.read_bytes())): cache=b.obtain(self.root,self.lock)
        (cache/'VERSION').write_text('v0.9.9')
        with self.assertRaises(ValueError): b.obtain(self.root,self.lock)
    def test_extra_file_is_rejected(self):
        (self.source/'injected.py').write_text('pass')
        with self.assertRaisesRegex(ValueError,'Unexpected files'): b.verify(self.source,self.lock)
    def test_tag_version_mismatch(self):
        with self.assertRaisesRegex(ValueError,'VERSION'): b.verify(self.source,dict(self.lock,tag='v0.2.0'))
    def test_unsafe_archive_paths_and_links(self):
        for name,kind in [('root/../../escape',tarfile.REGTYPE),('root/link',tarfile.SYMTYPE)]:
            with self.subTest(name=name):
                with tarfile.open(self.archive,'w:gz') as t:
                    item=tarfile.TarInfo(name);item.type=kind;item.linkname='/tmp/escape';t.addfile(item)
                with self.assertRaises(ValueError): b.unpack(self.archive,self.root/'out')
    def test_development_workflow_must_use_the_same_platform_tag(self):
        (self.root/'platform.lock.json').write_text(json.dumps(self.lock))
        (self.root/'.github/workflows').mkdir(parents=True)
        (self.root/'.github/workflows/platform.yaml').write_text(
            'uses: example/platform/.github/workflows/delivery.yaml@v0.1.0\n'
            'uses: example/platform/.github/workflows/development.yaml@v9.9.9\n')
        with patch.object(b, 'find_project', return_value=self.root):
            with self.assertRaisesRegex(ValueError, 'All platform workflow references'):
                b.main(['fetch'])

    def test_ci_rejects_local_override(self):
        (self.root/'platform.lock.json').write_text(json.dumps(self.lock))
        (self.root/'.github/workflows').mkdir(parents=True)
        (self.root/'.github/workflows/platform.yaml').write_text('example/platform/.github/workflows/delivery.yaml@v0.1.0')
        with patch.object(b,'find_project',return_value=self.root),patch.dict(os.environ,{'CI':'true','PLATFORM_TOOLS_DIR':str(self.source)}):
            with self.assertRaisesRegex(ValueError,'forbidden'): b.main(['fetch'])
    def test_workflow_pin_must_match(self):
        (self.root/'platform.lock.json').write_text(json.dumps(self.lock))
        (self.root/'.github/workflows').mkdir(parents=True)
        (self.root/'.github/workflows/platform.yaml').write_text('example/platform/.github/workflows/delivery.yaml@v9.0.0')
        with patch.object(b,'find_project',return_value=self.root):
            with self.assertRaisesRegex(ValueError,'differ'): b.main(['fetch'])

if __name__=='__main__': unittest.main()

class CliTests(unittest.TestCase):
    def test_discovery_from_nested_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root/'platform.lock.json').write_text('{}')
            nested = root/'apps'/'api'
            nested.mkdir(parents=True)
            self.assertEqual(b.find_project(nested), root)

    def test_incompatible_api_fails_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'platform.lock.json').write_text(json.dumps({'cliApiVersion': 999}))
            with patch.object(b, 'obtain', side_effect=AssertionError('must not download')):
                with self.assertRaisesRegex(ValueError, 'Unsupported CLI API'):
                    b.main(['--project', str(root), 'fetch'])

    def test_dispatch_uses_application_root_not_install_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            lock = {'schemaVersion': 1, 'cliApiVersion': 1, 'repository': 'example/platform', 'tag': 'v0.5.0', 'manifestSha256': 'a'*64}
            (root/'platform.lock.json').write_text(json.dumps(lock))
            (root/'.github/workflows').mkdir(parents=True)
            (root/'.github/workflows/platform.yaml').write_text('example/platform/.github/workflows/delivery.yaml@v0.5.0')
            with patch.dict(os.environ, {}, clear=True), patch.object(b, 'obtain', return_value=Path('/verified/platform')), patch.object(b.os, 'execvpe') as execute:
                b.main(['--project', str(root), 'local-tests'])
            self.assertEqual(execute.call_args.args[1], ['bash', '/verified/platform/scripts/entry.sh', 'local-tests'])
            self.assertEqual(execute.call_args.args[2]['PROJECT_ROOT'], str(root))
