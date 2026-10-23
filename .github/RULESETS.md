# Repository rules to apply in GitHub

These settings live in the GitHub web interface, not in files, so they are written down here. Apply
them once. Names below match the job names in `.github/workflows/` exactly.

## Ruleset 1: protect `main` (Settings, Rules, Rulesets, New branch ruleset)

- Enforcement: Active. Target: the default branch.
- Restrict deletions. Block force pushes.
- Require linear history (squash merge only).
- Require a pull request before merging: 1 approval, dismiss stale approvals on new commits, require
  review from Code Owners (see `CODEOWNERS`), require approval of the most recent push, require
  conversation resolution. While there is one maintainer, set the approvals to 0 and keep the rest.
- Require status checks to pass, branches up to date before merging:
  - `ci-passed` (integration: GitHub Actions)
  - `pr-title` (integration: GitHub Actions)
- Require signed commits (optional, recommended once the maintainer signs).
- Bypass list: empty. Add the repository admin role only if a release needs an emergency fix.

Why one aggregate check: `ci-passed` depends on every job in `ci.yml`, treats a path filtered skip as
a pass and a failure or cancellation as a fail. Adding, renaming or skipping a job never needs a
settings change.

## Ruleset 2: protect release tags

- Target: tags matching `v*`. Restrict creation to the maintainer role, restrict updates and deletions
  (a published tag never moves).
- The `release-please` workflow creates the tag with the token it is given. If it cannot create tags,
  add the repository secret `RELEASE_PLEASE_TOKEN` (see below) and put that identity on the bypass list.

## Merge settings (Settings, General, Pull Requests)

- Allow squash merging only. Default commit message: pull request title and description.
  The title is a Conventional Commit, checked by `pr-title`.
- Automatically delete head branches. Allow auto-merge.

## Environments (Settings, Environments)

| Environment | Required reviewers | Deployment branches and tags | Used by |
|---|---|---|---|
| `pypi` | the maintainer | tags `v*` | `release.yml`, job `publish-pypi` |
| `testpypi` | none needed, or the maintainer | tags `v*` | `release.yml`, job `publish-testpypi` |
| `demo` | the maintainer | tags `v*` and branch `main` | `deploy-demo.yml` |

Turn on "Prevent self-review" once there is a second maintainer.

## Actions settings (Settings, Actions, General)

- Actions permissions: allow actions created by GitHub and the specific third party actions in use, or
  "Allow all" with "Require actions to be pinned to a full-length commit SHA" turned on. Every workflow
  here already pins by SHA.
- Workflow permissions: read repository contents and packages only (the default token is read only; each
  job asks for what it needs).
- Allow GitHub Actions to create and approve pull requests only when `RELEASE_PLEASE_TOKEN` is not set
- Fork pull requests: require approval for all outside collaborators.

## Security settings (Settings, Code security)

- Dependency graph, Dependabot alerts and Dependabot security updates: on.
- Secret scanning and push protection: on (free once the repository is public).
- Private vulnerability reporting: on (the issue chooser and `SECURITY.md` point at it).
- Code scanning default setup is not needed: `codeql.yml` is the configuration.
- While the repository is private and has no GitHub Advanced Security, `codeql` and `dependency review`
  skip themselves. Set the repository variable `ENABLE_ADVANCED_SECURITY` to `true` if the plan includes it.

## Repository variables and secrets

| Name | Kind | Needed for |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN` | variable | `deploy-demo.yml` (output of `infra/aws-github-oidc/github-oidc-deploy-role.yaml`) |
| `DEMO_CERT_ARN` | variable | ISSUED ACM certificate (us-east-1) for the demo domain |
| `DEMO_ALERT_EMAIL` | variable | alarm and budget notices |
| `DEMO_DOMAIN`, `DEMO_STACK` | variable, optional | defaults `osm.changesetreview.online`, `cso-demo` |
| `ENABLE_ADVANCED_SECURITY` | variable, optional | `codeql`, `dependency review` on a private repository |
| `RELEASE_PLEASE_TOKEN` | secret, optional | fine grained token (this repository, contents and pull requests write) so the release pull request runs the required checks |

No PyPI token and no AWS key is stored anywhere: PyPI uses Trusted Publishing and AWS uses OIDC.

## Discussions

Turn on Discussions (Settings, General, Features). The issue chooser sends questions and ideas there.
Suggested categories: Q&A, Ideas, Show and tell, Announcements.

## Labels

Create these labels so the labeler, release notes and the stale sweep work: `backend`, `web`, `docs`,
`infra`, `ci`, `eval`, `security`, `dependencies`, `python`, `javascript`, `postgres`, `stale`,
`planned`, `pinned`, `help wanted`, `good first issue`, `skip-changelog`.
