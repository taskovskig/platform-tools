# Platform tools

Platform-team-owned tooling for local Kubernetes application environments. Consumers pin a Git tag and SHA-256 of `distribution.json`; that manifest pins every file in the package, including the shared Helm chart and reusable workflow. Do not move or overwrite published tags.

## Ownership and consumer contract

The application repository owns `platform.json`, a thin Makefile/bootstrap, application Helm values and database overrides, build inputs, HTTP expectations, browser tests and its database-outage assertion. The platform owns local infrastructure defaults, lifecycle scripts, chart templates, tool/dependency versions, release-isolation tests and the generic persistence drill. Developer application code and Dockerfiles are not modified.

The current contract supports named stateless HTTP applications and one optional-in-use local PostgreSQL service (database configuration is required by schema v1). The local database bootstrap requires a fresh cluster or matching credentials; it never rotates an initialized database. Production managed databases require a separate provisioning path. Image versions and protocol are deliberately constrained to this initial MVP.

`PROJECT_ROOT` must point to the consumer checkout. Scripts resolve values/build paths relative to that checkout and chart/runtime paths relative to this package. They use a dedicated kubeconfig and explicit cluster context. Application releases are independent of the PostgreSQL release. The shared chart's version is coupled to the platform tag so a consumer cannot accidentally combine incompatible tooling and chart versions.

## Infrastructure defaults (v0.2.0)

Existing schema-v1 consumers remain supported without changes. Projects can omit
these `platform.json` fields to use the platform defaults:

| Optional field | Default |
| --- | --- |
| `kindConfig` | `defaults/kind.yaml`: one control-plane node |
| `namespaceManifest` | Generated namespace using `namespace`, with restricted Pod Security pinned to v1.37 |
| `database.serviceAccountManifest` | Generated service account named after `database.release`, in the project namespace, with token automount disabled |

An explicitly supplied path must exist; invalid overrides fail rather than falling
back silently. Generated manifests live in the consumer's ignored
`.platform/infrastructure/` directory and are recreated before database deployment.
The platform package remains immutable. Custom service-account manifests must match
`serviceAccount.name` in the project's database values.

Database Helm values are applied in this order (last file wins):

1. Platform `defaults/db.values.yaml`: security context, credential key names,
   storage retention, storage size/class, and resource defaults.
2. Generated project names: release/fullname, existing Secret, and service account.
3. Required project `database.values`: PostgreSQL image version, database name,
   and any intentional overrides.

Keep the PostgreSQL image tag explicit in project values; the platform defaults
intentionally do not select an image version. A minimal project override is:

```yaml
image:
  tag: 17-bookworm
env:
  - {name: POSTGRES_DB, value: api-db}
```

Review database upgrades separately from tooling upgrades. Helm merges maps but
replaces lists, so an application `env` override must include every required entry.
Existing full database values files continue to override the new defaults.
Application chart values (ports, health endpoints, images, writable paths and
resource overrides) remain application-owned.

After publishing v0.2.0, consumers may upgrade both pins, remove the three optional
path fields and their old files, and reduce database values to application-specific
overrides. Verify deployment, persistence and release isolation before committing
that consumer migration. No consumer migration is needed to publish this release.

## Everyday development

Commit and push source changes normally; run `make test` for local validation.
You do not need to run `make release-manifest` or commit `distribution.json`
for ordinary changes. Pull requests and pushes to `main` run the tests without
requiring an up-to-date manifest. The checked-in manifest may therefore be stale
between releases.

## Preparing a release

Manifest generation is required only when preparing a new release. Finish all
source changes, update `VERSION`, then run `make release-manifest` and commit the
generated manifest together with the release changes. Any further packaged-file
changes require regenerating it before tagging.

Pushing a `v*` tag runs tests and checks that `VERSION` matches the tag and that
regenerating the manifest produces no diff. Wait for these checks to pass before
upgrading consumers. Tags remain immutable; a failed tag check requires a corrected
commit and a new version/tag, not moving the published tag.

## First release

1. Review the extraction and run the consumer with `PLATFORM_TOOLS_DIR=../platform-tools make chart-test` and the acceptance commands. Local override is explicit and forbidden in CI.
2. Set `VERSION` to the release tag (initially `v0.1.0`). Run `make release-manifest`. Commit all platform source and generated `distribution.json` together.
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
