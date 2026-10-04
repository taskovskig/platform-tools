#!/usr/bin/env python3
"""Generate the integrity manifest and print the consumer lock. Run before tagging."""
import hashlib, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
files={}
for path in sorted(root.rglob('*')):
    rel=path.relative_to(root)
    if any(x in {'.git','.platform','node_modules','__pycache__','dist'} for x in rel.parts): continue
    if str(rel)=='distribution.json' or not path.is_file(): continue
    if path.is_symlink(): raise SystemExit('Distribution must not contain symlinks')
    files[rel.as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
manifest=root/'distribution.json'
manifest.write_text(json.dumps({'schemaVersion':1,'files':files},indent=2)+'\n')
print(json.dumps({'schemaVersion':1,'repository':'taskovskig/platform-tools','tag':(root/'VERSION').read_text().strip(),'manifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest()},indent=2))
