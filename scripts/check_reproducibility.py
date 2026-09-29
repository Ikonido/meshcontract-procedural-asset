#!/usr/bin/env python3
"""Check that the generator reproduces the committed asset.obj byte for byte."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from meshcontract_cli import COMMITTED_ASSET, GateFailure, generate, generate_twice, sha256


def main() -> int:
    try:
        digest = generate_twice("valid")
        print(f"two independent generations identical: sha256 {digest}")
        with tempfile.TemporaryDirectory(prefix="meshcontract-repro-") as temp_dir:
            fresh = Path(temp_dir) / "asset.obj"
            generate("valid", fresh)
            committed = sha256(COMMITTED_ASSET)
            if sha256(fresh) != committed:
                raise GateFailure(
                    "generator output differs from committed asset.obj "
                    f"(generated {sha256(fresh)}, committed {committed}); "
                    "run `python generate_mesh.py` and commit the result"
                )
    except GateFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"generated output matches committed asset.obj: sha256 {digest}")
    print("PASS: asset generation is reproducible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
