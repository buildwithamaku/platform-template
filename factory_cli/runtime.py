"""Disposable Docker compatibility checks; no cluster or registry mutations."""
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], check=True, capture_output=True,
                          text=True, timeout=timeout).stdout.strip()


def numeric_nonroot(user):
    uid = user.split(":", 1)[0]
    return uid.isdecimal() and int(uid) > 0


def probe(url, deadline):
    # Never send local requests through a proxy from the caller's environment.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with client.open(url, timeout=2) as response:
                if 200 <= response.status < 400:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    return False


def check_service(name, service, *, env_file=None, migration_env_file=None,
                  network=None, timeout=60, frontend_type="ssr", run_migrations=False):
    checks = []
    config = service.get("config", {})
    port = config.get("port", 8080 if name == "backend" or frontend_type == "static" else 3000)
    ident = "factory-check-" + uuid.uuid4().hex
    image = ident + ":local"
    containers = []

    def record(item, status, detail):
        checks.append({"check": f"{name}.{item}", "status": status, "detail": detail})

    def env_args(values, file):
        args = []
        if file:
            args += ["--env-file", str(file)]
        for key, value in values.items():
            args += ["--env", f"{key}={value}"]
        if network:
            args += ["--network", network]
        return args

    stage = "image-build"
    try:
        docker("build", "--tag", image, str(service["_build"]), timeout=900)
        record(stage, "verified", "Docker build succeeded locally; image not pushed.")
        stage = "non-root-user"
        info = json.loads(docker("image", "inspect", image))[0]
        uid = config.get("run_as_user")
        if uid is not None and (type(uid) is not int or uid <= 0):
            record(stage, "failed", "Configured runtime UID must be a positive integer.")
            return checks
        if uid is None and not numeric_nonroot(info["Config"].get("User", "")):
            record(stage, "failed", "Image needs a numeric nonzero USER or an explicit run_as_user override.")
            return checks
        record(stage, "verified", "Configured numeric nonzero UID will be enforced." if uid else "Built image declares a numeric nonzero USER.")
        migration = config.get("migration", {})
        if name == "backend" and migration.get("enabled", True):
            stage = "migration"
            if not run_migrations:
                record(stage, "unverified", "Use --run-migrations with a disposable database and separate migration env file.")
            elif not migration_env_file:
                record(stage, "failed", "A separate --migration-env-file backend=PATH is required.")
                return checks
            else:
                migration_id = ident + "-migration"
                containers.append(migration_id)
                command = migration.get("command", [])
                args = ["run", "--name", migration_id]
                if uid is not None:
                    args += ["--user", str(uid)]
                args += env_args(migration.get("env", {}), migration_env_file)
                if command:
                    args += ["--entrypoint", command[0]]
                args += [image, *command[1:], *migration.get("args", ["migrate"])]
                docker(*args, timeout=timeout)
                record(stage, "verified", "Migration process exited successfully against supplied test configuration.")
        stage = "http-readiness"
        containers.append(ident)
        values = dict(config.get("env", {}))
        values.update(PORT=str(port), SCHEDULER_ENABLED="false")
        if name == "frontend":
            values.update(HOSTNAME="0.0.0.0", NODE_ENV="production")
        args = ["run", "--detach", "--name", ident, "--publish", f"127.0.0.1::{port}"]
        if uid is not None:
            args += ["--user", str(uid)]
        args += env_args(values, env_file)
        args += [image]
        docker(*args)
        bound = docker("port", ident, f"{port}/tcp").splitlines()[0]
        if not bound.startswith("127.0.0.1:"):
            raise ValueError("unexpected Docker port binding")
        base = "http://" + bound
        deadline = time.monotonic() + timeout
        paths = [config.get("ready_path", "/readyz" if name == "backend" else "/")]
        if name == "backend":
            paths.append(config.get("health_path", "/healthz"))
        elif "health_path" in config:
            paths.append(config["health_path"])
        for path in dict.fromkeys(paths):
            if not probe(base + path, deadline):
                record(stage, "failed", f"No successful HTTP response on port {port}, path {path}; inspect app test configuration.")
                return checks
        record(stage, "verified", f"HTTP probes succeeded through published container port {port}.")
        record("configuration", "verified", "Application started with supplied test environment; production secret delivery remains unverified.")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        # Docker output and application logs may contain credentials. Never echo
        # them into the generated report or exception output.
        record(stage, "failed", f"Container check failed ({type(error).__name__}); process output withheld to avoid exposing secrets.")
    finally:
        for container in reversed(containers):
            try:
                docker("rm", "--force", container)
            except (OSError, subprocess.SubprocessError):
                record("cleanup", "failed", f"Remove temporary container {container} manually.")
        try:
            docker("image", "rm", image)
        except (OSError, subprocess.SubprocessError):
            # A failed build can legitimately leave no tagged image.
            pass
    return checks
