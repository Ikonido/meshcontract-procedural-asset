"""Small subprocess helpers for exercising the MeshContract CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract.yaml"
WIDTH_LIMIT_M = 2.0
WIDTH_VIOLATION_CODE = "max_width_m_exceeded"
WIDTH_RULE = "max_width_m"


GENERATOR = ROOT / "generate_mesh.py"
COMMITTED_ASSET = ROOT / "asset.obj"


class GateFailure(RuntimeError):
    """Raised when MeshContract does not return the expected quality-gate result."""


def run_meshcontract(
    model: Path, *, json_output: bool = False
) -> subprocess.CompletedProcess[str]:
    command = [
        "meshcontract",
        "check",
        str(model.resolve()),
        "--contract",
        str(CONTRACT),
    ]
    if json_output:
        command.extend(("--format", "json"))
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise GateFailure(f"could not start MeshContract: {exc}") from exc


def require_pass(
    result: subprocess.CompletedProcess[str], *, label: str
) -> None:
    if result.returncode != 0:
        raise GateFailure(
            f"{label}: expected MeshContract exit code 0, got {result.returncode}"
        )


def require_width_violation(
    result: subprocess.CompletedProcess[str], *, label: str
) -> dict[str, object]:
    if result.returncode != 1:
        raise GateFailure(
            f"{label}: expected contract-failure exit code 1, got {result.returncode}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(f"{label}: MeshContract did not return valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateFailure(f"{label}: expected a JSON object from MeshContract")

    violations = payload.get("violations")
    if payload.get("status") != "fail" or not isinstance(violations, list):
        raise GateFailure(f"{label}: JSON is missing status=fail or violations")
    if len(violations) != 1 or not isinstance(violations[0], dict):
        raise GateFailure(
            f"{label}: expected exactly one structured violation, got {len(violations)}"
        )

    violation = violations[0]
    if (
        violation.get("code") != WIDTH_VIOLATION_CODE
        or violation.get("rule") != WIDTH_RULE
    ):
        raise GateFailure(f"{label}: JSON does not report the expected width violation")

    actual = violation.get("actual")
    limit = violation.get("limit")
    if (
        not isinstance(actual, (int, float))
        or isinstance(actual, bool)
        or not isinstance(limit, (int, float))
        or isinstance(limit, bool)
        or actual <= limit
        or limit != WIDTH_LIMIT_M
    ):
        raise GateFailure(
            f"{label}: expected actual width above {WIDTH_LIMIT_M} m, "
            f"got actual={actual!r}, limit={limit!r}"
        )
    return violation


def generate(variant: str, output: Path) -> None:
    """Run the procedural generator; raise GateFailure if it does not succeed."""
    command = [
        sys.executable,
        str(GENERATOR),
        "--variant",
        variant,
        "--output",
        str(output),
    ]
    try:
        result = subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True
        )
    except OSError as exc:
        raise GateFailure(f"could not run procedural generator: {exc}") from exc
    if result.returncode != 0:
        raise GateFailure(
            f"generator variant {variant!r} exited with code {result.returncode}: "
            f"{result.stderr.strip()}"
        )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_twice(variant: str = "valid") -> str:
    """Generate a variant twice independently; return the SHA-256 they share."""
    with tempfile.TemporaryDirectory(prefix="meshcontract-repro-") as temp_dir:
        first = Path(temp_dir) / "first.obj"
        second = Path(temp_dir) / "second.obj"
        generate(variant, first)
        generate(variant, second)
        digest_first, digest_second = sha256(first), sha256(second)
    if digest_first != digest_second:
        raise GateFailure(
            f"generator is not deterministic: {digest_first} != {digest_second}"
        )
    return digest_first
