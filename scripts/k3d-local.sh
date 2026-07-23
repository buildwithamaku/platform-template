#!/usr/bin/env bash
# Spin a local k3d cluster and bootstrap the platform onto it — free Phase-2 dev.
#
# Requires: Docker running, k3d, kubectl, helm.
# Optional secrets (export before running) for the full acceptance test:
#   GIT_TOKEN, INFISICAL_CLIENT_ID, INFISICAL_CLIENT_SECRET
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/.." && pwd)"
CLUSTER="${CLUSTER:-refclient-local}"

command -v docker >/dev/null || { echo "Docker not found"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon not running — start Docker Desktop"; exit 1; }

if ! k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  echo "==> creating k3d cluster '$CLUSTER'"
  k3d cluster create --config "${repo_root}/k3d/refclient-local.yaml"
fi
kubectl config use-context "k3d-${CLUSTER}" >/dev/null

# Default the platform revision to the branch you're on, so ArgoCD's ROOT app
# reads clusters/platform/ from your working branch (not main). NOTE: the
# git-sourced child apps (infisical-store, demo) still pin main — see README.
export PLATFORM_REPO_REVISION="${PLATFORM_REPO_REVISION:-$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)}"
echo "==> bootstrapping (revision: ${PLATFORM_REPO_REVISION})"
exec "${repo_root}/bootstrap.sh"
