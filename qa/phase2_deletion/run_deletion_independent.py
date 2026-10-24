#!/usr/bin/env python3
"""Exact-commit QA extension; fresh disposable identity DB only, no external DSN."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backend-root", type=Path, required=True)
parser.add_argument("--expected-backend-commit", required=True)
parser.add_argument("--run-disposable-identity", action="store_true")
args = parser.parse_args()
if not args.run_disposable_identity:
    parser.error("Explicit disposable-fixture approval flag is required")
root = args.backend_root.resolve(strict=True)

def exact_source():
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]).decode().strip()
    dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"]).strip()
    if head != args.expected_backend_commit or dirty:
        raise RuntimeError("Expected clean exact backend commit; refusing mixed-source evidence")
    return head

print("backend_commit", exact_source(), flush=True)
sys.path.insert(0, str(root / "backend"))
sys.path.insert(0, str(root / "backend/integration"))
import run_identity

def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module

def extra(connect, restart, temporary, keys):
    # Never expose private connection/key objects as CLI/HTTP/environment values.
    here = Path(__file__).resolve().parent
    baseline = load("qa_identity_independent", here.parent / "phase2/test_auth_independent.py")
    baseline.RESTART_DATABASE = restart
    additive = load("qa_deletion_independent", here / "test_deletion_independent.py")
    additive.RESTART_DATABASE = restart
    suite = unittest.defaultTestLoader.loadTestsFromModule(baseline)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(additive))
    return suite

result = run_identity.main(extra_test_factory=extra, argv=["--run-disposable-identity"])
exact_source()
raise SystemExit(result)
