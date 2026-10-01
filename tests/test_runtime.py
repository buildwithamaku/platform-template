import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from factory_cli.runtime import check_service, numeric_nonroot


class RuntimeTests(unittest.TestCase):
    def test_final_image_user(self):
        for value in ("", "root", "node", "0", "0:1000"):
            self.assertFalse(numeric_nonroot(value), value)
        for value in ("65532", "1000:1000"):
            self.assertTrue(numeric_nonroot(value), value)

    def fake_docker(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Config": {"User": "1000:1000"}}])
        if args[0] == "port":
            return "127.0.0.1:43123"
        return "container-id"

    @patch("factory_cli.runtime.probe", return_value=True)
    def test_custom_port_and_migration_entrypoint_with_cleanup(self, _):
        self.calls = []
        service = {"_build": Path("/tmp/app"), "config": {
            "port": 9100, "ready_path": "/ready", "health_path": "/live",
            "migration": {"command": ["node", "migrate.js"], "args": ["--apply"]}}}
        with patch("factory_cli.runtime.docker", side_effect=self.fake_docker):
            checks = check_service("backend", service, env_file=Path("runtime.env"),
                migration_env_file=Path("owner.env"), run_migrations=True)
        self.assertTrue(all(c["status"] == "verified" for c in checks))
        migration = next(c for c in self.calls if "--entrypoint" in c)
        self.assertEqual(migration[migration.index("--entrypoint") + 1], "node")
        self.assertEqual(migration[-2:], ("migrate.js", "--apply"))
        runtime = next(c for c in self.calls if "--detach" in c)
        self.assertIn("127.0.0.1::9100", runtime)
        self.assertNotIn("owner.env", runtime)
        self.assertEqual(len([c for c in self.calls if c[:2] == ("rm", "--force")]), 2)

    def test_frontend_checks_both_declared_http_probes(self):
        self.calls = []
        service = {"_build": Path("/tmp/app"), "config": {"ready_path": "/ready", "health_path": "/live"}}
        with patch("factory_cli.runtime.docker", side_effect=self.fake_docker), \
             patch("factory_cli.runtime.probe", return_value=True) as probe:
            check_service("frontend", service)
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         ["http://127.0.0.1:43123/ready", "http://127.0.0.1:43123/live"])

    def test_docker_error_does_not_disclose_captured_output(self):
        error = subprocess.CalledProcessError(1, ["docker"], stderr="password=SECRET")
        with patch("factory_cli.runtime.docker", side_effect=error):
            checks = check_service("backend", {"_build": Path("/tmp/app")})
        self.assertNotIn("SECRET", json.dumps(checks))
        self.assertEqual(checks[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
