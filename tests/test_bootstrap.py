import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from factory_cli.bootstrap import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "clusters/bootstrap").mkdir(parents=True)
        (self.root / "clusters/environments/staging").mkdir(parents=True)
        (self.root / "clusters/bootstrap/app-of-apps.yaml").write_text(
            'spec:\n  source:\n    path: clusters/environments/__ENVIRONMENT__\n')
        (self.root / "clusters/environments/staging/applications.yaml").write_text("")
        (self.root / "bootstrap.sh").write_text("#!/bin/bash\n")
        (self.root / ".copier-answers.yml").write_text("registry_org: example\nplatform_repo: platform\n")
        self.dirty = False
        self.existing_environment = None
        self.commands = []

    def fake_run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        output = ""
        if command[:3] == ("git", "rev-parse", "--show-toplevel"):
            output = str(self.root)
        elif command[:2] == ("git", "status"):
            output = " M dirty" if self.dirty else ""
        elif command[:2] == ("git", "rev-parse"):
            output = "a" * 40
        elif command[:2] == ("git", "remote"):
            output = "git@github.com:example/platform.git"
        elif command[:2] == ("git", "ls-remote"):
            output = "a" * 40 + "\trefs/heads/main"
        elif "crd" in command:
            output = "applications.argoproj.io" if self.existing_environment else ""
        elif "applications.argoproj.io" in command:
            output = json.dumps({"spec": {"source": {"repoURL": "https://github.com/example/platform.git", "path": "clusters/environments/" + self.existing_environment}}})
        return subprocess.CompletedProcess(command, 0, stdout=output)

    def execute(self):
        with patch.dict(os.environ, {"INFISICAL_CLIENT_ID": "test", "INFISICAL_CLIENT_SECRET": "test"}), \
             patch("factory_cli.bootstrap.shutil.which", return_value="/tool"), \
             patch("factory_cli.bootstrap.subprocess.run", side_effect=self.fake_run):
            return bootstrap(self.root, "staging", "explicit-context")

    def test_fresh_cluster_pins_context_without_requiring_argo_crd(self):
        result = self.execute()
        self.assertEqual(result["context"], "explicit-context")
        command, kwargs = self.commands[-1]
        self.assertEqual(command, ["bash", str(self.root / "bootstrap.sh")])
        self.assertEqual(kwargs["env"]["FACTORY_KUBE_CONTEXT"], "explicit-context")
        self.assertEqual(kwargs["env"]["PLATFORM_REPO_URL"], "https://github.com/example/platform.git")
        self.assertFalse(any("applications.argoproj.io" in c and "crd" not in c for c, _ in self.commands))

    def test_dirty_platform_is_refused_before_contacting_cluster(self):
        self.dirty = True
        with self.assertRaisesRegex(ValueError, "Commit and publish"):
            self.execute()
        self.assertFalse(any(c[0] in {"kubectl", "bash"} for c, _ in self.commands))

    def test_other_environment_is_never_overwritten(self):
        self.existing_environment = "prod"
        with self.assertRaisesRegex(ValueError, "different environment"):
            self.execute()
        self.assertFalse(any(isinstance(c, list) for c, _ in self.commands))

    def test_same_environment_can_be_bootstrapped_again(self):
        self.existing_environment = "staging"
        self.assertEqual(self.execute()["environment"], "staging")
