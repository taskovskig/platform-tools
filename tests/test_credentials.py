import json, os, subprocess, tempfile, unittest
from pathlib import Path

class CredentialTests(unittest.TestCase):
    def test_secret_contains_matching_values_without_shell_or_uri_interpretation(self):
        source=(Path(__file__).resolve().parents[1]/'scripts/platform.sh').read_text()
        function=source[source.index('credentials() {'):source.index('\nlegacy_guard()')]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'secret.json'
            env=dict(os.environ, PLATFORM_ENVIRONMENT='app-ci', DB_NAME='ci-api-db', DB_USER='ci-api-user', DB_PASSWORD="a'\n$(touch bad):@", DB_SECRET='database', NAMESPACE='app-ci', DB_PVC='data-db-0', OUTPUT=str(output))
            stub='''k() {
              if [ "$1" = get ] && [ "$2" = serviceaccount ]; then return 0; fi
              if [ "$1" = get ]; then return 1; fi
              if [ "$1" = create ]; then cat > "$OUTPUT"; return; fi
              return 1
            }
            '''
            result=subprocess.run(['bash','-eu','-c',stub+function+'\ncredentials'],env=env,cwd=directory,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            secret=json.loads(output.read_text())
            self.assertEqual(secret['stringData'],{'POSTGRES_DB':env['DB_NAME'],'POSTGRES_USER':env['DB_USER'],'POSTGRES_PASSWORD':env['DB_PASSWORD']})
            self.assertEqual(secret['metadata'],{'name':'database','namespace':'app-ci'})
            self.assertEqual(result.stdout,'')
            self.assertFalse((Path(directory)/'bad').exists())
