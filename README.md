# Platform tools

Platform-team-owned tooling for local Kubernetes application environments. Consumers pin a Git tag and SHA-256 of `distribution.json`; that manifest pins every file in the package, including the shared Helm chart and reusable workflow. Do not move or overwrite published tags.

## Ownership and consumer contract

The application repository owns `platform.json`, a thin Makefile/bootstrap, Helm values, build inputs, HTTP expectations, browser tests and its database-outage assertion. The platform owns lifecycle scripts, chart templates, tool/dependency versions, release-isolation tests and the generic persistence drill. Developer application code and Dockerfiles are not modified.

The current contract supports named stateless HTTP applications and one optional-in-use local PostgreSQL service (database configuration is required by schema v1). The local database bootstrap requires a fresh cluster or matching credentials; it never rotates an initialized database. Production managed databases require a separate provisioning path. Image versions and protocol are deliberately constrained to this initial MVP.

`PROJECT_ROOT` must point to the consumer checkout. Scripts resolve values/build paths relative to that checkout and chart/runtime paths relative to this package. They use a dedicated kubeconfig and explicit cluster context. Application releases are independent of the PostgreSQL release. The shared chart's version is coupled to the platform tag so a consumer cannot accidentally combine incompatible tooling and chart versions.

## First release

1. Review the extraction and run the consumer with `PLATFORM_TOOLS_DIR=../platform-tools make chart-test` and the acceptance commands. Local override is explicit and forbidden in CI.
2. Set `VERSION` to the release tag (initially `v0.1.0`). Run `python3 scripts/release.py`. Commit all platform source and generated `distribution.json` together.
3. Create and publish an annotated tag on that exact commit:

   ```sh
   git tag -a v0.1.0 -m 'Platform tools v0.1.0'
   git push origin HEAD
   git push origin v0.1.0
   ```

4. Copy the JSON printed by `release.py` into the consumer's `platform.lock.json`. Pin its reusable workflow to `taskovskig/platform-tools/.github/workflows/acceptance.yaml@v0.1.0` as well. The consumer bootstrap checks both pins agree.
5. Run `make platform-fetch` without a local override. This downloads the GitHub tag archive, checks the manifest and every file, then atomically caches it under `.platform/tools/<manifest digest>`. A missing tag, mismatched checksum or unsafe archive fails without executing downloaded scripts. Review and commit the consumer pin upgrade after acceptance passes.

The first release must be published before hosted consumer CI can resolve the reusable workflow. For private repositories, grant access to reusable workflows in GitHub settings and provide cross-repository read credentials for downloads; the caller's default token does not automatically grant access to a second private repository. Public repositories need no download credentials. Locally an authenticated `gh` CLI is used as a fallback for private archives.

## Subsequent releases and rollback

Never retag a release. Update VERSION, regenerate the manifest, test, commit, tag, and push a new version. Upgrade both consumer pins in one PR. Revert both pins to roll back tooling; this does not automatically roll back deployed Helm releases or database data. Use the application's release history and explicit recovery commands for those.

Generic chart checks use an isolated npm dependency directory under the consumer's `.platform/`, populated from this repository's locked test dependencies. Browser/application dependencies remain with their owner. `scripts/install-tools.sh` installs pinned kind, kubectl and Helm binaries on Linux AMD64 runners; macOS developers install prerequisites through their usual package manager.

## Validation

Run `python3 -m unittest discover -s tests -p 'test_*.py'` for configuration contracts and `bash -n scripts/*.sh` for shell syntax. Run `make chart-test`, `make up`, `make helm-test`, `make resilience` and browser acceptance from a consumer checkout using the explicit local override before publishing. The application bootstrap has separate download, cache, tamper and archive-safety tests in the consumer repo.
