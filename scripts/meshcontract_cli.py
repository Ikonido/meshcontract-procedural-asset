"""Subprocess helpers for exercising the MeshContract CLI and JSON protocol."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from meshcontract.contract import ContractError, load_contract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract.yaml"
WIDTH_VIOLATION_CODE = "max_width_m_exceeded"
WIDTH_RULE = "max_width_m"
SUBPROCESS_TIMEOUT_SECONDS = 30
BASELINE_METRICS = {
    "vertices": 1446,
    "faces": 1638,
    "triangles": 2584,
    "dimensions_m": {"width": 1.444, "length": 0.939, "height": 1.022},
}
GENERATOR = ROOT / "generate_mesh.py"
COMMITTED_ASSET = ROOT / "asset.obj"


class GateFailure(RuntimeError):
    """Raised when MeshContract does not return the expected quality-gate result."""


def run_meshcontract(model: Path, *, json_output: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["meshcontract", "check", str(model.resolve()), "--contract", str(CONTRACT)]
    if json_output:
        command.extend(("--format", "json"))
    try:
        return subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"MeshContract timed out after {SUBPROCESS_TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise GateFailure(f"could not start MeshContract: {exc}") from exc


def _json_payload(result: subprocess.CompletedProcess[str], label: str) -> dict[str, object]:
    def reject_constant(value: str):
        raise ValueError(f"non-finite JSON number {value}")

    try:
        payload = json.loads(result.stdout, parse_constant=reject_constant)
    except ValueError as exc:
        raise GateFailure(f"{label}: MeshContract did not return valid finite JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateFailure(f"{label}: expected a JSON object from MeshContract")
    return payload


def _require_metrics(payload: dict, label: str, expected: dict | None = None) -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise GateFailure(f"{label}: JSON is missing geometry metrics")
    for name in ("vertices", "faces", "triangles"):
        actual = metrics.get(name)
        if not isinstance(actual, int) or isinstance(actual, bool) or actual <= 0:
            raise GateFailure(f"{label}: invalid {name} metric {actual!r}")
        if expected is not None and actual != expected[name]:
            raise GateFailure(f"{label}: expected {name}={expected[name]}, got {actual}")
    dimensions = metrics.get("dimensions_m")
    if not isinstance(dimensions, dict):
        raise GateFailure(f"{label}: JSON is missing dimension metrics")
    for name in ("width", "length", "height"):
        actual = dimensions.get(name)
        if not _finite_number(actual) or actual < 0:
            raise GateFailure(f"{label}: invalid {name} dimension {actual!r}")
        if expected is not None and not math.isclose(actual, expected["dimensions_m"][name], rel_tol=0, abs_tol=1e-9):
            raise GateFailure(f"{label}: unexpected {name} dimension {actual!r}")


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def require_pass(
    result: subprocess.CompletedProcess[str], *, label: str,
    expected_metrics: dict | None = None,
) -> dict[str, object]:
    if result.returncode != 0:
        raise GateFailure(f"{label}: expected MeshContract exit code 0, got {result.returncode}")
    payload = _json_payload(result, label)
    if payload.get("status") != "pass" or payload.get("violations") != [] or "error" in payload:
        raise GateFailure(f"{label}: exit code 0 must accompany status=pass and no violations or error")
    _require_metrics(payload, label, expected_metrics)
    return payload


def require_width_violation(
    result: subprocess.CompletedProcess[str], *, label: str,
) -> dict[str, object]:
    if result.returncode != 1:
        raise GateFailure(f"{label}: expected contract-failure exit code 1, got {result.returncode}")
    payload = _json_payload(result, label)
    violations = payload.get("violations")
    if payload.get("status") != "fail" or not isinstance(violations, list) or "error" in payload:
        raise GateFailure(f"{label}: JSON is missing status=fail or violations")
    _require_metrics(payload, label)
    if len(violations) != 1 or not isinstance(violations[0], dict):
        raise GateFailure(f"{label}: expected exactly one structured violation, got {len(violations)}")
    violation = violations[0]
    if violation.get("code") != WIDTH_VIOLATION_CODE or violation.get("rule") != WIDTH_RULE:
        raise GateFailure(f"{label}: JSON does not report the expected width violation")
    try:
        expected_limit = load_contract(CONTRACT).max_width_m
    except ContractError as exc:
        raise GateFailure(f"could not read the width limit from {CONTRACT}: {exc}") from exc
    if expected_limit is None:
        raise GateFailure(f"{CONTRACT}: the demo requires geometry.max_width_m")
    actual, limit = violation.get("actual"), violation.get("limit")
    if not _finite_number(actual) or not _finite_number(limit) or actual <= limit or limit != expected_limit:
        raise GateFailure(f"{label}: expected actual width above {expected_limit} m, got actual={actual!r}, limit={limit!r}")
    if not math.isclose(actual, payload["metrics"]["dimensions_m"]["width"], rel_tol=0, abs_tol=1e-9):
        raise GateFailure(f"{label}: violation width does not match the reported metrics")
    return violation


def generate(variant: str, output: Path) -> None:
    command = [sys.executable, str(GENERATOR), "--variant", variant, "--output", str(output)]
    try:
        result = subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"generator variant {variant!r} timed out after {SUBPROCESS_TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise GateFailure(f"could not run procedural generator: {exc}") from exc
    if result.returncode != 0:
        raise GateFailure(f"generator variant {variant!r} exited with code {result.returncode}: {result.stderr.strip()}")


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise GateFailure(f"could not read asset {path}: {exc}") from exc


def generate_twice(variant: str = "valid") -> str:
    with tempfile.TemporaryDirectory(prefix="meshcontract-repro-") as temp_dir:
        first, second = Path(temp_dir) / "first.obj", Path(temp_dir) / "second.obj"
        generate(variant, first)
        generate(variant, second)
        digest_first, digest_second = sha256(first), sha256(second)
    if digest_first != digest_second:
        raise GateFailure(f"generator is not deterministic: {digest_first} != {digest_second}")
    return digest_first
