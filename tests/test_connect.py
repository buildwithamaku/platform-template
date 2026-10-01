from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from factory_cli.cli import delivery_workflows, SpecError
from factory_cli.connect import connect


class ConnectTests(unittest.TestCase):
    def test_monorepo_services_must_agree_on_branch(self):
        spec = {"services": {"backend": {"repo": "example/app", "branch": "main"},
                             "frontend": {"repo": "example/app", "branch": "release"}}}
        answers = {"registry_org": "example", "platform_repo": "platform", "client_name": "demo"}
        with self.assertRaisesRegex(SpecError, "same delivery branch"):
            delivery_workflows(spec, answers)
        spec["services"]["backend"]["branch"] = "release"
        workflows = delivery_workflows(spec, answers)
        self.assertEqual(workflows["example/app"]["on"]["push"]["branches"], ["release"])

    @unittest.skipUnless(shutil.which("git"), "Git required")
    def test_connect_prepares_one_workflow_without_changing_user_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            root = base / "app"
            root.mkdir()

            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

            git("init", "-b", "main")
            git("config", "user.name", "Factory test")
            git("config", "user.email", "factory@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("remote", "add", "origin", "https://github.com/example/app.git")
            (root / "README.md").write_text("app\n")
            git("add", ".")
            git("commit", "-m", "Fixture")
            revision = git("rev-parse", "HEAD")
            (root / "README.md").write_text("user's unfinished work\n")
            spec = {"services": {name: {"repo": "example/app", "_root": root, "context": name}
                                 for name in ("backend", "frontend")}}
            answers = {"registry_org": "example", "platform_repo": "platform", "client_name": "demo"}
            workflows = delivery_workflows(spec, answers)
            bundle = base / "bundle"
            source = bundle / "connections/example/app/deliver.yml"
            source.parent.mkdir(parents=True)
            source.write_text(yaml.safe_dump(workflows["example/app"], sort_keys=False))
            actual_run = subprocess.run

            def run(command, **kwargs):
                if command[:3] == ("git", "fetch", "origin"):
                    command = ("git", "fetch", ".", command[3])
                return actual_run(command, **kwargs)

            with patch("factory_cli.connect.subprocess.run", side_effect=run):
                results = connect(spec, bundle, workflows)
            self.assertEqual(len(results), 1)
            branch = results[0]["branch"]
            self.assertEqual(git("rev-parse", "HEAD"), revision)
            self.assertEqual((root / "README.md").read_text(), "user's unfinished work\n")
            self.assertEqual(git("diff", "--name-only", "main", branch), ".github/workflows/factory-deliver.yml")
            workflow = yaml.safe_load(git("show", f"{branch}:.github/workflows/factory-deliver.yml"))
            self.assertEqual(set(workflow["jobs"]), {"backend", "frontend"})
            self.assertEqual(len(git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

            source.write_text("stale: workflow\n")
            with patch("factory_cli.connect.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "differs from specification"):
                    connect(spec, bundle, workflows)
                run.assert_not_called()
