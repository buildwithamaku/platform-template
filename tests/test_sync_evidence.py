from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from factory_cli.verify import same_application_at_revision


@unittest.skipUnless(shutil.which("git") and shutil.which("kustomize"), "Git and Kustomize required")
class SyncEvidenceTests(unittest.TestCase):
    def test_unrelated_commit_is_accepted_but_changed_hook_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            def run(*args):
                return subprocess.run(args, cwd=root, check=True, text=True, capture_output=True).stdout.strip()

            run("git", "init", "-b", "main")
            run("git", "config", "user.name", "Factory test")
            run("git", "config", "user.email", "factory@example.invalid")
            run("git", "config", "commit.gpgsign", "false")
            path = "clusters/apps/backend/overlays/staging"
            overlay = root / path
            overlay.mkdir(parents=True)
            (overlay / "kustomization.yaml").write_text(yaml.safe_dump({
                "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                "resources": ["hook.yaml"]}))
            hook = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "test"},
                    "spec": {"template": {"spec": {"restartPolicy": "Never", "containers": [
                        {"name": "test", "image": "example/test@sha256:" + "a" * 64, "args": ["original"]}]}}}}
            (overlay / "hook.yaml").write_text(yaml.safe_dump(hook))
            run("git", "add", ".")
            run("git", "commit", "-m", "Original sync")
            revision = run("git", "rev-parse", "HEAD")
            (root / "README.md").write_text("An unrelated documentation change\n")
            run("git", "add", ".")
            run("git", "commit", "-m", "Unrelated change")
            rendered = run("kustomize", "build", str(overlay))
            self.assertTrue(same_application_at_revision(root, path, revision, rendered))
            hook["spec"]["template"]["spec"]["containers"][0]["args"] = ["changed"]
            (overlay / "hook.yaml").write_text(yaml.safe_dump(hook))
            changed = run("kustomize", "build", str(overlay))
            self.assertFalse(same_application_at_revision(root, path, revision, changed))
            self.assertFalse(same_application_at_revision(root, path, "missing", rendered))
            self.assertFalse(same_application_at_revision(root, str(overlay), revision, rendered))
