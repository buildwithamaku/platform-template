import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from factory_cli.promote import promote, promoted_overlay


class PromotionTests(unittest.TestCase):
    def image(self, character):
        return {"name": "ghcr.io/example/backend", "digest": "sha256:" + character * 64}

    def test_only_images_are_promoted(self):
        staging = {"namespace": "staging", "images": [self.image("a")]}
        prod = {"namespace": "production", "resources": ["prod-ingress.yaml"], "images": [self.image("b")]}
        original = copy.deepcopy(prod)
        result = promoted_overlay(staging, prod)
        self.assertEqual(result["images"], staging["images"])
        self.assertEqual(result["namespace"], "production")
        self.assertEqual(result["resources"], ["prod-ingress.yaml"])
        self.assertEqual(prod, original)

    def test_mutable_or_different_image_sets_are_refused(self):
        prod = {"images": [self.image("a")]}
        with self.assertRaisesRegex(ValueError, "pinned"):
            promoted_overlay({"images": [{"name": "ghcr.io/example/backend", "newTag": "latest"}]}, prod)
        with self.assertRaisesRegex(ValueError, "same unique"):
            promoted_overlay({"images": [self.image("b")]}, {"images": []})

    @unittest.skipUnless(shutil.which("git") and shutil.which("kustomize"), "Git and Kustomize required")
    def test_real_git_branch_preserves_checkout_and_commits_only_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

            git("init", "-b", "main")
            git("config", "user.name", "Factory test")
            git("config", "user.email", "factory@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("remote", "add", "origin", "https://github.com/example/platform.git")
            (root / ".copier-answers.yml").write_text("registry_org: example\nplatform_repo: platform\n")
            for env, char in (("staging", "a"), ("prod", "b")):
                overlay = root / f"clusters/apps/backend/overlays/{env}"
                overlay.mkdir(parents=True)
                (overlay / "kustomization.yaml").write_text(yaml.safe_dump({
                    "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                    "namespace": env, "resources": [], "images": [self.image(char)]}))
            git("add", ".")
            git("commit", "-m", "Fixture")
            revision = git("rev-parse", "HEAD")
            evidence = {"promotion_ready": True, "revision": revision, "checks": []}
            actual_run = subprocess.run

            def run(command, **kwargs):
                if command[:2] == ("git", "ls-remote"):
                    return subprocess.CompletedProcess(command, 0, stdout=revision + "\trefs/heads/main")
                return actual_run(command, **kwargs)

            with patch("factory_cli.promote.verify", return_value=evidence), \
                 patch("factory_cli.promote.subprocess.run", side_effect=run):
                result = promote(root, "test-staging", ["https://app.example.com"], "suite")
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(git("branch", "--show-current"), "main")
            self.assertEqual(git("rev-parse", "HEAD"), revision)
            self.assertEqual(git("status", "--porcelain"), "")
            changed = git("diff", "--name-only", "main", result["branch"]).splitlines()
            self.assertEqual(len(changed), 2)
            overlay = "clusters/apps/backend/overlays/prod/kustomization.yaml"
            self.assertIn(overlay, changed)
            promoted = yaml.safe_load(git("show", f"{result['branch']}:{overlay}"))
            self.assertEqual(promoted["images"], [self.image("a")])
            self.assertEqual(promoted["namespace"], "prod")
            self.assertEqual(len(git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_unverified_staging_cannot_create_a_branch(self):
        with patch("factory_cli.promote.verify", return_value={"promotion_ready": False}), \
             patch("factory_cli.promote.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "incomplete"):
                promote(".", "staging", ["https://example.com"], "suite")
            run.assert_not_called()
