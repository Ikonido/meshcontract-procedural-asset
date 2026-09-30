#!/usr/bin/env python3
"""Demonstrate MeshContract accepting a baseline chest and blocking its regression."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from meshcontract_cli import (
    BASELINE_METRICS,
    ROOT,
    GateFailure,
    generate,
    require_pass,
    require_width_violation,
    run_meshcontract,
)

sys.path.insert(0, str(ROOT))
from generate_mesh import REGRESSION_WIDTH_SCALE  # noqa: E402


def run_demo() -> None:
    with tempfile.TemporaryDirectory(prefix="meshcontract-demo-") as temp_dir:
        work = Path(temp_dir)
        baseline = work / "baseline.obj"
        regression = work / "regression.obj"

        print("1. Generate the procedural chest (baseline parameters)")
        generate("valid", baseline)
        print("   asset generated")

        print("2. Check the baseline against contract.yaml")
        result = run_meshcontract(baseline)
        for line in result.stdout.splitlines():
            if line.startswith(("Dimensions", "PASS")):
                print(f"   {line}")
        require_pass(
            run_meshcontract(baseline, json_output=True), label="baseline chest",
            expected_metrics=BASELINE_METRICS,
        )
        print("   -> PASS (exit code 0)")

        print(f"3. Change one generator parameter: width x {REGRESSION_WIDTH_SCALE}")
        generate("regression", regression)
        print("   same generator, new geometry")

        print("4. Check the regenerated asset")
        result = run_meshcontract(regression, json_output=True)
        violation = require_width_violation(result, label="procedural regression")
        print("   -> FAIL (exit code 1)")
        print(f"   {violation['code']}: width {violation['actual']} m > limit {violation['limit']} m")

        print("5. Quality gate: BLOCKED - the regression would not be accepted")


def main() -> int:
    try:
        run_demo()
    except GateFailure as exc:
        print(f"DEMO FAILED: {exc}", file=sys.stderr)
        return 1
    print("\nThe generator still works, but the geometry regression violates the")
    print("asset contract, so the quality gate blocks it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
