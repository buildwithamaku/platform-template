"""Reviewable production image promotion; never merges or contacts production."""
import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

import yaml

from .verify import verify


def promoted_overlay(staging, production):
    images = staging.get("images", [])
    if not images or any(not re.fullmatch(r"sha256:[a-f0-9]{64}", image.get("digest", ""))
                         or image.get("newTag") for image in images):
        raise ValueError("Every staging overlay image, including E2E tooling, must be pinned by digest")
    names = [i["name"] for i in images]
    if len(names) != len(set(names)) or set(names) != {i["name"] for i in production.get("images", [])}:
        raise ValueError("Staging and production must declare the same unique image names")
    result = copy.deepcopy(production)
    result["images"] = copy.deepcopy(images)
    return result


def promote(platform, context, urls, acceptance_suite, publish=False):
    platform = Path(platform).resolve()
    if not urls or not acceptance_suite:
        raise ValueError("Promotion requires HTTPS URLs and an application/database acceptance suite")
    evidence = verify(platform, "staging", context, urls, acceptance_suite)
    if not evidence["promotion_ready"]:
        raise ValueError("Staging verification is incomplete or failed; run factory verify for details")

    def run(*args, cwd=platform):
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                              text=True, timeout=120).stdout.strip()

    answers = yaml.safe_load((platform / ".copier-answers.yml").read_text())
    repo = f"{answers['registry_org']}/{answers['platform_repo']}"
    origin = run("git", "remote", "get-url", "origin").removesuffix(".git")
    if origin not in {f"https://github.com/{repo}", f"git@github.com:{repo}"}:
        raise ValueError("origin must match the generated platform repository")

    def check_main():
        published = run("git", "ls-remote", "origin", "refs/heads/main").split()
        if not published or published[0] != evidence["revision"]:
            raise ValueError("Published main changed or differs from verified staging; re-verify before promotion")

    check_main()
    changes = {}
    for staging in sorted((platform / "clusters/apps").glob("*/overlays/staging/kustomization.yaml")):
        if staging.parent.parent.parent.name not in {"backend", "frontend"}:
            continue
        production = staging.parent.parent / "prod/kustomization.yaml"
        # Read immutable Git content, not files another process could edit.
        staged = yaml.safe_load(run("git", "show", f"{evidence['revision']}:{staging.relative_to(platform)}"))
        previous = yaml.safe_load(run("git", "show", f"{evidence['revision']}:{production.relative_to(platform)}"))
        result = promoted_overlay(staged, previous)
        if result != previous:
            changes[production.relative_to(platform)] = result
    if not changes:
        return {"status": "unchanged", "detail": "Production already references the verified staging digests"}
    branch = "codex/promote-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="factory-promotion-") as tmp:
        worktree = Path(tmp) / "platform"
        run("git", "worktree", "add", "-b", branch, str(worktree), evidence["revision"])
        try:
            for relative, document in changes.items():
                (worktree / relative).write_text(yaml.safe_dump(document, sort_keys=False))
                run("kustomize", "build", str((worktree / relative).parent), cwd=worktree)
            record = Path("promotion-evidence") / (branch.split("/")[-1] + ".json")
            (worktree / record).parent.mkdir(exist_ok=True)
            (worktree / record).write_text(json.dumps(evidence, indent=2) + "\n")
            run("git", "add", "--", *map(str, changes), str(record), cwd=worktree)
            run("git", "commit", "-m", "Promote verified staging images to production", cwd=worktree)
            commit = run("git", "rev-parse", "HEAD", cwd=worktree)
            result = {"status": "prepared", "branch": branch, "commit": commit,
                      "staging_revision": evidence["revision"], "files": list(map(str, changes))}
            if publish:
                check_main()
                run("git", "push", "--set-upstream", "origin", branch, cwd=worktree)
                body = Path(tmp) / "pr-body.md"
                body.write_text(f"Promotes the exact image digests verified on staging at `{evidence['revision']}`.\n\n"
                    f"Validation: GitOps reconciliation, completed rollouts, HTTPS, and application/database acceptance. "
                    f"Evidence is recorded in `{record}`.\n\n"
                    "Only production image references change; environment configuration is preserved. "
                    "Review acceptance-suite coverage and migration compatibility before merging. "
                    "Production reconciliation and verification remain required after merge.\n")
                result["pr"] = run("gh", "pr", "create", "--repo", repo, "--base", "main", "--head", branch,
                    "--title", "Promote verified staging images to production", "--body-file", str(body), cwd=worktree)
                result["status"] = "published"
            return result
        finally:
            # This worktree is exclusively created and owned by this operation.
            # Its branch remains available for review/recovery even if publishing fails.
            run("git", "worktree", "remove", "--force", str(worktree))
