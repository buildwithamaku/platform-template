import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from factory_cli.cli import SpecError, delivery_workflows, doctor, onboard, read_spec, validate_config


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app").mkdir()

    def spec(self, context="."):
        path = self.root / "factory.yaml"
        path.write_text(f"version: 1\nservices:\n  backend:\n    repo: example/api\n    checkout: app\n    context: {context}\n")
        return path

    def test_legacy_probe_answers_are_normalized_for_all_consumers(self):
        path = self.spec()
        path.write_text(path.read_text() + "answers:\n  backend_health_path: /api/live\n  backend_ready_path: /api/ready\n")
        config = read_spec(path)["services"]["backend"]["config"]
        self.assertEqual(config["health_path"], "/api/live")
        self.assertEqual(config["ready_path"], "/api/ready")

    def test_optional_injected_variables_require_the_capability(self):
        with self.assertRaisesRegex(SpecError, "without mappings"):
            validate_config("backend", {"required_env": ["SCHEDULER_ENABLED"]})
        validate_config("backend", {"required_env": ["SCHEDULER_ENABLED"]}, single_writer=True)
        validate_config("frontend", {"required_env": ["HOSTNAME"]}, frontend_type="ssr")

    def test_context_cannot_escape_checkout(self):
        with self.assertRaisesRegex(SpecError, "escapes"):
            read_spec(self.spec("../elsewhere"))

    def test_symlink_cannot_escape_checkout(self):
        (self.root / "app" / "outside").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(SpecError, "escapes"):
            read_spec(self.spec("outside"))

    def test_missing_dockerfile_is_failure(self):
        self.assertEqual(doctor(read_spec(self.spec()))[0]["status"], "failed")

    def test_existing_output_is_never_overwritten(self):
        with self.assertRaisesRegex(SpecError, "refusing to overwrite"):
            onboard({}, self.root, self.root)

    def test_repo_cannot_escape_workflow_directory(self):
        path = self.spec()
        path.write_text(path.read_text().replace("example/api", "../api"))
        with self.assertRaisesRegex(SpecError, "traversal"):
            read_spec(path)

    def test_monorepo_has_two_jobs_not_two_conflicting_files(self):
        spec = {"services": {
            "backend": {"repo": "example/app", "context": "backend"},
            "frontend": {"repo": "example/app", "context": "frontend"}}}
        answers = {"registry_org": "example", "platform_repo": "platform", "client_name": "demo"}
        generated = delivery_workflows(spec, answers)
        self.assertEqual(len(generated), 1)
        self.assertEqual(set(generated["example/app"]["jobs"]), {"backend", "frontend"})
        spec["services"]["frontend"]["repo"] = "example/web"
        self.assertEqual(len(delivery_workflows(spec, answers)), 2)

    def test_required_variables_must_exist_in_that_container(self):
        with self.assertRaisesRegex(SpecError, "without mappings"):
            validate_config("frontend", {"required_env": ["DATABASE_URL"]})
        with self.assertRaisesRegex(SpecError, "without mappings"):
            validate_config("backend.migration", {"required_env": ["PORT"]}, migration=True)

    def test_unresponsive_daemon_prevents_all_builds(self):
        (self.root / "app" / "Dockerfile").write_text("FROM scratch\nUSER 1000\n")
        with patch("factory_cli.cli.docker", side_effect=subprocess.TimeoutExpired("docker info", 10)) as daemon, \
             patch("factory_cli.cli.check_service") as build:
            checks = doctor(read_spec(self.spec()), runtime=True)
        self.assertEqual(checks[0]["check"], "docker.daemon")
        self.assertEqual(checks[0]["status"], "failed")
        daemon.assert_called_once()
        build.assert_not_called()
        self.assertTrue(any(c["check"] == "backend.image-build" and c["status"] == "unverified" for c in checks))

    def test_container_delivery_is_runtime_agnostic(self):
        answers = {"registry_org": "example", "platform_repo": "platform", "client_name": "demo"}
        spec = {"services": {"backend": {"repo": "example/python-app"}}}
        job = delivery_workflows(spec, answers)["example/python-app"]["jobs"]["backend"]
        self.assertEqual(job["with"]["language"], "container")
        spec["services"]["backend"]["language"] = "typo"
        with self.assertRaisesRegex(SpecError, "language must"):
            delivery_workflows(spec, answers)

    @patch("factory_cli.cli.shutil.which", return_value="/usr/bin/tool")
    def test_dockerfile_does_not_prove_runtime(self, _):
        (self.root / "app" / "Dockerfile").write_text("FROM scratch\nUSER 1000\n")
        checks = doctor(read_spec(self.spec()))
        self.assertEqual(checks[0]["status"], "verified")
        runtime = [c for c in checks if c["check"] == "backend.non-root-user"][0]
        self.assertEqual(runtime["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
