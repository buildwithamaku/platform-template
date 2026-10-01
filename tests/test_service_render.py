"""Render the actual template and inspect the deployment contract it emits."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from factory_cli.cli import secret_inventory, validate_config, SpecError
from factory_cli.environments import generate_environments


class ConfigValidation(unittest.TestCase):
    def test_requires_mapping_for_declared_configuration(self):
        with self.assertRaisesRegex(SpecError, "without mappings"):
            validate_config("backend", {"required_env": ["JWT_SECRET"]})

    def test_does_not_allow_overriding_owner_or_scheduler_credentials(self):
        with self.assertRaisesRegex(SpecError, "platform-owned"):
            validate_config("backend", {"secrets": {"DATABASE_URL": "OWNER_URL"}})

    def test_rejects_shell_migration_string(self):
        with self.assertRaisesRegex(SpecError, "argument list"):
            validate_config("backend", {"migration": {"command": "npm run migrate"}})


@unittest.skipUnless(shutil.which("copier"), "Copier required for render integration")
class ServiceRender(unittest.TestCase):
    def test_custom_contract_preserves_database_role_separation(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            answers = yaml.safe_load((root / "examples/all-caps.copier-answers.yml").read_text())
            answers["service_config"] = {
                "backend": {
                    "port": 9090, "health_path": "/alive", "ready_path": "/ready",
                    "env": {"DB_MIGRATIONS_RUN": "false"},
                    "secrets": {"JWT_SECRET": "PAYROLL_JWT"},
                    "db_env": {"DB_USERNAME": "username", "DB_PASSWORD": "password"},
                    "migration": {"command": ["npm"], "args": ["run", "migration:run"],
                                  "secrets": {"MIGRATION_KEY": "MIGRATION_KEY"}}},
                "frontend": {"port": 3333, "env": {"SERVER_LABEL": "production: #quoted"},
                             "secrets": {"SESSION_KEY": "SESSION_KEY"}}}
            path = tmp / "answers.yml"
            path.write_text(yaml.safe_dump(answers))
            output = tmp / "platform"
            subprocess.run(["copier", "copy", "--defaults", "--vcs-ref=HEAD", "--data-file", str(path),
                            str(root), str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def read(relative):
                return yaml.safe_load((output / relative).read_text())
            probes = (output / "e2e/tests/smoke.spec.ts").read_text()
            self.assertIn('request.get("/ready"', probes)
            self.assertNotIn("/api/widgets", probes)
            health = (output / "e2e/tests/api.spec.ts").read_text()
            self.assertIn('request.get("/alive"', health)
            self.assertNotIn("http_requests_total", health)
            if shutil.which("node"):
                subprocess.run(["node", "--check", str(output / "e2e/ci/mock-backend.js")], check=True)
            workflow = read(".github/workflows/build-and-bump.yaml")
            self.assertEqual(workflow["jobs"]["build"]["outputs"]["digest"], "${{ steps.build.outputs.digest }}")
            bump = workflow["jobs"]["bump"]["steps"][-1]
            self.assertIn("${IMAGE}=${IMAGE}@${DIGEST}", bump["run"])
            subprocess.run(["bash", "-n"], input=bump["run"], text=True, check=True)
            if shutil.which("kustomize"):
                image = f"ghcr.io/{answers['registry_org']}/{answers['client_name']}-backend"
                digest = "sha256:" + "a" * 64
                overlay = output / "clusters/apps/backend/overlays/staging"
                subprocess.run(["kustomize", "edit", "set", "image", f"{image}={image}@{digest}"],
                               cwd=overlay, check=True, capture_output=True)
                built = subprocess.run(["kustomize", "build", str(overlay)],
                                       check=True, capture_output=True, text=True)
                for doc in yaml.safe_load_all(built.stdout):
                    if doc and doc.get("kind") in {"Deployment", "Job"}:
                        for container in doc["spec"]["template"]["spec"]["containers"]:
                            if container["image"].startswith(image):
                                self.assertEqual(container["image"], f"{image}@{digest}")
            backend = read("clusters/apps/backend/base/deployment.yaml")["spec"]["template"]["spec"]["containers"][0]
            env = {e["name"]: e for e in backend["env"]}
            self.assertEqual(backend["ports"][0]["containerPort"], 9090)
            self.assertEqual(backend["livenessProbe"]["httpGet"]["path"], "/alive")
            self.assertEqual(env["DB_MIGRATIONS_RUN"]["value"], "false")
            self.assertTrue(env["DB_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"].endswith("-app-rw"))
            migration = read("clusters/apps/backend/base/migration-job.yaml")["spec"]["template"]["spec"]["containers"][0]
            self.assertEqual(migration["command"], ["npm"])
            self.assertEqual(migration["args"], ["run", "migration:run"])
            self.assertTrue(migration["env"][0]["valueFrom"]["secretKeyRef"]["name"].endswith("-db-app"))
            self.assertNotEqual(backend["envFrom"], migration["envFrom"])
            self.assertIn("PAYROLL_JWT", secret_inventory(output))
            recorded = read(".copier-answers.yml")
            self.assertEqual(recorded["service_config"], answers["service_config"])
            answers["infisical_project_slug"] = "independent-project"
            generate_environments(output, answers)
            for env in ("staging", "prod"):
                docs = list(yaml.safe_load_all((output / f"clusters/environments/{env}/applications.yaml").read_text()))
                apps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Application"}
                self.assertEqual(apps["backend"]["spec"]["source"]["path"], f"clusters/apps/backend/overlays/{env}")
                dns = yaml.safe_load(apps["external-dns"]["spec"]["source"]["helm"]["values"])
                self.assertEqual(dns["txtOwnerId"], f"capsclient-{env}")
                if shutil.which("kustomize"):
                    # Every Git-sourced Application must actually build, not just
                    # contain a plausible path in the app-of-apps manifest.
                    for app in apps.values():
                        source = app["spec"]["source"]
                        if "path" not in source:
                            continue
                        build = subprocess.run(["kustomize", "build", str(output / source["path"])],
                                               check=True, capture_output=True, text=True)
                        resources = [d for d in yaml.safe_load_all(build.stdout) if d]
                        if app["metadata"]["name"] == "infisical-store":
                            store = next(d for d in resources if d["kind"] == "ClusterSecretStore")
                            scope = store["spec"]["provider"]["infisical"]["secretsScope"]
                            self.assertEqual(scope["environmentSlug"], env)
                            self.assertEqual(scope["projectSlug"], "independent-project")
                        if app["metadata"]["name"] == "database":
                            cluster = next(d for d in resources if d["kind"] == "Cluster")
                            self.assertTrue(cluster["spec"]["backup"]["barmanObjectStore"]["destinationPath"].endswith("/" + env))
            # The off path must remove both the job and its resource reference.
            answers["service_config"]["backend"]["migration"]["enabled"] = False
            path.write_text(yaml.safe_dump(answers))
            output = tmp / "no-migration"
            subprocess.run(["copier", "copy", "--defaults", "--vcs-ref=HEAD", "--data-file", str(path),
                            str(root), str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertFalse((output / "clusters/apps/backend/base/migration-job.yaml").exists())
            self.assertNotIn("migration-job.yaml", read("clusters/apps/backend/base/kustomization.yaml")["resources"])


if __name__ == "__main__":
    unittest.main()
