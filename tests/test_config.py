import json, subprocess, tempfile, unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/config.py'
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'file').write_text('placeholder')
        self.config={'schemaVersion':1,'cluster':'example-cluster','namespace':'example','kindConfig':'file','namespaceManifest':'file','buildContext':['file'],
          'applications':{'frontend':{'dockerfile':'file','values':'file','image':'example/frontend','port':3000,'localPort':4300}},
          'checks':[{'service':'frontend','path':'/ready','body':'ok'}],
          'database':{'release':'storage','statefulset':'storage','secret':'credentials','pvc':'data-storage-0','values':'file','serviceAccountManifest':'file','client':'frontend','outageCheck':'file','developmentUser':'user','developmentPassword':"a'$(touch unwanted)"}}
    def run_config(self):
        (self.root/'platform.json').write_text(json.dumps(self.config))
        return subprocess.run(['python3',str(SCRIPT),str(self.root)],capture_output=True,text=True)
    def test_non_sample_names_and_safe_shell_quoting(self):
        result=self.run_config();self.assertEqual(result.returncode,0,result.stderr)
        command=result.stdout+'\nprintf "%s\\n" "$CLUSTER" "$DB_PASSWORD"; app_port frontend'
        out=subprocess.check_output(['bash','-c',command],cwd=self.root,text=True)
        self.assertIn('example-cluster',out);self.assertIn("a'$(touch unwanted)",out);self.assertIn('3000',out)
        self.assertFalse((self.root/'unwanted').exists())
    def test_optional_infrastructure_uses_platform_defaults(self):
        del self.config['kindConfig']
        del self.config['namespaceManifest']
        del self.config['database']['serviceAccountManifest']
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = subprocess.check_output(['bash', '-c', result.stdout +
            '\nprintf "%s\\n" "$KIND_CONFIG" "$NAMESPACE_MANIFEST" "$DB_ACCOUNT"'], text=True)
        self.assertEqual(output.splitlines(), [str(SCRIPT.parent.parent / 'defaults/kind.yaml'), '', ''])

    def test_explicit_infrastructure_overrides_remain_supported(self):
        result = self.run_config()
        output = subprocess.check_output(['bash', '-c', result.stdout +
            '\nprintf "%s\\n" "$KIND_CONFIG" "$NAMESPACE_MANIFEST" "$DB_ACCOUNT"'], text=True)
        self.assertEqual(output.splitlines(), ['file', 'file', 'file'])

    def test_invalid_explicit_infrastructure_does_not_fall_back(self):
        for key in ('kindConfig', 'namespaceManifest'):
            with self.subTest(key=key):
                self.config[key] = 'missing'
                self.assertNotEqual(self.run_config().returncode, 0)
                self.config[key] = 'file'
        self.config['database']['serviceAccountManifest'] = '../file'
        self.assertNotEqual(self.run_config().returncode, 0)

    def test_rejects_escape_from_project(self):
        self.config['buildContext']=['../file'];self.assertNotEqual(self.run_config().returncode,0)
    def test_rejects_unknown_check_service(self):
        self.config['checks'][0]['service']='missing';self.assertNotEqual(self.run_config().returncode,0)
    def test_rejects_unknown_schema(self):
        self.config['schemaVersion']=2;self.assertNotEqual(self.run_config().returncode,0)
if __name__=='__main__':unittest.main()
