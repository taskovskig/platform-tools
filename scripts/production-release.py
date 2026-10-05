#!/usr/bin/env python3
"""Publish a retryable production snapshot, or validate it for approved deployment."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TAG = re.compile(r'prod-\d{8}T\d{6}Z')
SHA = re.compile(r'[a-f0-9]{40}')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path):
    return json.loads(run('gh', 'api', path))


def pages(path):
    return [item for page in json.loads(run('gh', 'api', '--paginate', '--slurp', path)) for item in page]


def releases(repo):
    return [r for r in pages(f'repos/{repo}/releases?per_page=100') if TAG.fullmatch(r['tag_name']) and not r['prerelease']]


def assert_current(items, tag):
    if any(r['tag_name'] > tag for r in items):
        raise ValueError('A newer production release exists. Refuse to republish or deploy an older run.')


def release_tag(created_at):
    return 'prod-' + datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00')).astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def validate(manifest, config, repo, source, run_id):
    if manifest.get('schemaVersion') != 1 or manifest.get('repository') != repo:
        raise ValueError('Invalid release manifest repository/schema')
    if manifest.get('sourceCommit') != source or not SHA.fullmatch(source) or manifest.get('runId') != str(run_id):
        raise ValueError('Release source/run identity mismatch')
    if not TAG.fullmatch(manifest.get('tag', '')):
        raise ValueError('Invalid production tag')
    images = manifest.get('images', {})
    if set(images) != set(config['applications']):
        raise ValueError('Release must contain every application exactly once')
    prefix = config['environments']['app-prod']['imagePrefix']
    if prefix != config['environments']['app-dev']['imagePrefix']:
        raise ValueError('Development and production must share the registry image prefix')
    for app, image in images.items():
        if image.get('repository') != prefix + '/' + app or not DIGEST.fullmatch(image.get('digest', '')):
            raise ValueError('Invalid release image reference')


def download_manifest(repo, tag, directory):
    directory.mkdir(parents=True, exist_ok=True)
    run('gh', 'release', 'download', tag, '--repo', repo, '--pattern', 'release.json', '--dir', str(directory), '--clobber')
    return json.loads((directory / 'release.json').read_text())


def notes(repo, baseline, source, images):
    # Git ancestry, not PR dates: squash/merge/rebase commits define the delta.
    run('git', 'merge-base', '--is-ancestor', baseline, source)
    commits = run('git', 'rev-list', f'{baseline}..{source}').splitlines()
    pull_requests = {}
    for commit in commits:
        for pr in pages(f'repos/{repo}/commits/{commit}/pulls?per_page=100'):
            if pr.get('merged_at') and pr['base']['ref'] == 'main' and pr.get('merge_commit_sha') in commits:
                pull_requests[pr['number']] = pr
    lines = ['## Changes', '']
    for number, pr in sorted(pull_requests.items()):
        title = ' '.join(pr['title'].split()).replace('[', '\\[').replace(']', '\\]')
        lines.append(f'- {title} ([#{number}]({pr["html_url"]}))')
    if not pull_requests:
        lines.append('No merged pull requests in this source range.')
    lines += ['', f'[Full source delta](https://github.com/{repo}/compare/{baseline}...{source})', '', '## Images', '']
    lines += [f'- `{name}`: `{image["repository"]}@{image["digest"]}`' for name, image in sorted(images.items())]
    lines += ['', 'Publication does not imply production deployment. Approval and deployment status are tracked by the app-prod environment.', '']
    return '\n'.join(lines)


def snapshot(config, source):
    expected_tree = run('git', 'rev-parse', source + '^{tree}')
    images = {}
    build = None
    prefix = config['environments']['app-dev']['imagePrefix']
    for app in config['applications']:
        repository = prefix + '/' + app
        run('docker', 'pull', repository + ':dev-latest')
        data = json.loads(run('docker', 'image', 'inspect', repository + ':dev-latest'))[0]
        run('docker', 'pull', repository + ':dev-passed')
        passed = json.loads(run('docker', 'image', 'inspect', repository + ':dev-passed'))[0]
        if not data.get('Id') or data['Id'] != passed.get('Id'):
            raise ValueError(f'{app}: dev-latest has not passed development deployment checks')
        labels = data['Config'].get('Labels') or {}
        if labels.get('io.platform.source-tree') != expected_tree:
            raise ValueError(f'{app}: dev-latest does not match the selected main commit')
        candidate_build = labels.get('io.platform.ci-build', '')
        if not re.fullmatch(r'ci-[1-9][0-9]*', candidate_build) or (build and candidate_build != build):
            raise ValueError('Development images must come from the same CI build')
        build = candidate_build
        refs = [ref for ref in data.get('RepoDigests', []) if ref.startswith(repository + '@')]
        if len(refs) != 1 or not DIGEST.fullmatch(refs[0].split('@')[1]):
            raise ValueError(f'{app}: registry digest unavailable or ambiguous')
        images[app] = {'repository': repository, 'digest': refs[0].split('@')[1]}
    return images


def publish(config, repo, source, run_id, state):
    metadata = api(f'repos/{repo}/actions/runs/{run_id}')
    if metadata['head_sha'] != source or metadata['head_branch'] != 'main' or metadata['event'] != 'workflow_dispatch':
        raise ValueError('Production release must be manually dispatched from main')
    tag = release_tag(metadata['created_at'])
    items = releases(repo)
    assert_current(items, tag)
    existing = next((r for r in items if r['tag_name'] == tag), None)
    remote_tag = run('git', 'ls-remote', '--tags', 'origin', 'refs/tags/' + tag)
    if remote_tag:
        if not existing:
            raise ValueError('Production Git tag already exists without its release record')
        run('git', 'fetch', 'origin', 'tag', tag)
        if run('git', 'rev-parse', tag + '^{commit}') != source:
            raise ValueError('Existing production tag points to a different source commit')
    if existing and any(a['name'] == 'release.json' for a in existing['assets']):
        manifest = download_manifest(repo, tag, state)
        validate(manifest, config, repo, source, run_id)
    else:
        if existing and (existing['target_commitish'] != source or not existing['draft'] or f'Production workflow run: {run_id}' not in (existing.get('body') or '')):
            raise ValueError('Release tag collision or incomplete published release')
        runs = api(f'repos/{repo}/actions/workflows/platform.yaml/runs?branch=main&event=push&head_sha={source}&status=success&per_page=100')['workflow_runs']
        if not any(r['head_sha'] == source and r['conclusion'] == 'success' for r in runs):
            raise ValueError('Selected main commit needs a successful development delivery run')
        images = snapshot(config, source)
        previous = sorted((r for r in items if not r['draft'] and r['tag_name'] != tag), key=lambda r: r['tag_name'])
        if previous:
            prior = download_manifest(repo, previous[-1]['tag_name'], state / 'previous')
            baseline = prior['sourceCommit']
        else:
            baseline = config.get('productionRelease', {}).get('initialBaseline', '')
        if not SHA.fullmatch(baseline):
            raise ValueError('First release requires productionRelease.initialBaseline (full commit SHA)')
        if baseline == source:
            raise ValueError('No source changes since the previous production release')
        body = notes(repo, baseline, source, images) + f'\nProduction workflow run: {run_id}\n'
        manifest = {'schemaVersion': 1, 'repository': repo, 'tag': tag, 'sourceCommit': source,
                    'runId': str(run_id), 'previousSourceCommit': baseline, 'images': images}
        validate(manifest, config, repo, source, run_id)
        (state / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (state / 'notes.md').write_text(body)
        if not existing:
            run('gh', 'release', 'create', tag, '--repo', repo, '--target', source, '--title', tag,
                '--notes-file', str(state / 'notes.md'), '--draft')
        run('gh', 'release', 'upload', tag, str(state / 'release.json'), '--repo', repo)
    if not existing or existing['draft']:
        # The saved draft snapshot survives retries; never resolve moving tags again.
        for image in manifest['images'].values():
            ref = image['repository'] + '@' + image['digest']
            run('docker', 'pull', ref)
            for alias in (tag, 'latest'):
                target = image['repository'] + ':' + alias
                run('docker', 'tag', ref, target)
                run('docker', 'push', target)
        run('gh', 'release', 'edit', tag, '--repo', repo, '--draft=false', '--latest')
    # Publishing creates the tag; check its commit, never move an existing tag.
    run('git', 'fetch', 'origin', 'tag', tag)
    if run('git', 'rev-parse', tag + '^{commit}') != source:
        raise ValueError('Production Git tag does not identify the released source')
    checksum = hashlib.sha256((state / 'release.json').read_bytes()).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write(f'tag={tag}\nsource={source}\nmanifest_sha256={checksum}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
        out.write(f'Published [{tag}](https://github.com/{repo}/releases/tag/{tag}). Awaiting app-prod approval.\n')


def prepare(config, repo, source, run_id, state):
    tag = os.environ['PRODUCTION_TAG']
    if not TAG.fullmatch(tag):
        raise ValueError('Invalid production tag')
    items = releases(repo)
    assert_current(items, tag)
    release = next(r for r in items if r['tag_name'] == tag)
    if release['draft']:
        raise ValueError('Production release is not published')
    manifest = download_manifest(repo, tag, state)
    actual = hashlib.sha256((state / 'release.json').read_bytes()).hexdigest()
    if actual != os.environ['PRODUCTION_MANIFEST_SHA256']:
        raise ValueError('Release manifest changed after publication job')
    validate(manifest, config, repo, source, run_id)
    if manifest['tag'] != tag or run('git', 'rev-parse', 'HEAD') != source:
        raise ValueError('Checkout/tag does not match approved release')
    directory = Path('.platform/images')
    directory.mkdir(parents=True, exist_ok=True)
    for app, image in manifest['images'].items():
        (directory / app).write_text(image['repository'] + ':' + tag + '@' + image['digest'] + '\n')
    Path('.platform/production-tag').write_text(tag + '\n')


def main():
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Production workflow must run from main')
    os.chdir(os.environ['PROJECT_ROOT'])
    config = json.loads(Path('platform.json').read_text())
    repo, source, run_id = (os.environ[k] for k in ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID'))
    state = Path('.platform/production')
    state.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == 'publish':
        publish(config, repo, source, run_id, state)
    elif sys.argv[1] == 'prepare':
        prepare(config, repo, source, run_id, state)
    else:
        raise ValueError('Unknown production command')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        sys.exit(f'Production release failed: {error}')
