import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('production', Path(__file__).resolve().parents[1]/'scripts/production-release.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
SOURCE = 'a'*40
BASE = 'b'*40
REPO = 'example/app'
CONFIG = {'applications': {'api': {}, 'web': {}}, 'environments': {
    'app-dev': {'imagePrefix': 'ghcr.io/example/app'}, 'app-prod': {'imagePrefix': 'ghcr.io/example/app'}},
    'productionRelease': {'initialBaseline': BASE}}
TAG = 'prod-20261005T140000Z'
IMAGES = {app: {'repository': 'ghcr.io/example/app/'+app, 'digest': 'sha256:'+'c'*64} for app in ('api','web')}
MANIFEST = dict(schemaVersion=1, repository=REPO, tag=TAG, sourceCommit=SOURCE, runId='12', previousSourceCommit=BASE, images=IMAGES)

class ProductionTests(unittest.TestCase):
    def test_timestamp_is_stable_and_utc(self):
        self.assertEqual(b.release_tag('2026-10-05T16:00:00+02:00'), TAG)

    def test_rejects_incomplete_or_wrong_registry_snapshot(self):
        b.validate(MANIFEST, CONFIG, REPO, SOURCE, '12')
        for invalid in [dict(MANIFEST, images={}), dict(MANIFEST, sourceCommit=BASE), dict(MANIFEST, runId='13')]:
            with self.assertRaises(ValueError): b.validate(invalid, CONFIG, REPO, SOURCE, '12')
        bad = json.loads(json.dumps(MANIFEST)); bad['images']['api']['repository']='ghcr.io/unrelated/image'
        with self.assertRaises(ValueError): b.validate(bad, CONFIG, REPO, SOURCE, '12')

    def test_older_retries_blocked_even_if_new_release_is_draft(self):
        with self.assertRaisesRegex(ValueError, 'newer'):
            b.assert_current([{'tag_name':'prod-20261005T150000Z', 'draft':True}], TAG)

    def test_notes_are_commit_delta_and_prs_deduplicated(self):
        merged = {'number':1,'title':'Add secrets','html_url':'https://github.com/example/app/pull/1','merged_at':'date','merge_commit_sha':SOURCE,'base':{'ref':'main'}}
        unrelated = dict(merged,number=2,merge_commit_sha=BASE)
        with patch.object(b,'run',side_effect=['',SOURCE+'\n'+'d'*40]) as run, patch.object(b,'pages',return_value=[merged,unrelated]):
            body=b.notes(REPO,BASE,SOURCE,IMAGES)
        self.assertEqual(body.count('Add secrets'),1)
        self.assertNotIn('#2',body)
        self.assertIn(BASE+'...'+SOURCE,body)
        self.assertEqual(run.call_args_list[1].args, ('git','rev-list',BASE+'..'+SOURCE))

    def test_snapshot_rejects_mixed_builds_and_wrong_source(self):
        for mismatch in ('build','tree'):
            def command(*args):
                if args[:2]==('git','rev-parse'): return 'tree'
                if args[:3]==('docker','image','inspect'):
                    web='web:' in args[3]
                    labels={'io.platform.source-tree':'wrong' if web and mismatch=='tree' else 'tree', 'io.platform.ci-build':'ci-2' if web and mismatch=='build' else 'ci-1'}
                    return json.dumps([{'Id':'image-id','Config':{'Labels':labels},'RepoDigests':[args[3].split(':')[0]+'@sha256:'+'c'*64]}])
                return ''
            with patch.object(b,'run',side_effect=command), self.assertRaises(ValueError): b.snapshot(CONFIG,SOURCE)

    def test_publish_saves_snapshot_before_aliases_and_exposes_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory); calls=[]
            def command(*args):
                calls.append(args)
                return SOURCE if args[:2]==('git','rev-parse') else ''
            def api(path):
                if '/actions/runs/' in path: return dict(head_sha=SOURCE,head_branch='main',event='workflow_dispatch',created_at='2026-10-05T14:00:00Z')
                return {'workflow_runs':[{'head_sha':SOURCE,'conclusion':'success'}]}
            with patch.object(b,'api',side_effect=api),patch.object(b,'releases',return_value=[]),patch.object(b,'snapshot',return_value=IMAGES),patch.object(b,'notes',return_value='PR notes'),patch.object(b,'run',side_effect=command),patch.dict(os.environ,{'GITHUB_OUTPUT':str(state/'output'),'GITHUB_STEP_SUMMARY':str(state/'summary')}):
                b.publish(CONFIG,REPO,SOURCE,'12',state)
            upload=next(i for i,c in enumerate(calls) if c[:3]==('gh','release','upload'))
            tag=next(i for i,c in enumerate(calls) if c[:2]==('docker','tag'))
            self.assertLess(upload,tag)
            self.assertEqual(json.loads((state/'release.json').read_text()),MANIFEST)
            self.assertIn('manifest_sha256=',(state/'output').read_text())
            self.assertFalse(any('build' in c or 'kubectl' in c or 'helm' in c for c in calls))

    def test_published_retry_reuses_manifest_without_retagging(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            def download(*args): (state/'release.json').write_text(json.dumps(MANIFEST)); return MANIFEST
            release={'tag_name':TAG,'draft':False,'assets':[{'name':'release.json'}]}
            metadata=dict(head_sha=SOURCE,head_branch='main',event='workflow_dispatch',created_at='2026-10-05T14:00:00Z')
            with patch.object(b,'api',return_value=metadata),patch.object(b,'releases',return_value=[release]),patch.object(b,'download_manifest',side_effect=download),patch.object(b,'snapshot',side_effect=AssertionError('moving tag read')),patch.object(b,'run',side_effect=lambda *args: '' if args[:2]==('git','ls-remote') else SOURCE) as run,patch.dict(os.environ,{'GITHUB_OUTPUT':str(state/'output'),'GITHUB_STEP_SUMMARY':str(state/'summary')}):
                b.publish(CONFIG,REPO,SOURCE,'12',state)
            self.assertFalse(any(c.args[0]=='docker' for c in run.call_args_list))

    def test_prepare_rejects_changed_asset_before_writing_deployment_images(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            def download(*args): (state/'release.json').write_text(json.dumps(MANIFEST)); return MANIFEST
            with patch.object(b,'releases',return_value=[{'tag_name':TAG,'draft':False}]),patch.object(b,'download_manifest',side_effect=download),patch.dict(os.environ,{'PRODUCTION_TAG':TAG,'PRODUCTION_MANIFEST_SHA256':'wrong'}),self.assertRaisesRegex(ValueError,'changed'):
                b.prepare(CONFIG,REPO,SOURCE,'12',state)

    def test_prepare_writes_exact_images_without_resolving_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'snapshot';state.mkdir()
            def download(*args): (state/'release.json').write_text(json.dumps(MANIFEST)); return MANIFEST
            checksum=b.hashlib.sha256(json.dumps(MANIFEST).encode()).hexdigest()
            old=os.getcwd()
            try:
                os.chdir(root)
                with patch.object(b,'releases',return_value=[{'tag_name':TAG,'draft':False}]),patch.object(b,'download_manifest',side_effect=download),patch.object(b,'run',return_value=SOURCE) as run,patch.dict(os.environ,{'PRODUCTION_TAG':TAG,'PRODUCTION_MANIFEST_SHA256':checksum}):
                    b.prepare(CONFIG,REPO,SOURCE,'12',state)
                self.assertEqual((root/'.platform/images/api').read_text().strip(),IMAGES['api']['repository']+':'+TAG+'@'+IMAGES['api']['digest'])
                self.assertFalse(any(c.args[0]=='docker' for c in run.call_args_list))
            finally:
                os.chdir(old)

    def test_failed_development_image_is_rejected(self):
        def command(*args):
            if args[:2]==('git','rev-parse'): return 'tree'
            if args[:3]==('docker','image','inspect'):
                return json.dumps([{'Id':'passed' if args[3].endswith(':dev-passed') else 'failed'}])
            return ''
        with patch.object(b,'run',side_effect=command),self.assertRaisesRegex(ValueError,'not passed'):
            b.snapshot(CONFIG,SOURCE)

    def test_draft_retry_uses_saved_images(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            def download(*args): (state/'release.json').write_text(json.dumps(MANIFEST)); return MANIFEST
            release={'tag_name':TAG,'draft':True,'assets':[{'name':'release.json'}]}
            metadata=dict(head_sha=SOURCE,head_branch='main',event='workflow_dispatch',created_at='2026-10-05T14:00:00Z')
            with patch.object(b,'api',return_value=metadata),patch.object(b,'releases',return_value=[release]),patch.object(b,'download_manifest',side_effect=download),patch.object(b,'snapshot',side_effect=AssertionError('moving tag read')),patch.object(b,'run',side_effect=lambda *args: SOURCE if args[:2]==('git','rev-parse') else '') as run,patch.dict(os.environ,{'GITHUB_OUTPUT':str(state/'output'),'GITHUB_STEP_SUMMARY':str(state/'summary')}):
                b.publish(CONFIG,REPO,SOURCE,'12',state)
            pulls=[c.args[-1] for c in run.call_args_list if c.args[:2]==('docker','pull')]
            self.assertEqual(pulls,[i['repository']+'@'+i['digest'] for i in IMAGES.values()])

    def test_release_requires_successful_main_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata=dict(head_sha=SOURCE,head_branch='main',event='workflow_dispatch',created_at='2026-10-05T14:00:00Z')
            with patch.object(b,'api',side_effect=[metadata,{'workflow_runs':[]}]),patch.object(b,'releases',return_value=[]),patch.object(b,'run',return_value=''),patch.object(b,'snapshot',side_effect=AssertionError('should not inspect images')),self.assertRaisesRegex(ValueError,'successful development'):
                b.publish(CONFIG,REPO,SOURCE,'12',Path(directory))

    def test_production_shell_uses_digest_and_preserves_database(self):
        source=(Path(__file__).resolve().parents[1]/'scripts/platform.sh').read_text()
        function=source[source.index('production_deploy() {'):source.index('\ndeploy() {')]
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'images').mkdir()
            (state/'production-tag').write_text(TAG)
            (state/'images/api').write_text(IMAGES['api']['repository']+':'+TAG+'@'+IMAGES['api']['digest'])
            trace=state/'trace'
            stub='''python3() { echo validate >> "$TRACE"; }
app_image() { echo ghcr.io/example/app/api; }
docker() { printf '%s\\n' "$*" >> "$TRACE"; }
db_up() { echo db-up >> "$TRACE"; }
deploy() { echo deploy >> "$TRACE"; }
check() { echo check >> "$TRACE"; }
'''
            env=dict(os.environ,PLATFORM_ENVIRONMENT='app-prod',NAMESPACE='app-prod',SERVICE='all',STATE=str(state),APPS='api',TOOLS_ROOT='/fixture',TRACE=str(trace))
            result=b.subprocess.run(['bash','-eu','-c',stub+function+'\nproduction_deploy'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            calls=trace.read_text().splitlines()
            self.assertEqual(calls[0],'validate')
            self.assertIn('pull '+IMAGES['api']['repository']+'@'+IMAGES['api']['digest'],calls)
            self.assertEqual(calls[-3:],['db-up','deploy','check'])
            self.assertFalse(any('latest' in c or 'delete' in c or 'build' in c for c in calls))
            result=b.subprocess.run(['bash','-eu','-c',stub+function+'\nproduction_deploy'],env=dict(env,NAMESPACE='app-ci'),capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(trace.read_text().splitlines(),calls)
