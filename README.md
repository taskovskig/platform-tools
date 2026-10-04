# Platform tools

## Install the platform CLI

The `platform-tools-cli` Python package is distributed directly from this repository's immutable release tags. No PyPI publication or application-owned bootstrap source is required. Python 3.10+, Git and pipx are prerequisites.

```sh
pipx install 'git+https://github.com/taskovskig/platform-tools.git@v0.5.0'
pipx ensurepath
platform-tools --version
```

Open a new shell if the command is not yet on PATH. To update an existing installation to a reviewed version, use `pipx install --force` with the explicit tagged URL; do not use an unpinned branch. [pipx supports Git sources](https://pipx.pypa.io/latest/how-to/install-pipx.html).

Run commands inside an application checkout (including subdirectories), or use `platform-tools --project /path/to/app fetch`. `--version` reports the installed CLI version; `version` reports the application's pinned platform release. The CLI verifies downloaded/cached files against `platform.lock.json` and checks the reusable workflow pin. Lock `cliApiVersion: 1` identifies the supported bootstrap protocol, independent of the release version; an unsupported value fails before downloading or executing anything. Older locks without that field default to protocol 1.

The reusable delivery workflow installs the CLI in a runner-local virtual environment before invoking Make. The installer trusts the reviewed GitHub release tag; the subsequent platform payload is additionally verified against the application's manifest checksum. A missing CLI makes Make stop with installation instructions.

For platform development, install this checkout with `pipx install --force .`, then use `PLATFORM_TOOLS_DIR=../platform-tools make <target>` from the application. The override remains forbidden in CI.

Documentation rendering is an optional extra, also owned here:

```sh
pipx install --force 'platform-tools-cli[docs] @ git+https://github.com/taskovskig/platform-tools.git@v0.5.0'
platform-render-design PLATFORM-DESIGN.md PLATFORM-DESIGN.pdf
```

The existing case-study layout is retained. Input/output paths now come from arguments; installing the base CLI does not install ReportLab. The Markdown and generated PDF remain application-owned.

Before publishing, align `VERSION`, `platform_tools.__version__`, and the CLI installation tag in `delivery.yaml`; run tests and generate the release manifest. Publish v0.5.0 before upgrading application workflow/lock pins. Package installation is validated by the platform checks workflow. Bootstrap tests now live in `tests/test_cli.py` in this repository.


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

## Shared-cluster delivery (v0.4.0)

`.github/workflows/delivery.yaml` is the reusable workflow for branch pushes.
Callers must serialize the entire workflow (CI and promotion together) with one
repository-scoped concurrency group and `cancel-in-progress: false`, grant
`packages: write`, and use `secrets: inherit`. Non-main pushes select GitHub
environment `app-ci`; main selects `app-dev`. The selected environment supplies
`KUBECONFIG`. The API must be reachable by a hosted Linux AMD64 runner.

Consumers configure `environments.app-ci` and `environments.app-dev`, each with
`cluster`, matching `kind-<cluster>` context, matching namespace, and public GHCR
`imagePrefix`. The supported namespaces are exactly `app-ci` and `app-dev`;
production execution is disabled. `PLATFORM_ENVIRONMENT` selects one of them or
`local` (default). Namespace creation and RBAC remain administrative operations.

Feature CI calls `ci-reset` first: uninstall configured applications and database,
delete the database PVC and Secret, while retaining namespace and deployment RBAC.
`ci-up` builds `ci-$GH_BUILD_NUMBER` (GitHub workflow run number), pushes it and
`ci-latest`, and installs the numbered image pinned by digest. Tests run against CI
services. `ci-passed` marks images only after acceptance succeeds. Image tags may
move, including the numbered tag on a rerun; deployed references include a digest.

Main calls `promote`: pull `ci-latest`, verify it matches `ci-passed`, compare its
source-tree label to checked-out main, and require consistent CI build labels
across applications. Add `dev-latest`, upgrade development, and smoke-test without
building images or resetting development data. A latest image from another branch
fails promotion before any development tag or deployment change. Rerun the intended
feature CI then main promotion if aliases moved. Require up-to-date PR branches.

The reusable workflow never invokes kind lifecycle commands. `local-tests` is a
separate developer-only command, rejected in CI/shared modes. It installs local
test dependencies and exercises the full original local kind acceptance flow,
leaving the cluster running for inspection. Consumer Makefiles expose it as
`make local-tests`; CI uses individual test commands against `app-ci` instead.

`app-prod` is provisioned but never deployed by this workflow. Application sources
and Dockerfiles remain developer-owned. Namespace-scoped kubeconfigs should use
the appropriate `platform-deployer` identity; credentials must be renewed before
expiration. Shared namespaces still share node/control-plane failure domains.

## Cluster provisioning on main

`.github/workflows/provision-cluster.yaml` runs on every push to `main` in this
platform repository, and can also be started manually from `main`. It runs the
tooling tests, installs checksum-verified kubectl, and applies:

- `defaults/namespaces.yaml`: `app-ci`, `app-dev`, and `app-prod`, with restricted
  Pod Security admission pinned to v1.37.
- `defaults/ci-access.yaml`, `defaults/development-access.yaml`, and
  `defaults/production-access.yaml`: a separate `platform-deployer` service account,
  Role, and RoleBinding in each corresponding namespace. Each binding names only
  the service account from its own namespace; there are no ClusterRoleBindings.
  The repeated `app-dev` namespace declaration matches the namespace defaults.

Repeated runs use `kubectl apply`; they do not delete namespaces, prune resources,
create/delete the kind cluster, or deploy applications. Production provisioning
creates its namespace and deployment access, but does not install workloads or
enable production deployment. Each identity has the same deployment permissions
restricted to its own namespace. Existing workloads must comply with the restricted
policy for future pod creations. Application CI runs in `app-ci`; `app-dev` receives tested-image promotion.
Disposable kind clusters are used only for developer-local tests.

Before the first run, configure **this repository's** GitHub environment
`platform-administration`:

1. Allow deployment from `main` only. Protect `main` with review requirements;
   optionally require an environment reviewer for administrative changes.
2. Set the **Actions repository secret** `KUBECONFIG` under Settings → Secrets
   and variables → Actions, or set an environment secret with that name in
   `platform-administration`. The workflow reads `${{ secrets.KUBECONFIG }}`,
   which supports either location; a same-named environment secret takes precedence.
   Do not use a configuration variable. Store the full portable administrative
   kubeconfig contents with context `kind-testkube-samples`, not a local path.
   Its identity must be allowed to manage these namespaces and their scoped RBAC.
   The namespace-limited application credential cannot perform provisioning.
3. Ensure its API endpoint is reachable from GitHub-hosted runners and its
   embedded credentials are valid. The workflow writes them to a temporary file
   with restricted permissions and removes the file on completion/failure.

The `platform-administration` job environment still supplies deployment rules
when using a repository secret. A repository secret is also available to other
eligible workflows in this repository; environment secrets provide narrower
exposure. See [GitHub secret precedence](https://docs.github.com/en/actions/reference/security/secrets).

The application repository's `app-ci`, `app-dev`, and `app-prod` environments
each keep their own namespace-scoped `KUBECONFIG`. Do not replace it with the administrative credential.
After provisioning passes, create/renew the scoped application kubeconfig as
needed and rerun the failed application delivery job. Existing token creation
and renewal remain administrative steps, not part of this provisioning workflow.

No new platform tag or application pin update is needed to activate provisioning:
it runs from `main`. Keep published tags unchanged. Generate a fresh manifest
only when preparing the next platform release. Commit and push these workflow,
manifest-source, script, test, and documentation changes normally.

## Everyday development

Commit and push source changes normally; run `make test` for local validation.
You do not need to run `make release-manifest` or commit `distribution.json`
for ordinary changes. Pull requests and pushes to `main` run the tests without
requiring an up-to-date manifest. The checked-in manifest may therefore be stale
between releases.

## Preparing a release

Manifest generation is required only when preparing a new release. It includes tracked and non-ignored source files; ignored local credentials are excluded, and tracked `.kube` files are rejected. Finish all
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

4. Copy the JSON printed by `release.py` into the consumer's `platform.lock.json`. Pin its reusable workflow to `taskovskig/platform-tools/.github/workflows/delivery.yaml@<new-tag>` as well. The installed CLI checks both pins agree.
5. Run `make platform-fetch` without a local override. This downloads the GitHub tag archive, checks the manifest and every file, then atomically caches it under `.platform/tools/<manifest digest>`. A missing tag, mismatched checksum or unsafe archive fails without executing downloaded scripts. Review and commit the consumer pin upgrade after acceptance passes.

The first release must be published before hosted consumer CI can resolve the reusable workflow. For private repositories, grant access to reusable workflows in GitHub settings and provide cross-repository read credentials for downloads; the caller's default token does not automatically grant access to a second private repository. Public repositories need no download credentials. Locally an authenticated `gh` CLI is used as a fallback for private archives.

## Subsequent releases and rollback

Never retag a release. Update VERSION, regenerate the manifest, test, commit, tag, and push a new version. Upgrade both consumer pins in one PR. Revert both pins to roll back tooling; this does not automatically roll back deployed Helm releases or database data. Use the application's release history and explicit recovery commands for those.

Generic chart checks use an isolated npm dependency directory under the consumer's `.platform/`, populated from this repository's locked test dependencies. Browser/application dependencies remain with their owner. `scripts/install-tools.sh` installs pinned kind, kubectl and Helm binaries on Linux AMD64 runners; macOS developers install prerequisites through their usual package manager.

## Validation

Run `python3 -m unittest discover -s tests -p 'test_*.py'` for configuration contracts and `bash -n scripts/*.sh` for shell syntax. Run `make chart-test`, `make up`, `make helm-test`, `make resilience` and browser acceptance from a consumer checkout using the explicit local override before publishing. CLI download, cache, tamper, archive-safety, project discovery and dispatch tests run in this repository.
