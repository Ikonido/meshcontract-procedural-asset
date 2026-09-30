"""Geometry and protocol regressions using only the standard test library."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from generate_mesh import MeshBuilder, build_chest
import meshcontract_cli as cli


def response(payload, code=0):
    return subprocess.CompletedProcess([], code, json.dumps(payload), "")


def passing_payload():
    return {"status": "pass", "metrics": copy.deepcopy(cli.BASELINE_METRICS), "violations": []}


def signed_volume(mesh):
    volume = 0
    for face in mesh.faces:
        a = mesh.vertices[face[0] - 1]
        for index in range(1, len(face) - 1):
            b, c = mesh.vertices[face[index] - 1], mesh.vertices[face[index + 1] - 1]
            volume += sum(
                a[j] * (b[(j + 1) % 3] * c[(j + 2) % 3] - b[(j + 2) % 3] * c[(j + 1) % 3])
                for j in range(3)
            ) / 6
    return volume


class GeometryTests(unittest.TestCase):
    def test_both_mirrored_handles_have_outward_winding(self):
        for side in (-1, 1):
            with self.subTest(side=side):
                mesh = MeshBuilder()
                mesh.add_torus_yz(side, 0, 0, 0, 1, .2)
                self.assertGreater(signed_volume(mesh), 0)

    def test_fix_preserves_chest_counts_and_dimensions(self):
        mesh = build_chest()
        self.assertEqual(len(mesh.vertices), 1446)
        self.assertEqual(len(mesh.faces), 1638)
        self.assertEqual(sum(len(face) - 2 for face in mesh.faces), 2584)
        for axis, name in enumerate(("width", "length", "height")):
            actual = max(v[axis] for v in mesh.vertices) - min(v[axis] for v in mesh.vertices)
            self.assertAlmostEqual(actual, cli.BASELINE_METRICS["dimensions_m"][name])


class GateTests(unittest.TestCase):
    def test_baseline_requires_consistent_success_json(self):
        payload = passing_payload()
        self.assertEqual(cli.require_pass(response(payload), label="baseline", expected_metrics=cli.BASELINE_METRICS), payload)

    def test_zero_exit_does_not_accept_fail_status_or_violations(self):
        for updates in ({"status": "fail"}, {"violations": [{}]}, {"error": {}}, {"metrics": None}):
            with self.subTest(updates=updates):
                payload = passing_payload()
                payload.update(updates)
                with self.assertRaises(cli.GateFailure):
                    cli.require_pass(response(payload), label="baseline")

    def test_zero_exit_does_not_accept_garbage_stdout(self):
        with self.assertRaises(cli.GateFailure):
            cli.require_pass(subprocess.CompletedProcess([], 0, "PASS", ""), label="baseline")

    def test_wrong_baseline_metrics_are_rejected(self):
        payload = passing_payload()
        payload["metrics"]["vertices"] = 12
        with self.assertRaises(cli.GateFailure):
            cli.require_pass(response(payload), label="baseline", expected_metrics=cli.BASELINE_METRICS)
        payload = passing_payload()
        payload["metrics"]["dimensions_m"]["width"] = 1.5
        with self.assertRaises(cli.GateFailure):
            cli.require_pass(response(payload), label="baseline", expected_metrics=cli.BASELINE_METRICS)

    def test_invalid_or_nonfinite_metrics_are_rejected(self):
        for value in (True, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                payload = passing_payload()
                payload["metrics"]["dimensions_m"]["width"] = value
                with self.assertRaises(cli.GateFailure):
                    cli.require_pass(response(payload), label="baseline")

    def test_width_limit_comes_from_contract_and_matches_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "contract.yaml"
            contract.write_text("version: 1\ngeometry:\n  max_width_m: 3\n")
            payload = passing_payload()
            payload["status"] = "fail"
            payload["metrics"]["dimensions_m"]["width"] = 3.2
            payload["violations"] = [{"code": "max_width_m_exceeded", "rule": "max_width_m", "actual": 3.2, "limit": 3}]
            with patch.object(cli, "CONTRACT", contract):
                self.assertEqual(cli.require_width_violation(response(payload, 1), label="regression")["limit"], 3)
                payload["violations"][0]["limit"] = 2
                with self.assertRaises(cli.GateFailure):
                    cli.require_width_violation(response(payload, 1), label="regression")
                payload["violations"][0]["limit"] = 3
                payload["metrics"]["dimensions_m"]["width"] = 3.3
                with self.assertRaises(cli.GateFailure):
                    cli.require_width_violation(response(payload, 1), label="regression")

    def test_generator_and_validator_timeouts_are_diagnostic(self):
        with patch.object(cli.subprocess, "run", side_effect=subprocess.TimeoutExpired("command", 30)) as run:
            with self.assertRaisesRegex(cli.GateFailure, "timed out"):
                cli.generate("valid", Path("asset.obj"))
            self.assertEqual(run.call_args.kwargs["timeout"], 30)
            with self.assertRaisesRegex(cli.GateFailure, "timed out"):
                cli.run_meshcontract(Path("asset.obj"))
            self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_missing_asset_has_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(cli.GateFailure, "could not read asset"):
                cli.sha256(Path(temp) / "missing.obj")


if __name__ == "__main__":
    unittest.main()
