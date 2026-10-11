import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from factory_cli.acceptance import run_acceptance


class AcceptanceTests(unittest.TestCase):
    def run_suite(self, mutation="", exit_code=0, requires_database=True):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "acceptance.py"
            script.write_text(f"#!{sys.executable}\n" + '''import json, sys
target = json.load(sys.stdin)
report = dict(target, checks=[
    {"check": "application", "status": "passed", "assertions": 2},
    {"check": "database", "status": "passed", "assertions": 1}],
    private_output="secret-must-not-escape")
''' + mutation + f'\nprint(json.dumps(report))\nsys.exit({exit_code})\n')
            script.chmod(0o700)
            actual_run = subprocess.run

            def run(command, **kwargs):
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout="acceptance.py")
                return actual_run(command, **kwargs)

            with patch("factory_cli.acceptance.subprocess.run", side_effect=run):
                return run_acceptance(root, "acceptance.py", {
                    "version": 1, "environment": "staging", "context": "test", "revision": "abc",
                    "requires_database": requires_database})

    def test_real_process_protocol_and_redacted_evidence(self):
        result = self.run_suite()
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["sha256"]), 64)
        self.assertNotIn("secret-must-not-escape", json.dumps(result))

    def test_empty_database_assertions_are_not_acceptance(self):
        self.assertFalse(self.run_suite('report["checks"][1]["assertions"] = 0')["passed"])

    def test_wrong_target_or_failing_exit_invalidates_report(self):
        self.assertFalse(self.run_suite('report["revision"] = "old"')["passed"])
        self.assertFalse(self.run_suite(exit_code=1)["passed"])

    def test_malformed_check_does_not_crash_or_pass(self):
        self.assertFalse(self.run_suite('report["checks"] = [None, None]')["passed"])

    def test_database_can_only_be_inapplicable_when_platform_has_none(self):
        mutation = 'report["checks"][1].update(status="not_applicable", assertions=0)'
        self.assertFalse(self.run_suite(mutation)["passed"])
        result = self.run_suite(mutation, requires_database=False)
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks"][1]["status"], "not_applicable")
