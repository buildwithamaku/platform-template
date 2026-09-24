# Adopting the platform factory (for a new user)

You do **not** fork or edit this repo. It's a [copier](https://copier.readthedocs.io)
template: you *render your own platform repo* from it, then *connect your app repo(s)* to
that. Three repos are involved:

```
platform-template (this factory) ──copier render──▶  <you>/<client>-platform  (GitOps repo; Argo CD watches it)
                                                              ▲
                                    image-tag bump │ (your deployer GitHub App)
                                                              │
                                     <you>/<client>-app  (your code) ──build-and-bump──┘
```

- **factory** — this repo. Never edited by you; you generate instances from it.
- **platform repo** — rendered per client. It's the GitOps source of truth; Argo CD reconciles it.
- **app repo(s)** — your actual application code. Connected via the `build-and-bump` workflow.

---

## 1. Render your platform repo
Install copier and render an instance, answering the questionnaire (this is where it becomes
*yours* — `client_name`, `domain`, `registry_org` = **your** GitHub org, `cloud`, capabilities):

```bash
pipx install copier        # or: uvx copier
copier copy --trust gh:buildwithamaku/platform-template <client>-platform
# from a local copy instead: copier copy --trust ./platform-template <client>-platform
```

`--trust` is required because the template runs copier tasks. Then push it to **your** org:

```bash
cd <client>-platform && git init && git add -A && git commit -m "init from platform-template"
gh repo create <your-org>/<client>-platform --private --source=. --push
```

Read `docs/RUNBOOK.md` **in your rendered repo** — it's tailored to your answers (your domain,
cloud, capabilities) and is the authoritative operating manual.

## 2. Accounts (all yours)
Per RUNBOOK §1.1: your **cloud** (Hetzner / DigitalOcean / **baremetal** — any VPS incl.
InterServer, OVH, on-prem), **Cloudflare** (domain + an R2 bucket for DB backups), **Infisical**
(secrets), **Tailscale** (private admin access), and — needed to connect app repos — **your own
deployer GitHub App** (`<your-org>-deployer`: an app-id + private key).

## 3. Provision + bootstrap (RUNBOOK §1.3–1.4)
```bash
cd tofu/live/staging && tofu init && tofu apply   # cluster + ./kubeconfig
./bootstrap.sh                                     # installs Argo CD → it reconciles everything from git
```
(For `cloud=baremetal` you provision the nodes first and put their IPs in `terraform.tfvars` —
see `docs/TESTING-baremetal.md` and the module README.)

## 4. Connect an app repo
Three things wire your code to the platform:

### (a) Your app ships a Dockerfile
Container images only — no buildpacks. The image must run as a **numeric non-root USER**. The full
6-point contract is `docs/APP-CONTRACT.md` in your rendered repo (Dockerfile · numeric non-root USER
· `$PORT` · liveness+readiness endpoints · config from env · no boot-time migrations).

### (b) A thin caller workflow in the app repo
Add `.github/workflows/deliver.yml` to your **app** repo. Ready-to-paste variants are in this
factory under [`examples/app-ci/`](../examples/app-ci):
- `deliver-node-polyrepo.yml` — a Node app in its own repo
- `deliver-go-polyrepo.yml` — a Go app in its own repo
- `deliver-monorepo.yml` — one repo, backend + frontend (two `build-and-bump` calls)

The minimal shape:
```yaml
name: deliver
on: { push: { branches: [main] } }
jobs:
  ship:
    permissions: { contents: read, packages: write }
    uses: <your-org>/<client>-platform/.github/workflows/build-and-bump.yaml@main
    with:
      app: backend                              # overlay dir: clusters/apps/<app>/overlays/staging
      image: ghcr.io/<your-org>/<client>-backend
      language: node                            # or: go
      context: .                                # monorepo? the service subdir, e.g. "backend"
    secrets:
      deployer_app_id: ${{ secrets.DEPLOYER_APP_ID }}
      deployer_private_key: ${{ secrets.DEPLOYER_PRIVATE_KEY }}
```

### (c) Install the deployer GitHub App + set secrets
- Create/install `<your-org>-deployer` on **both** repos. The **platform** repo needs it with
  `contents: write` (it commits the overlay tag bump). The app repo needs it to mint the token.
- In the **app** repo's Settings → Secrets, add `DEPLOYER_APP_ID` and `DEPLOYER_PRIVATE_KEY`.

Now **push to the app repo's `main`** → `build-and-bump` builds + scans (gitleaks) + tests + pushes
the image to GHCR, then (as the deployer App) commits the SHA-tag bump into the platform repo's
`overlays/staging` → **Argo CD deploys it**. The app repo never touches the cluster.

- **Polyrepo:** each app repo gets its own `deliver.yml`.
- **Monorepo:** one repo calls `build-and-bump` once per service (different `app` + `context`).

## 5. Day-2
- **Staging is automatic** on merge to the app repo.
- **Prod is a promotion PR**: bump `clusters/apps/<app>/overlays/prod/kustomization.yaml` to the
  proven staging SHA → review → merge → Argo deploys → PostSync smoke.
- **Rollback** = `git revert` the tag-bump commit.
- **Access** everything (Argo, Grafana, kubectl) over the tailnet — no public admin surface.

## 6. Pull future factory improvements
copier wrote a `.copier-answers.yml` into your platform repo. When this factory improves, run
`copier update` in your platform repo to merge the new template changes into yours (same answers,
updated scaffolding), then review + commit the diff.

## A second client
A new answers file + repeat from step 1. Nothing about the factory changes.
