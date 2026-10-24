#!/usr/bin/env python3
"""QA-only extension of the reviewed disposable identity harness; no external DSN."""
import argparse
import importlib.util
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backend-root", type=Path, required=True)
parser.add_argument("--run-disposable-identity", action="store_true")
args = parser.parse_args()
if not args.run_disposable_identity:
    parser.error("Explicit --run-disposable-identity is required")
root = args.backend_root.resolve(strict=True)
if not (root / "backend/integration/run_identity.py").is_file():
    parser.error("Reviewed backend checkout is required")
sys.path.insert(0, str(root / "backend"))
sys.path.insert(0, str(root / "backend/integration"))
import run_identity

def extra(connect, restart, temporary, keys):
    # All private objects remain in Python; no keys/connection details are printed.
    source = Path(__file__).with_name("test_auth_independent.py")
    spec = importlib.util.spec_from_file_location("qa_identity_independent", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RESTART_DATABASE = restart
    return unittest.defaultTestLoader.loadTestsFromModule(module)

raise SystemExit(run_identity.main(extra_test_factory=extra, argv=["--run-disposable-identity"]))
