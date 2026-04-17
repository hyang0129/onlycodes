"""Data models for SWE-bench problems and results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger


@dataclass
class Problem:
    """A single SWE-bench problem instance."""

    instance_id: str
    repo_slug: str
    base_commit: str
    test_cmd: str
    problem_statement: str
    patch_file: str | None
    added_at: str
    hf_split: str

    def to_yaml(self, path: Path) -> None:
        """Write this problem to a YAML file."""
        data = {
            "instance_id": self.instance_id,
            "repo": self.repo_slug,
            "base_commit": self.base_commit,
            "test_cmd": self.test_cmd,
            "patch_file": self.patch_file,
            "problem_statement": self.problem_statement,
            "added_at": self.added_at,
            "hf_split": self.hf_split,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        except OSError as exc:
            logger.error(f"Failed to write YAML to {path}: {exc}")
            raise

    @classmethod
    def from_yaml(cls, path: Path) -> Problem:
        """Load a Problem from a YAML file."""
        # Gap 3: OSError on open; Gap 1: YAMLError on parse
        try:
            with open(path) as f:
                raw = f.read()
        except OSError as exc:
            logger.error(f"Failed to read YAML from {path}: {exc}")
            raise
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            logger.error(f"Failed to parse YAML from {path}: {exc}")
            raise
        # Gap 2: KeyError on missing required field
        try:
            instance_id = data["instance_id"]
            repo_slug = data["repo"]
            base_commit = data["base_commit"]
            test_cmd = data["test_cmd"]
            problem_statement = data["problem_statement"]
        except KeyError as exc:
            logger.error(f"Missing required field {exc} in YAML at {path}")
            raise
        return cls(
            instance_id=instance_id,
            repo_slug=repo_slug,
            base_commit=base_commit,
            test_cmd=test_cmd,
            problem_statement=problem_statement,
            patch_file=data.get("patch_file"),
            added_at=data.get("added_at", ""),
            hf_split=data.get("hf_split", "test"),
        )


@dataclass
class ArmResult:
    """Result of running one arm on one instance."""

    instance_id: str
    arm: str  # "baseline" | "onlycode"
    run_idx: int
    verdict: str  # "PASS" | "FAIL" | "ERROR"
    cost_usd: float | None
    num_turns: int | None
    wall_secs: int
    jsonl_path: str
    test_txt_path: str
