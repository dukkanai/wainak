#!/usr/bin/env python3
"""Explicit clean-commit QA extension of the owned disposable identity harness."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest


def module_from_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-root',type=Path,required=True)
    parser.add_argument('--expected-backend-commit',required=True)
    parser.add_argument('--run-disposable-identity',action='store_true')
    args=parser.parse_args(argv)
    if not args.run_disposable_identity:
        parser.error('Explicit disposable identity opt-in is required')
    if not re.fullmatch(r'[0-9a-f]{40}',args.expected_backend_commit):
        parser.error('Full lowercase expected commit is required')
    root=args.backend_root.resolve(strict=True)
    required=[root/'backend/integration/run_identity.py',
              root/'qa/phase2/test_auth_independent.py',
              Path(__file__).with_name('test_matching_independent.py')]
    if not all(p.is_file() and not p.is_symlink() for p in required):
        parser.error('Reviewed local fixture and QA source files are required')
    def check():
        head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True)
        if head!=args.expected_backend_commit or dirty:
            raise RuntimeError('Candidate must match expected clean commit')
    check()
    print('QA_MATCHING_SOURCE '+json.dumps({'root':str(root),'commit':args.expected_backend_commit,
        'test_sha256':hashlib.sha256(required[-1].read_bytes()).hexdigest()},sort_keys=True),flush=True)
    sys.path.insert(0,str(root/'backend'))
    sys.path.insert(0,str(root/'backend/integration'))
    import run_identity
    def extra(connect,restart,temporary,keys):
        # No key/DSN is serialized or printed; same reviewed Python-only seam.
        helpers=module_from_path('qa_matching_baseline_helpers',required[1])
        module=module_from_path('qa_matching_independent',required[2])
        module.BASELINE_HELPERS=helpers
        module.RESTART_DATABASE=restart
        return unittest.defaultTestLoader.loadTestsFromTestCase(module.MatchingIndependentTests)
    try:
        return run_identity.main(extra_test_factory=extra,argv=['--run-disposable-identity'])
    finally:
        check()


if __name__=='__main__':
    raise SystemExit(main())
