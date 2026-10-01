"""Local preflight. External commands use argument vectors, never shell input."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

from .runtime import check_service, docker
from .bootstrap import bootstrap
from .verify import verify
from .promote import promote
from .connect import connect
from .environments import generate_environments


class SpecError(ValueError):
    pass


def validate_config(name, config, migration=False, single_writer=False, frontend_type="static"):
    if not isinstance(config, dict):
        raise SpecError(f"{name}.config must be a mapping")
    allowed = {"env", "secrets", "db_env", "required_env"}
    allowed |= {"enabled", "command", "args"} if migration else {"port", "health_path", "ready_path", "migration"}
    if set(config) - allowed:
        raise SpecError(f"{name}: unknown configuration keys: {sorted(set(config) - allowed)}")
    port = config.get("port", 8080)
    if type(port) is not int or not 1 <= port <= 65535:
        raise SpecError(f"{name}.port must be an integer from 1 to 65535")
    for field in ("health_path", "ready_path"):
        path = config.get(field, "/")
        if not isinstance(path, str) or not path.startswith("/") or any(c.isspace() for c in path):
            raise SpecError(f"{name}.{field} must be an absolute HTTP path without whitespace")
    reserved = {"PORT", "DATABASE_URL", "SCHEDULER_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT"}
    if name == "frontend":
        reserved |= {"HOSTNAME", "NODE_ENV"}
    seen = set()
    for field in ("env", "secrets", "db_env"):
        values = config.get(field, {})
        if not isinstance(values, dict):
            raise SpecError(f"{name}.{field} must be a mapping")
        for key, value in values.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise SpecError(f"{name}.{field}: invalid environment variable name")
            if key in reserved or key in seen:
                raise SpecError(f"{name}.{key} duplicates another mapping or a platform-owned variable")
            if not isinstance(value, str):
                raise SpecError(f"{name}.{key}: quote configuration values as strings")
            if field == "db_env" and value not in {"host", "port", "dbname", "username", "password", "uri"}:
                raise SpecError(f"{name}.{key}: unknown database secret key {value}")
            if field == "secrets" and not value:
                raise SpecError(f"{name}.{key}: provide an Infisical key reference, not its value")
            seen.add(key)
    if name == "frontend" and (config.get("db_env") or "migration" in config):
        raise SpecError("frontend: database credentials and migrations belong to backend")
    required = config.get("required_env", [])
    if not isinstance(required, list) or any(not isinstance(k, str) for k in required):
        raise SpecError(f"{name}.required_env must be a list of variable names")
    # Reserved names prevent overrides, but only actually injected variables
    # can satisfy a required declaration (migration pods only get DATABASE_URL).
    injected = {"DATABASE_URL"} if migration else {"PORT"}
    if name == "backend":
        injected |= {"DATABASE_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"}
        if single_writer:
            injected.add("SCHEDULER_ENABLED")
    if name == "frontend" and frontend_type == "ssr":
        injected |= {"HOSTNAME", "NODE_ENV"}
    missing = set(required) - seen - injected
    if missing:
        raise SpecError(f"{name}: required variables without mappings: {sorted(missing)}")
    if migration:
        if type(config.get("enabled", True)) is not bool:
            raise SpecError(f"{name}.enabled must be a boolean")
        for field in ("command", "args"):
            if field in config and (not isinstance(config[field], list) or any(not isinstance(x, str) for x in config[field])):
                raise SpecError(f"{name}.{field} must be an argument list, not a shell string")
    elif "migration" in config:
        validate_config(name + ".migration", config["migration"], migration=True)


def read_spec(path):
    path = Path(path).resolve()
    spec = yaml.safe_load(path.read_text())
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise SpecError("spec must be a mapping with version: 1")
    answers = spec.get("answers", {})
    if not isinstance(answers, dict):
        raise SpecError("answers must be a mapping")
    services = spec.get("services")
    if not isinstance(services, dict) or not services:
        raise SpecError("services must contain backend and/or frontend")
    for name, service in services.items():
        if name not in {"backend", "frontend"} or not isinstance(service, dict):
            raise SpecError("supported service names: backend, frontend")
        repo = service.get("repo", "")
        if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise SpecError(f"{name}.repo must be owner/repository")
        if any(part in {".", ".."} for part in repo.split("/")):
            raise SpecError(f"{name}.repo must not contain traversal segments")
        checkout = service.get("checkout")
        if not isinstance(checkout, str) or not checkout:
            raise SpecError(f"{name}.checkout must identify a local checkout")
        root = (path.parent / checkout).resolve()
        context = service.get("context", ".")
        if not isinstance(context, str) or Path(context).is_absolute():
            raise SpecError(f"{name}.context must be a relative path")
        build = (root / context).resolve()
        if not build.is_relative_to(root):
            raise SpecError(f"{name}.context escapes its checkout")
        service["_root"] = root
        service["_build"] = build
        config = service.get("config", {})
        if not isinstance(config, dict):
            raise SpecError(f"{name}.config must be a mapping")
        config = dict(config)
        if name == "backend":
            config.setdefault("health_path", answers.get("backend_health_path", "/healthz"))
            config.setdefault("ready_path", answers.get("backend_ready_path", "/readyz"))
        service["config"] = config
        validate_config(name, config, single_writer=answers.get("cap_single_writer", False),
                        frontend_type=answers.get("frontend_type", "static"))
    return spec


def doctor(spec, *, runtime=False, env_files=None, migration_env_files=None, network=None,
           timeout=60, run_migrations=False):
    checks = []
    if runtime:
        try:
            version = docker("info", "--format", "{{.ServerVersion}}", timeout=10)
            if not version:
                raise ValueError("missing Docker server version")
            checks.append({"check": "docker.daemon", "status": "verified",
                           "detail": "Docker daemon responded to preflight."})
        except (OSError, subprocess.SubprocessError, ValueError):
            checks.append({"check": "docker.daemon", "status": "failed",
                           "detail": "Docker daemon did not respond within 10 seconds. Start Docker and check the selected Docker context/socket permissions; no builds were attempted."})
            runtime = False
    for name, service in spec["services"].items():
        dockerfile = service["_build"] / "Dockerfile"
        checks.append({"check": f"{name}.dockerfile", "status": "verified" if dockerfile.is_file() else "failed",
                       "detail": str(dockerfile)})
        if runtime and dockerfile.is_file():
            checks.extend(check_service(name, service, env_file=(env_files or {}).get(name),
                migration_env_file=(migration_env_files or {}).get(name), network=network,
                timeout=timeout, frontend_type=spec.get("answers", {}).get("frontend_type", "static"),
                run_migrations=run_migrations))
            continue
        # Source text cannot prove the final image's user, health, or migrations.
        for item in ("image-build", "non-root-user", "http-readiness", "configuration", "migration"):
            checks.append({"check": f"{name}.{item}", "status": "unverified",
                           "detail": "Requires container execution with the application's test configuration."})
    for tool in ("copier", "docker", "tofu", "kubectl", "helm", "gh"):
        executable = shutil.which(tool)
        checks.append({"check": f"tool.{tool}", "status": "configured" if executable else "failed",
                       "detail": executable or f"Install {tool}; executable not on PATH."})
    checks.append({"check": "live-integration", "status": "unverified",
                   "detail": "No live cluster checks performed. This report does not certify deployability."})
    return checks


def delivery_workflows(spec, answers):
    """One workflow per repo; monorepos get multiple jobs in the same file."""
    workflows = {}
    for name, service in spec["services"].items():
        language = service.get("language", "container")
        if language not in {"container", "node", "go"}:
            raise SpecError(f"{name}: language must be container, node, or go")
        branch = service.get("branch", "main")
        if (not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch)
                or ".." in branch or "//" in branch or branch.endswith(("/", ".", ".lock"))):
            raise SpecError(f"{name}: invalid delivery branch")
        workflow = workflows.setdefault(service["repo"], {
            "name": "deliver", "on": {"push": {"branches": [branch]}}, "jobs": {}})
        if workflow["on"]["push"]["branches"] != [branch]:
            raise SpecError("Services in one repository must use the same delivery branch")
        workflow["jobs"][name] = {
            "permissions": {"contents": "read", "packages": "write"},
            "uses": f"{answers['registry_org']}/{answers['platform_repo']}/.github/workflows/build-and-bump.yaml@main",
            "with": {"app": name, "language": language, "context": service.get("context", "."),
                     "image": f"ghcr.io/{answers['registry_org']}/{answers['client_name']}-{name}"},
            "secrets": {"deployer_app_id": "${{ secrets.DEPLOYER_APP_ID }}",
                        "deployer_private_key": "${{ secrets.DEPLOYER_PRIVATE_KEY }}"}}
    return workflows


def secret_inventory(platform):
    inventory = {}
    for path in sorted((platform / "clusters").rglob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict) or document.get("kind") != "ExternalSecret":
                continue
            for entry in document.get("spec", {}).get("data", []):
                key = entry.get("remoteRef", {}).get("key")
                if key:
                    inventory.setdefault(key, []).append(str(path.relative_to(platform)))
    return inventory


def onboard(spec, output, template):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise SpecError(f"output already exists: {output}; refusing to overwrite")
    answers = spec.get("answers")
    if not isinstance(answers, dict):
        raise SpecError("onboard requires an answers mapping of Copier answers")
    for key in ("client_name", "registry_org", "platform_repo", "domain", "acme_email", "cloud", "infisical_project_slug"):
        if not isinstance(answers.get(key), str) or not answers[key]:
            raise SpecError(f"answers.{key} is required")
    for key in ("registry_org", "platform_repo", "client_name"):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", answers[key]):
            raise SpecError(f"answers.{key} must be a repository-safe identifier")
    answers = dict(answers)
    answers["service_config"] = {name: service.get("config", {}) for name, service in spec["services"].items()}
    answers["app_backend"] = "backend" in spec["services"]
    answers["app_frontend"] = "frontend" in spec["services"]
    # The backend-off template is not yet gated correctly: don't claim support.
    if not answers["app_backend"]:
        raise SpecError("frontend-only onboarding is pending backend-off template support")
    workflows = delivery_workflows(spec, answers)
    for name, service in spec["services"].items():
        if not (service["_build"] / "Dockerfile").is_file():
            raise SpecError(f"{name}: missing Dockerfile at {service['_build']}")
    copier = shutil.which("copier")
    if not copier:
        raise SpecError("Install copier before onboarding")
    template = Path(template).resolve()
    if not (template / "copier.yml").is_file():
        raise SpecError("--template must identify a local platform-template checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".factory-", dir=output.parent) as temp:
        work = Path(temp)
        answer_file = work / "answers.yml"
        answer_file.write_text(yaml.safe_dump(answers))
        # Working tree is intentional: validation must exercise current code.
        subprocess.run([copier, "copy", "--vcs-ref=HEAD", "--defaults", "--data-file", str(answer_file),
                        str(template), str(work / "platform")], check=True, stdout=subprocess.DEVNULL)
        platform = work / "platform"
        generate_environments(platform, answers)
        for repo, workflow in workflows.items():
            destination = work / "connections" / repo / "deliver.yml"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(yaml.safe_dump(workflow, sort_keys=False))
        (work / "secrets-required.json").write_text(json.dumps({
            "platform_remote_keys": secret_inventory(platform),
            "app_secrets": {name: {"runtime": service.get("config", {}).get("secrets", {}),
                "migration": service.get("config", {}).get("migration", {}).get("secrets", {})}
                for name, service in spec["services"].items()},
            "github_caller_secrets": ["DEPLOYER_APP_ID", "DEPLOYER_PRIVATE_KEY"],
            "bootstrap_credentials": ["INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET", "GIT_TOKEN (private repos)"]}, indent=2) + "\n")
        (work / "readiness.json").write_text(json.dumps({"deployable": False,
            "checks": doctor(spec), "remaining": ["Container runtime verification",
                "Live acceptance"]}, indent=2) + "\n")
        # Move a completed bundle only; failed generation leaves no partial output.
        work.rename(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(prog="factory")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="Report local prerequisites and missing runtime evidence")
    check.add_argument("--spec", required=True, type=Path)
    check.add_argument("--json", action="store_true")
    check.add_argument("--runtime", action="store_true", help="Build and run disposable containers locally")
    check.add_argument("--env-file", action="append", default=[], metavar="SERVICE=PATH")
    check.add_argument("--migration-env-file", action="append", default=[], metavar="SERVICE=PATH")
    check.add_argument("--run-migrations", action="store_true", help="Execute migrations against your disposable test database")
    check.add_argument("--network", help="Existing Docker test network for app dependencies")
    check.add_argument("--timeout", type=int, default=60)
    setup = sub.add_parser("onboard", help="Generate a review bundle without touching app repos or infrastructure")
    setup.add_argument("--spec", required=True, type=Path)
    setup.add_argument("--output", required=True, type=Path)
    setup.add_argument("--template", required=True, type=Path)
    boot = sub.add_parser("bootstrap", help="Install GitOps into an explicit cluster from a published platform repo")
    boot.add_argument("--platform", required=True, type=Path)
    boot.add_argument("--environment", required=True, choices=["staging", "prod"])
    boot.add_argument("--context", required=True)
    live = sub.add_parser("verify", help="Collect read-only cluster and HTTPS evidence")
    live.add_argument("--platform", required=True, type=Path)
    live.add_argument("--environment", required=True, choices=["staging", "prod"])
    live.add_argument("--context", required=True)
    live.add_argument("--url", action="append", default=[])
    live.add_argument("--acceptance-suite", help="Committed executable relative to platform; runs app/database tests")
    promotion = sub.add_parser("promote", help="Prepare a verified staging-to-production branch and optionally publish its PR")
    promotion.add_argument("--platform", required=True, type=Path)
    promotion.add_argument("--context", required=True, help="Staging Kubernetes context")
    promotion.add_argument("--url", action="append", required=True)
    promotion.add_argument("--acceptance-suite", required=True)
    promotion.add_argument("--publish", action="store_true", help="Push the promotion branch and open a GitHub PR")
    connection = sub.add_parser("connect", help="Prepare caller workflow branches in app repositories")
    connection.add_argument("--spec", required=True, type=Path)
    connection.add_argument("--bundle", required=True, type=Path)
    connection.add_argument("--publish", action="store_true", help="Push branches and open GitHub PRs")
    args = parser.parse_args(argv)
    try:
        if args.command == "connect":
            spec = read_spec(args.spec)
            workflows = delivery_workflows(spec, spec["answers"])
            print(json.dumps(connect(spec, args.bundle, workflows, args.publish), indent=2))
            return 0
        if args.command == "promote":
            result = promote(args.platform, args.context, args.url, args.acceptance_suite, args.publish)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "verify":
            result = verify(args.platform, args.environment, args.context, args.url, args.acceptance_suite)
            print(json.dumps(result, indent=2))
            if any(c["status"] == "failed" for c in result["checks"]):
                return 1
            return 0 if all(c["status"] == "verified" for c in result["checks"]) else 3
        if args.command == "bootstrap":
            result = bootstrap(args.platform, args.environment, args.context)
            print(f"Bootstrap submitted to {result['context']} for {result['environment']}. Application reconciliation and live verification are still required.")
            return 0
        if args.command == "onboard":
            result = onboard(read_spec(args.spec), args.output, args.template)
            print(f"Generated review bundle: {result}. Read readiness.json before deployment.")
            return 0
        spec = read_spec(args.spec)
        def files(values):
            result = {}
            for entry in values:
                name, sep, value = entry.partition("=")
                if not sep or name not in spec["services"] or not Path(value).is_file():
                    raise SpecError("env file must be SERVICE=PATH with an existing file and service")
                result[name] = Path(value).resolve()
            return result
        if args.timeout <= 0:
            raise SpecError("timeout must be positive")
        checks = doctor(spec, runtime=args.runtime, env_files=files(args.env_file),
                        migration_env_files=files(args.migration_env_file), network=args.network,
                        timeout=args.timeout, run_migrations=args.run_migrations)
    except (ValueError, OSError, yaml.YAMLError, subprocess.SubprocessError) as error:
        print(f"factory: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"checks": checks}, indent=2))
    else:
        for item in checks:
            print(f"{item['status'].upper():10} {item['check']}: {item['detail']}")
    # 0 = fully verified; 1 = failure; 3 = incomplete evidence.
    return 1 if any(c["status"] == "failed" for c in checks) else 3


if __name__ == "__main__":
    sys.exit(main())
