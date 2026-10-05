# Publishing a platform tag

Run these commands from the `platform-tools` repository. The next prepared release is `v0.7.0`; use a new version for each subsequent release. Never move or overwrite a published tag.

## 1. Prepare the version

Check that you are on `main` and review the pending changes:

```sh
git branch --show-current
git status --short
```

Align these version references before publishing:

- `VERSION`: the tag, for example `v0.7.0`.
- `platform_tools/__init__.py`: `__version__`, for example `0.7.0`.
- CLI installation tags in `.github/workflows/delivery.yaml` and `.github/workflows/production.yaml`.
- Installation examples and workflow references in `PLATFORM.md`.

Confirm the proposed tag does not already exist locally or remotely. Both tag commands should print nothing; otherwise choose a new version.

```sh
release_tag=$(cat VERSION)
git tag --list "$release_tag"
git ls-remote --tags origin "refs/tags/$release_tag"
```

## 2. Validate and generate the manifest

```sh
make test
make release-manifest
```

Save the consumer lock JSON printed by the second command. It includes the tag and manifest checksum needed by application repositories. Manifest generation is required for releases, not ordinary commits. If you edit any packaged file afterward, regenerate the manifest before committing.

For changes affecting deployment, also validate the relevant commands from a consumer checkout using `PLATFORM_TOOLS_DIR=../platform-tools`; see [PLATFORM.md](PLATFORM.md) for the platform contract and validation commands.

## 3. Commit and publish

Review everything staged, including new files, before committing. Include `distribution.json` and all intended release sources together.

```sh
git add -A
git diff --cached --stat
git diff --cached --check
git diff --cached
```

After reviewing:

```sh
git commit -m "Release platform tools $release_tag"
git tag -a "$release_tag" -m "Platform tools $release_tag"
git push origin main
git push origin "$release_tag"
```

Stop if a command fails. If pushing `main` is rejected, reconcile the branch before publishing the tag. If branch protection requires a PR, merge the release changes first, check out the resulting `main` commit, regenerate and verify the manifest, then tag that commit.

Wait for GitHub Actions checks on both `main` and the tag to pass. Tag checks verify that `VERSION` matches the tag and that the manifest is current. If a published tag fails validation, fix the issue and publish a new version; do not retag it.

## 4. Upgrade consumers

Only after the tag checks pass:

1. Copy the generated lock JSON into the application's `platform.lock.json`.
2. Update every reusable platform workflow reference to the same tag, including delivery and production callers.
3. From the application checkout, install and verify the pinned release:

   ```sh
   make setup
   make platform-fetch
   make platform-version
   make chart-test
   ```

4. Run the applicable acceptance checks, then review and commit the consumer changes.

To roll back tooling, restore the previous lock and workflow pins together. This does not roll back deployed applications or database data.
