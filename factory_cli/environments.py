"""Generate explicit environment roots over shared GitOps components."""
import copy
import os
from pathlib import Path

import yaml


def write_yaml(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def resource_patch(document, operations):
    return {"target": {"group": document["apiVersion"].split("/")[0] if "/" in document["apiVersion"] else "",
                       "version": document["apiVersion"].split("/")[-1], "kind": document["kind"],
                       "name": document["metadata"]["name"]},
            "patch": yaml.safe_dump(operations, sort_keys=False)}


def generate_environments(platform, answers):
    """Called on a fresh render, before publication, never against a live cluster.

    App delivery still changes shared app overlays. Environment roots isolate
    platform configuration while referencing those overlays without copying them.
    """
    applications = []
    for path in sorted((platform / "clusters/platform").glob("*.yaml")):
        applications.extend(d for d in yaml.safe_load_all(path.read_text()) if d)
    for env in ("staging", "prod"):
        root = platform / "clusters/environments" / env
        rendered = []
        for original in applications:
            doc = copy.deepcopy(original)
            # Previews belong to staging; never mirror them on production.
            if env == "prod" and doc["kind"] != "Application":
                continue
            if doc["kind"] != "Application":
                rendered.append(doc)
                continue
            name = doc["metadata"]["name"]
            source = doc["spec"]["source"]
            if "path" in source:
                path = source["path"]
                if path.endswith("/overlays/staging"):
                    source["path"] = path.removesuffix("staging") + env
                else:
                    base = platform / path
                    # Directory sources need a Kustomization before they can be
                    # shared by overlays. Enumerate only direct manifests, as Argo
                    # did before (no recursive ingestion of generated overlays).
                    kustomization = base / "kustomization.yaml"
                    resources = sorted(p.name for p in base.glob("*.yaml") if p.name != "kustomization.yaml")
                    if not kustomization.exists():
                        write_yaml(kustomization, {"apiVersion": "kustomize.config.k8s.io/v1beta1",
                            "kind": "Kustomization", "resources": resources})
                    component = root / "components" / name
                    config = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                              "resources": [os.path.relpath(base, component)], "patches": []}
                    for file in resources:
                        for resource in yaml.safe_load_all((base / file).read_text()):
                            if not resource or "kind" not in resource:
                                continue
                            ops = []
                            if resource["kind"] == "ClusterSecretStore":
                                ops = [
                                    {"op": "replace", "path": "/spec/provider/infisical/secretsScope/projectSlug", "value": answers["infisical_project_slug"]},
                                    {"op": "replace", "path": "/spec/provider/infisical/secretsScope/environmentSlug", "value": env}]
                            if resource["kind"] == "Cluster" and resource["apiVersion"].startswith("postgresql.cnpg.io/"):
                                backup = resource.get("spec", {}).get("backup", {}).get("barmanObjectStore")
                                if backup:
                                    ops.append({"op": "replace", "path": "/spec/backup/barmanObjectStore/destinationPath",
                                                "value": backup["destinationPath"].rstrip("/") + "/" + env})
                            if resource["kind"] == "Namespace" and "env" in resource["metadata"].get("labels", {}):
                                ops.append({"op": "replace", "path": "/metadata/labels/env", "value": env})
                            if resource["kind"] == "Ingress":
                                updated = copy.deepcopy(resource["spec"])
                                annotations = resource["metadata"].get("annotations", {})
                                if updated.get("ingressClassName") == "tailscale":
                                    host = f"{answers['client_name']}-{env}-{resource['metadata']['name']}"
                                    for tls in updated.get("tls", []):
                                        tls["hosts"] = [host]
                                    ops.append({"op": "add", "path": "/metadata/annotations/tailscale.com~1hostname", "value": host})
                                elif name == "demo":
                                    host = f"test{'.staging' if env == 'staging' else ''}.{answers['domain']}"
                                    for rule in updated.get("rules", []):
                                        rule["host"] = host
                                    for tls in updated.get("tls", []):
                                        tls["hosts"] = [host]
                                    ops.append({"op": "add", "path": "/metadata/annotations/cert-manager.io~1cluster-issuer",
                                                "value": answers.get("staging_tls_issuer", "letsencrypt-staging") if env == "staging" else "letsencrypt-prod"})
                                if updated != resource["spec"]:
                                    ops.append({"op": "replace", "path": "/spec", "value": updated})
                            if ops:
                                config["patches"].append(resource_patch(resource, ops))
                    write_yaml(component / "kustomization.yaml", config)
                    source["path"] = str(component.relative_to(platform))
                    source.pop("directory", None)
            else:
                helm = source.get("helm", {})
                values = yaml.safe_load(helm.get("values", "{}")) or {}
                if name == "external-dns":
                    values["txtOwnerId"] = f"{answers['client_name']}-{env}"
                if name == "ingress-nginx" and answers["cloud"] == "hetzner":
                    annotations = values["controller"]["service"]["annotations"]
                    annotations["load-balancer.hetzner.cloud/name"] = f"{answers['client_name']}-{env}-ingress"
                    annotations["load-balancer.hetzner.cloud/location"] = answers.get("region", "nbg1")
                if name == "tailscale-operator":
                    values.setdefault("operatorConfig", {})["hostname"] = f"{answers['client_name']}-{env}-operator"
                if name == "kube-prometheus-stack":
                    ingress = values.get("grafana", {}).get("ingress", {})
                    if ingress:
                        hostname = f"{answers['client_name']}-{env}-grafana"
                        ingress["hosts"] = [hostname]
                        for tls in ingress.get("tls", []):
                            tls["hosts"] = [hostname]
                if values:
                    source.setdefault("helm", {})["values"] = yaml.safe_dump(values, sort_keys=False)
            rendered.append(doc)
        root.mkdir(parents=True, exist_ok=True)
        (root / "applications.yaml").write_text(yaml.safe_dump_all(rendered, sort_keys=False))
    bootstrap = platform / "clusters/bootstrap/app-of-apps.yaml"
    root_app = yaml.safe_load(bootstrap.read_text())
    root_app["spec"]["source"]["path"] = "clusters/environments/__ENVIRONMENT__"
    write_yaml(bootstrap, root_app)
