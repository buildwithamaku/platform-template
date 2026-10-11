import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from factory_cli.verify import deployment_ready, reconciled, verify


class EvidenceTests(unittest.TestCase):
    def deployment(self):
        return {"apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": "backend", "namespace": "data", "generation": 3},
                "spec": {"replicas": 2, "template": {"spec": {"containers": [
                    {"name": "backend", "image": "ghcr.io/example/backend@sha256:" + "a" * 64}]}}},
                "status": {"observedGeneration": 3, "replicas": 2, "updatedReplicas": 2,
                           "readyReplicas": 2, "availableReplicas": 2}}

    def application(self):
        return {"kind": "Application", "metadata": {"name": "backend"},
                "spec": {"source": {"repoURL": "https://github.com/example/platform.git",
                                    "path": "clusters/apps/backend/overlays/staging", "targetRevision": "main"}},
                "status": {"sync": {"status": "Synced", "revision": "abc"},
                           "health": {"status": "Healthy"},
                           "operationState": {"phase": "Succeeded", "syncResult": {"revision": "abc"}}}}

    def test_previous_healthy_replicas_do_not_prove_new_rollout(self):
        deployment = self.deployment()
        self.assertTrue(deployment_ready(deployment))
        deployment["status"]["observedGeneration"] = 2
        self.assertFalse(deployment_ready(deployment))
        deployment["status"]["observedGeneration"] = 3
        deployment["status"]["updatedReplicas"] = 1
        self.assertFalse(deployment_ready(deployment))

    def test_zero_replicas_are_not_a_running_app(self):
        deployment = self.deployment()
        deployment["spec"]["replicas"] = 0
        self.assertFalse(deployment_ready(deployment))

    def test_failed_or_pending_operation_blocks_verification(self):
        app = self.application()
        self.assertTrue(reconciled(app, "abc"))
        app["status"]["operationState"]["phase"] = "Failed"
        self.assertFalse(reconciled(app, "abc"))
        app["status"]["operationState"]["phase"] = "Succeeded"
        app["status"]["operationState"]["syncResult"]["revision"] = "old"
        self.assertTrue(reconciled(app, "abc"))  # unchanged apps need no new sync
        app["operation"] = {"sync": {"revision": "abc"}}
        self.assertFalse(reconciled(app, "abc"))
        app.pop("operation")
        app["status"]["sync"]["revision"] = "old"
        self.assertFalse(reconciled(app, "abc"))

    def test_health_evidence_does_not_claim_database_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "clusters/environments/staging"
            path.mkdir(parents=True)
            (root / ".copier-answers.yml").write_text("registry_org: example\nplatform_repo: platform\n")
            app = self.application()
            (path / "applications.yaml").write_text(yaml.safe_dump(app))
            commands = []
            drift = False

            def run(command, **kwargs):
                commands.append(command)
                if command[:3] == ("git", "rev-parse", "--show-toplevel"):
                    output = str(root)
                elif command[:2] == ("git", "status"):
                    output = ""
                elif command[0] == "git":
                    output = "abc"
                elif command[0] == "kustomize":
                    output = yaml.safe_dump_all([self.deployment(), {"kind": "Ingress", "spec": {
                        "rules": [{"host": "app.staging.example.com"}]}}])
                elif "deployment" in command:
                    deployment = self.deployment()
                    if drift:
                        deployment["status"]["updatedReplicas"] = 1
                    output = json.dumps(deployment)
                else:
                    live = copy.deepcopy(app)
                    if "platform-root" in command:
                        live["spec"]["source"]["path"] = "clusters/environments/staging"
                    output = json.dumps(live)
                return subprocess.CompletedProcess(command, 0, stdout=output)

            with patch("factory_cli.verify.subprocess.run", side_effect=run):
                result = verify(root, "staging", "test-context", [])
            self.assertFalse(result["promotion_ready"])
            states = {check["check"]: check["status"] for check in result["checks"]}
            self.assertEqual(states["deployment.data/backend"], "verified")
            self.assertEqual(states["application-database-acceptance"], "unverified")
            self.assertEqual(states["public-https"], "unverified")
            for command in commands:
                if command[0] == "kubectl":
                    self.assertEqual(command[1:3], ("--context", "test-context"))
                    self.assertIn("get", command)

            with patch("factory_cli.verify.subprocess.run", side_effect=run), \
                 patch("factory_cli.verify.https_probe", return_value=True), \
                 patch("factory_cli.verify.run_acceptance", return_value={"passed": True}):
                result = verify(root, "staging", "test-context", ["https://app.staging.example.com/"], "suite")
            self.assertTrue(result["promotion_ready"])

            def suite_with_concurrent_rollout(*args):
                nonlocal drift
                drift = True
                return {"passed": True}

            with patch("factory_cli.verify.subprocess.run", side_effect=run), \
                 patch("factory_cli.verify.https_probe", return_value=True), \
                 patch("factory_cli.verify.run_acceptance", side_effect=suite_with_concurrent_rollout):
                result = verify(root, "staging", "test-context", ["https://app.staging.example.com/"], "suite")
            self.assertFalse(result["promotion_ready"])
            self.assertEqual(result["checks"][-1]["check"], "stable-acceptance-target")
            self.assertEqual(result["checks"][-1]["status"], "failed")
