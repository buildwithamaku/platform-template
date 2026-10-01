"""Install generated caller workflows through isolated review branches."""
from pathlib import Path
import subprocess
import tempfile
import uuid

import yaml


def connect(spec, bundle, workflows, publish=False):
    bundle = Path(bundle).resolve()
    repositories = {}
    for service in spec["services"].values():
        root = service["_root"].resolve()
        repo = service["repo"]
        if repo in repositories and repositories[repo] != root:
            raise ValueError("Services in one repository must use the same checkout")
        repositories[repo] = root
    plans = []

    def run(root, *args):
        return subprocess.run(args, cwd=root, check=True, capture_output=True,
                              text=True, timeout=120).stdout.strip()

    # Validate every repository and workflow before preparing any branch.
    for repo, root in repositories.items():
        source = bundle / "connections" / repo / "deliver.yml"
        content = source.read_text()
        if yaml.safe_load(content) != workflows[repo]:
            raise ValueError(f"{repo}: bundle workflow differs from specification; regenerate onboarding")
        if Path(run(root, "git", "rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError(f"{repo}: checkout must be the repository root")
        origin = run(root, "git", "remote", "get-url", "origin").removesuffix(".git")
        if origin not in {f"https://github.com/{repo}", f"git@github.com:{repo}"}:
            raise ValueError(f"{repo}: origin does not match the declared app repository")
        base = workflows[repo]["on"]["push"]["branches"][0]
        run(root, "git", "check-ref-format", "--branch", base)
        run(root, "git", "fetch", "origin", base)
        revision = run(root, "git", "rev-parse", "FETCH_HEAD")
        plans.append((repo, root, content, base, revision))
    results = []
    for repo, root, content, base, revision in plans:
        branch = "codex/connect-factory-" + uuid.uuid4().hex[:12]
        with tempfile.TemporaryDirectory(prefix="factory-connect-") as temp:
            worktree = Path(temp) / "app"
            run(root, "git", "worktree", "add", "-b", branch, str(worktree), revision)
            try:
                relative = Path(".github/workflows/factory-deliver.yml")
                target = worktree / relative
                if not target.parent.resolve().is_relative_to(worktree.resolve()):
                    raise ValueError(f"{repo}: workflow directory resolves outside the checkout")
                if target.exists() or target.is_symlink():
                    if not target.is_symlink() and target.read_text() == content:
                        results.append({"repo": repo, "status": "unchanged"})
                        continue
                    raise ValueError(f"{repo}: factory-deliver.yml already exists with different content; refusing to overwrite")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                run(worktree, "git", "add", "--", str(relative))
                run(worktree, "git", "commit", "-m", "Connect container delivery to platform factory")
                result = {"repo": repo, "status": "prepared", "branch": branch,
                          "commit": run(worktree, "git", "rev-parse", "HEAD")}
                if publish:
                    run(worktree, "git", "push", "--set-upstream", "origin", branch)
                    body = Path(temp) / "body.md"
                    body.write_text("Connects this repository's container builds to the platform delivery workflow. "
                        "Each configured service builds from its own context and updates its staging image digest.\n\n"
                        "Before merging, configure DEPLOYER_APP_ID and DEPLOYER_PRIVATE_KEY, authorize access to "
                        "the reusable platform workflow, and confirm GHCR package access. "
                        "Production promotion remains a separate reviewed PR.\n")
                    result["pr"] = run(worktree, "gh", "pr", "create", "--repo", repo, "--base", base,
                        "--head", branch, "--title", "Connect container delivery to platform factory",
                        "--body-file", str(body))
                    result["status"] = "published"
                results.append(result)
            finally:
                run(root, "git", "worktree", "remove", "--force", str(worktree))
    return results
