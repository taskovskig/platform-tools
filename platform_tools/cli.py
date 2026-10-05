#!/usr/bin/env python3
"""Fetch a tagged, content-locked platform package and delegate commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

from . import __version__, CLI_API_VERSION


def find_project(start):
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / 'platform.lock.json').is_file():
            return candidate
    raise ValueError('No platform.lock.json found; run inside an application repo or use --project PATH')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value:
        raise ValueError(f'Unsafe package path: {value}')
    return p

def verify(package, lock):
    manifest = package / 'distribution.json'
    if sha(manifest) != lock['manifestSha256']:
        raise ValueError('Platform manifest checksum mismatch; refuse changed tag content')
    files = json.loads(manifest.read_text())['files']
    for name, expected in files.items():
        target = package / relative(name)
        if target.is_symlink() or not target.is_file() or sha(target) != expected:
            raise ValueError(f'Platform content checksum mismatch: {name}')
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    if actual != set(files) | {'distribution.json'}:
        raise ValueError('Unexpected files in platform package')
    if (package / 'VERSION').read_text().strip() != lock['tag']:
        raise ValueError('Platform VERSION does not match pinned tag')

def unpack(archive, destination):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if sum(m.size for m in members) > 50 * 1024 * 1024:
            raise ValueError('Platform archive exceeds 50 MiB')
        roots = {PurePosixPath(m.name).parts[0] for m in members}
        if len(roots) != 1:
            raise ValueError('Expected one archive root')
        seen = set()
        for member in members:
            relative(member.name.rstrip('/'))
            parts = PurePosixPath(member.name).parts[1:]
            if not parts:
                if not member.isdir(): raise ValueError('Invalid archive root')
                continue
            path = destination.joinpath(*parts)
            if path in seen: raise ValueError('Duplicate archive member')
            seen.add(path)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, path.open('wb') as out:
                    shutil.copyfileobj(source, out)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError('Links and special files are forbidden in platform archives')

def download(lock, archive):
    endpoint = f"repos/{lock['repository']}/tarball/refs/tags/{lock['tag']}"
    url = 'https://api.github.com/' + endpoint
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'platform-bootstrap'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as out:
            shutil.copyfileobj(response, out)
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404) or not shutil.which('gh'):
            raise RuntimeError(f"Cannot download {lock['repository']} tag {lock['tag']}. Publish the tag first; for a private repository authenticate gh with read access.") from exc
        with archive.open('wb') as out:
            subprocess.run(['gh','api',endpoint], stdout=out, check=True)

def obtain(root, lock):
    cache = root / '.platform' / 'tools' / lock['manifestSha256']
    if cache.exists():
        verify(cache, lock)
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='download-', dir=cache.parent) as temp:
        temp = Path(temp)
        archive = temp / 'source.tar.gz'
        package = temp / 'package'
        package.mkdir()
        download(lock, archive)
        unpack(archive, package)
        verify(package, lock)
        try:
            package.rename(cache)
        except OSError:
            if not cache.exists(): raise
            verify(cache, lock)
    return cache

def main(argv=None):
    parser = argparse.ArgumentParser(description='Fetch verified platform releases and run application platform commands.')
    parser.add_argument('--version', action='version', version=f'platform-tools {__version__}')
    parser.add_argument('--project', type=Path, default=Path.cwd(), help='Application directory (default: discover from cwd)')
    parser.add_argument('command', nargs='*', help='fetch, version, local-tests, ci-up, promote, or another platform command')
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return
    ROOT = find_project(args.project)
    lock = json.loads((ROOT / 'platform.lock.json').read_text())
    if lock.get('cliApiVersion', 1) != CLI_API_VERSION: raise ValueError('Unsupported CLI API version; install a compatible platform-tools CLI')
    if lock.get('schemaVersion') != 1: raise ValueError('Unsupported platform lock schema')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',lock['repository']): raise ValueError('Invalid repository')
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[\w.-]+)?',lock['tag']): raise ValueError('Pin a semantic version tag, never a branch')
    if not re.fullmatch(r'[a-f0-9]{64}',lock['manifestSha256']): raise ValueError('Invalid checksum')
    # GitHub requires a literal tag in a reusable-workflow reference. Keep both pins aligned.
    workflow = (ROOT / '.github/workflows/platform.yaml').read_text()
    expected = f"{lock['repository']}/.github/workflows/delivery.yaml@{lock['tag']}"
    if expected not in workflow: raise ValueError('CI workflow tag and platform.lock.json differ')
    workflow = '\n'.join(p.read_text() for p in (ROOT / '.github/workflows').glob('*.y*ml'))
    references = re.findall(re.escape(lock['repository']) + r'/\.github/workflows/[\w.-]+@([^\s]+)', workflow)
    if any(reference != lock['tag'] for reference in references):
        raise ValueError('All platform workflow references must match platform.lock.json')
    command = args.command
    override = os.environ.get('PLATFORM_TOOLS_DIR')
    if override:
        if os.environ.get('CI'): raise ValueError('Local platform override is forbidden in CI')
        package = Path(override).resolve()
        print(f'LOCAL DEVELOPMENT OVERRIDE: {package}; release checksums bypassed', file=sys.stderr)
    else:
        package = obtain(ROOT, lock)
    print(f"Platform: {lock['repository']}@{lock['tag']} ({lock['manifestSha256'][:12]})", file=sys.stderr)
    if command == ['fetch']: return
    environment = dict(os.environ, PROJECT_ROOT=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    os.execvpe('bash',['bash',str(package/'scripts/entry.sh'),*command],environment)

def cli():
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, KeyError) as exc:
        sys.exit(f'Platform bootstrap failed: {exc}')


if __name__ == "__main__":
    cli()
