import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from factory_cli.cli import onboard, read_spec


@unittest.skipUnless(shutil.which("copier") and shutil.which("kustomize"), "Copier and Kustomize required")
class FrontendOnlyTests(unittest.TestCase):
    def test_full_onboarding_omits_backend_and_database_dependencies(self):
        template = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "web"
            app.mkdir()
            (app / "Dockerfile").write_text("FROM scratch\nUSER 1000\n")
            answers = yaml.safe_load((template / "examples/baremetal.copier-answers.yml").read_text())
            answers.update(infisical_project_slug="frontend-test", app_metabase=False)
            spec_file = root / "onboarding.yaml"
            spec_file.write_text(yaml.safe_dump({"version": 1, "answers": answers,
                "services": {"frontend": {"repo": "example/web", "checkout": "web",
                    "config": {"ready_path": "/status"}}}}))
            actual_run = subprocess.run

            def quiet(command, **kwargs):
                if Path(command[0]).name == "copier":
                    kwargs["stderr"] = subprocess.PIPE
                return actual_run(command, **kwargs)

            with patch("factory_cli.cli.subprocess.run", side_effect=quiet):
                bundle = onboard(read_spec(spec_file), root / "bundle", template)
            platform = bundle / "platform"
            self.assertFalse((platform / "clusters/apps/backend").exists())
            self.assertFalse((platform / "clusters/platform-config/database").exists())
            self.assertFalse((platform / "e2e").exists())
            self.assertFalse((platform / ".github/workflows/e2e-image.yaml").exists())
            saved = yaml.safe_load((platform / ".copier-answers.yml").read_text())
            self.assertFalse(saved["app_backend"])
            self.assertTrue(saved["app_frontend"])
            self.assertEqual(saved["staging_tls_issuer"], "letsencrypt-prod")
            workflow = yaml.safe_load((bundle / "connections/example/web/deliver.yml").read_text())
            self.assertEqual(set(workflow["jobs"]), {"frontend"})
            readiness = json.loads((bundle / "readiness.json").read_text())
            self.assertFalse(readiness["deployable"])
            for env in ("staging", "prod"):
                docs = list(yaml.safe_load_all((platform / f"clusters/environments/{env}/applications.yaml").read_text()))
                apps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Application"}
                self.assertIn("frontend", apps)
                self.assertFalse({"backend", "database", "cloudnative-pg"} & apps.keys())
                for application in apps.values():
                    source = application["spec"]["source"]
                    if "path" not in source:
                        continue
                    built = subprocess.run(["kustomize", "build", str(platform / source["path"])],
                                           capture_output=True, text=True, check=True)
                    resources = [d for d in yaml.safe_load_all(built.stdout) if d]
                    self.assertFalse(any(d.get("metadata", {}).get("namespace") == "data" for d in resources))
                    if application["metadata"]["name"] in {"frontend", "demo"}:
                        ingress = next(d for d in resources if d.get("kind") == "Ingress")
                        self.assertEqual(ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"], "letsencrypt-prod")
                    if application["metadata"]["name"] == "gatus":
                        configmap = next(d for d in yaml.safe_load_all(built.stdout) if d and d.get("kind") == "ConfigMap")
                        config = yaml.safe_load(configmap["data"]["config.yaml"])
                        urls = [endpoint["url"] for endpoint in config["endpoints"]]
                        self.assertIn("http://frontend.frontend.svc/status", urls)
                        self.assertFalse(any("backend.data.svc" in url for url in urls))
