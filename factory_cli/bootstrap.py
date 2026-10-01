"""Bootstrap a published bundle into an explicitly selected cluster."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml


def bootstrap(platform, environment, context):
    platform = Path(platform).resolve()
    if environment not in {"staging", "prod"} or not context or context.startswith("-"):
        raise ValueError("Provide staging/prod and an explicit Kubernetes context")
    for tool in ("git", "kubectl", "helm", "kustomize", "bash"):
        if not shutil.which(tool):
            raise ValueError(f"Install {tool} before bootstrap")
    for key in ("INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"):
        if not os.environ.get(key):
            raise ValueError(f"Set {key} through your secret manager before bootstrap")
    script = platform / "bootstrap.sh"
    root = platform / "clusters/bootstrap/app-of-apps.yaml"
    applications = platform / f"clusters/environments/{environment}/applications.yaml"
    if not script.is_file() or not root.is_file() or not applications.is_file():
        raise ValueError("Use the platform directory from a factory onboard bundle")
    root_app = yaml.safe_load(root.read_text())
    if root_app["spec"]["source"]["path"] != "clusters/environments/__ENVIRONMENT__":
        raise ValueError("Bootstrap root does not support explicit environment selection")

    def read(*args):
        return subprocess.run(args, cwd=platform, check=True, capture_output=True,
                              text=True, timeout=60).stdout.strip()

    # Argo reads Git, not local files. Require precisely the published main tree.
    if Path(read("git", "rev-parse", "--show-toplevel")).resolve() != platform:
        raise ValueError("Platform must be its own Git repository")
    if read("git", "status", "--porcelain"):
        raise ValueError("Commit and publish all platform changes before bootstrap")
    revision = read("git", "rev-parse", "HEAD")
    remote = read("git", "remote", "get-url", "origin")
    answers = yaml.safe_load((platform / ".copier-answers.yml").read_text())
    repo = f"{answers['registry_org']}/{answers['platform_repo']}"
    expected = f"https://github.com/{repo}.git"
    if remote.removesuffix(".git") not in {expected.removesuffix(".git"), f"git@github.com:{repo}"}:
        raise ValueError("origin must match the GitHub repository declared during onboarding")
    remote = expected
    published = read("git", "ls-remote", "origin", "refs/heads/main").split()
    if not published or published[0] != revision:
        raise ValueError("Local platform HEAD must match published origin/main")
    for document in yaml.safe_load_all(applications.read_text()):
        if not document or document.get("kind") != "Application":
            continue
        source = document["spec"]["source"]
        if "path" in source:
            path = (platform / source["path"]).resolve()
            if not path.is_relative_to(platform):
                raise ValueError("Application path escapes the platform checkout")
            read("kustomize", "build", str(path))
    read("bash", "-n", str(script))
    read("kubectl", "--context", context, "--request-timeout=15s", "get", "namespace", "kube-system", "-o", "name")
    # Avoid overriding a cluster already assigned to the other environment.
    crd = read("kubectl", "--context", context, "--request-timeout=15s", "get", "crd",
               "applications.argoproj.io", "--ignore-not-found", "-o", "name")
    existing = read("kubectl", "--context", context, "--request-timeout=15s", "get", "applications.argoproj.io",
                    "platform-root", "-n", "argocd", "--ignore-not-found", "-o", "json") if crd else ""
    if existing:
        source = json.loads(existing)["spec"]["source"]
        if source["path"] != f"clusters/environments/{environment}":
            raise ValueError("Cluster already has a root for a different environment")
        if source.get("repoURL", "").removesuffix(".git") != remote.removesuffix(".git"):
            raise ValueError("Cluster already has a root owned by another platform repository")
    env = dict(os.environ, FACTORY_KUBE_CONTEXT=context, PLATFORM_ENVIRONMENT=environment,
               PLATFORM_REPO_URL=remote, PLATFORM_REPO_REVISION="main",
               ARGOCD_NAMESPACE="argocd", ESO_NAMESPACE="external-secrets")
    subprocess.run(["bash", str(script)], cwd=platform, env=env, check=True)
    return {"environment": environment, "context": context, "revision": revision}
