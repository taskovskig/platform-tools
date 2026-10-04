#!/usr/bin/env python3
"""Generate the integrity manifest and print the consumer lock. Run before tagging."""
import hashlib, json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
files={}
# Match the files that can enter the tag archive; do not hash ignored local kubeconfigs.
names = subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']
).decode().split('\0')
for name in sorted(set(names) - {''}):
    if name == 'distribution.json': continue
    path = root / name
    if path.is_symlink(): raise SystemExit('Distribution must not contain symlinks')
    if not path.is_file(): continue
    if '.kube' in path.relative_to(root).parts: raise SystemExit('Kubeconfig directories must not be packaged')
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest=root/'distribution.json'
manifest.write_text(json.dumps({'schemaVersion':1,'files':files},indent=2)+'\n')
print(json.dumps({'schemaVersion':1,'repository':'taskovskig/platform-tools','tag':(root/'VERSION').read_text().strip(),'manifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest()},indent=2))
