#!/usr/bin/env python3
"""Verify the quality gate accepts a good asset and rejects bad ones.

MeshContract failing on the invalid and regression assets is the *expected*
result here. The gate itself only fails when an outcome is not what it should be.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meshcontract_cli import (
    BASELINE_METRICS,
    GateFailure,
    generate_twice,
    require_pass,
    require_width_violation,
    run_meshcontract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("valid_asset", type=Path)
    parser.add_argument("invalid_asset", type=Path)
    parser.add_argument(
        "regression_asset",
        type=Path,
        nargs="?",
        help="optional procedural regression OBJ (always supplied by CI)",
    )
    args = parser.parse_args()

    try:
        print("BASELINE")
        for path in (args.valid_asset, args.invalid_asset, args.regression_asset):
            if path is not None and not path.is_file():
                raise GateFailure(f"asset not found: {path}")
        print("  generation: PASS (asset present)")
        generate_twice("valid")
        print("  deterministic: PASS (two independent generations identical)")
        require_pass(
            run_meshcontract(args.valid_asset, json_output=True), label="baseline",
            expected_metrics=BASELINE_METRICS,
        )
        print("  MeshContract: PASS (exit code 0)")

        print("\nINVALID")
        invalid_text = run_meshcontract(args.invalid_asset)
        if invalid_text.returncode != 1:
            raise GateFailure(
                f"invalid asset: expected exit code 1, got {invalid_text.returncode}"
            )
        if "max_width_m exceeded" not in invalid_text.stdout:
            raise GateFailure("invalid asset: expected width violation was absent")
        invalid = require_width_violation(
            run_meshcontract(args.invalid_asset, json_output=True),
            label="invalid asset",
        )
        if invalid["actual"] != 2.2:
            raise GateFailure(
                f"invalid asset: expected width 2.2 m, got {invalid['actual']!r}"
            )
        print("  MeshContract: FAIL (expected)")
        print("  exit code: 1")
        print(f"  violation: {invalid['code']}")

        if args.regression_asset is not None:
            print("\nREGRESSION")
            regression = require_width_violation(
                run_meshcontract(args.regression_asset, json_output=True),
                label="procedural regression",
            )
            print("  generator: PASS (asset present)")
            print("  MeshContract: FAIL (expected)")
            print(f"  violation: {regression['code']}")
            print(f"  actual: {regression['actual']}")
            print(f"  limit: {regression['limit']}")
    except GateFailure as exc:
        print(f"\nOVERALL QUALITY GATE: FAIL - {exc}", file=sys.stderr)
        return 1

    print("\nOVERALL QUALITY GATE: PASS")
    if args.regression_asset is None:
        print("(regression asset not supplied; regression case not checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
