"""Read-only deployment evidence. Health alone never certifies app acceptance."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import urllib.request
from urllib.parse import urlsplit

import yaml

from .acceptance import run_acceptance


def deployment_ready(document):
    spec, status = document["spec"], document.get("status", {})
    count = spec.get("replicas", 1)
    return (count > 0 and status.get("observedGeneration", 0) >= document["metadata"]["generation"]
            and all(status.get(key, 0) == count for key in
                    ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas")))


def reconciled(document, revision=None):
    status = document.get("status", {})
    sync = status.get("sync", {})
    return (sync.get("status") == "Synced"
            and status.get("health", {}).get("status") == "Healthy"
            and status.get("operationState", {}).get("phase") == "Succeeded"
            and (revision is None or (sync.get("revision") == revision
                 and status.get("operationState", {}).get("syncResult", {}).get("revision") == revision)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_probe(url):
    # Default TLS verification stays enabled; redirects cannot disguise failures.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with client.open(url, timeout=15) as response:
        return 200 <= response.status < 300


def verify(platform, environment, context, urls, acceptance_suite=None):
    platform = Path(platform).resolve()
    if environment not in {"staging", "prod"} or not context or context.startswith("-"):
        raise ValueError("An explicit staging/prod environment and Kubernetes context are required")
    checks, images, hosts = [], {}, set()

    def read(*args):
        return subprocess.run(args, cwd=platform, check=True, capture_output=True,
                              text=True, timeout=60).stdout

    def kube(kind, name, namespace):
        return json.loads(read("kubectl", "--context", context, "--request-timeout=15s",
                               "get", kind, name, "-n", namespace, "-o", "json"))

    def record(name, passed, detail):
        checks.append({"check": name, "status": "verified" if passed else "failed", "detail": detail})

    if Path(read("git", "rev-parse", "--show-toplevel").strip()).resolve() != platform:
        raise ValueError("Platform must be its own Git repository")
    if read("git", "status", "--porcelain").strip():
        raise ValueError("Verify a clean committed platform checkout")
    revision = read("git", "rev-parse", "HEAD").strip()
    answers = yaml.safe_load((platform / ".copier-answers.yml").read_text())
    repo = f"https://github.com/{answers['registry_org']}/{answers['platform_repo']}.git"
    documents = list(yaml.safe_load_all((platform / f"clusters/environments/{environment}/applications.yaml").read_text()))
    desired = [d for d in documents if d and d.get("kind") == "Application"]
    desired.insert(0, {"metadata": {"name": "platform-root"}, "spec": {"source": {
        "repoURL": repo, "path": f"clusters/environments/{environment}", "targetRevision": "main"}}})
    for app in desired:
        name, source = app["metadata"]["name"], app["spec"]["source"]
        try:
            live = kube("applications.argoproj.io", name, "argocd")
            actual = live["spec"]["source"]
            source_matches = all(actual.get(k) == source.get(k) for k in ("repoURL", "path", "chart", "targetRevision"))
            record(f"argocd.{name}", source_matches and reconciled(live, revision if "path" in source else None),
                   "Requires matching source, Synced, Healthy, successful operation, and expected Git revision.")
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            record(f"argocd.{name}", False, "Unable to read application state; command output withheld.")
        if name not in {"backend", "frontend"}:
            continue
        path = (platform / source["path"]).resolve()
        if not path.is_relative_to(platform):
            raise ValueError("Application source escapes platform checkout")
        resources = yaml.safe_load_all(read("kustomize", "build", str(path)))
        for resource in resources:
            if not resource:
                continue
            if resource.get("kind") == "Ingress":
                hosts.update(rule["host"] for rule in resource["spec"].get("rules", []) if "host" in rule)
            if resource.get("kind") != "Deployment":
                continue
            meta = resource["metadata"]
            key = f"{meta['namespace']}/{meta['name']}"
            expected = {c["name"]: c["image"] for c in resource["spec"]["template"]["spec"]["containers"]}
            images[key] = expected
            pinned = all(re.fullmatch(r".+@sha256:[a-f0-9]{64}", image) for image in expected.values())
            try:
                live = kube("deployment", meta["name"], meta["namespace"])
                actual = {c["name"]: c["image"] for c in live["spec"]["template"]["spec"]["containers"]}
                record(f"deployment.{key}", pinned and expected == actual and deployment_ready(live),
                       "Requires digest-pinned matching images and all replicas updated, ready, and available.")
            except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                record(f"deployment.{key}", False, "Unable to read deployment; command output withheld.")
    if not images:
        record("workloads", False, "No application deployments found")
    for url in urls:
        parsed = urlsplit(url)
        if parsed.port not in {None, 443} or parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Verification URLs must use HTTPS on a generated application ingress host, without credentials, query, or fragment")
        try:
            record(f"https.{url}", https_probe(url), "Public DNS/TLS/HTTP request must return 2xx without redirects.")
        except (OSError, ValueError):
            record(f"https.{url}", False, "HTTPS request failed; response content withheld.")
    if not urls:
        checks.append({"check": "public-https", "status": "unverified", "detail": "Supply application HTTPS URLs to check DNS, TLS and ingress."})
    acceptance = None
    if acceptance_suite and all(c["status"] == "verified" for c in checks):
        target = {"version": 1, "environment": environment, "context": context,
                  "revision": revision, "images": images, "urls": urls}
        acceptance = run_acceptance(platform, acceptance_suite, target)
        record("application-database-acceptance", acceptance["passed"],
               "Application-owned suite must pass nonempty application and database assertions.")
        # Re-observe after the suite: a concurrent rollout invalidates its result.
        after = verify(platform, environment, context, urls)
        stable = (after["revision"] == revision and after["images"] == images
                  and all(c["status"] == "verified" for c in after["checks"]
                          if c["check"] != "application-database-acceptance"))
        record("stable-acceptance-target", stable, "Target must remain healthy at the same revision and digests after acceptance.")
    else:
        checks.append({"check": "application-database-acceptance", "status": "unverified",
                   "detail": "Application-owned database and business acceptance tests are still required."})
    return {"version": 1, "environment": environment, "context": context, "revision": revision,
            "checked_at": datetime.now(timezone.utc).isoformat(), "images": images,
            "checks": checks, "acceptance": acceptance,
            "promotion_ready": environment == "staging" and all(c["status"] == "verified" for c in checks)}
