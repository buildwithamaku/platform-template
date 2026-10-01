"""Execute a reviewed, committed application acceptance entrypoint."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def run_acceptance(platform, suite, target):
    platform = Path(platform).resolve()
    relative = Path(suite)
    script = (platform / relative).resolve()
    if relative.is_absolute() or not script.is_relative_to(platform) or not script.is_file():
        raise ValueError("Acceptance suite must be a file within the platform checkout")
    if not os.access(script, os.X_OK):
        raise ValueError("Acceptance entrypoint must be executable and have an interpreter shebang")
    subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(relative)],
                   cwd=platform, check=True, capture_output=True, text=True)
    fingerprint = hashlib.sha256(script.read_bytes()).hexdigest()
    result = {"path": str(relative), "sha256": fingerprint, "checks": []}
    try:
        process = subprocess.run([str(script)], cwd=platform,
            input=json.dumps(target), text=True, capture_output=True, timeout=300,
            env=dict(os.environ, FACTORY_KUBE_CONTEXT=target["context"],
                     PLATFORM_ENVIRONMENT=target["environment"]))
        report = json.loads(process.stdout)
        checks = report.get("checks", [])
        def passed(check):
            count = check.get("assertions")
            if type(count) is not int:
                return False
            if check.get("check") == "database" and not target.get("requires_database", True):
                if check.get("status") == "not_applicable" and count == 0:
                    return True
            return check.get("status") == "passed" and count > 0

        valid = (process.returncode == 0 and report.get("version") == 1
                 and report.get("revision") == target["revision"]
                 and report.get("environment") == target["environment"]
                 and report.get("context") == target["context"]
                 and isinstance(checks, list) and len(checks) == 2
                 and {c.get("check") for c in checks} == {"application", "database"}
                 and all(passed(c) for c in checks))
        if not valid:
            raise ValueError("Acceptance report is incomplete or failing")
        # Whitelist output: test logs, response bodies and arbitrary fields may
        # contain credentials or application data and must not enter evidence.
        result["checks"] = [{"check": c["check"], "status": c["status"], "assertions": c["assertions"]} for c in checks]
        result["passed"] = True
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        result["passed"] = False
    return result
