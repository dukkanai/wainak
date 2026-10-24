#!/usr/bin/env python3
"""Identity tests: fake email, ephemeral fixture keys, owned disposable PG only."""
import argparse
import importlib.util
import sys
from pathlib import Path
import unittest
import run_postgres


def main(extra_test_factory=None, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-disposable-identity", action="store_true")
    args = parser.parse_args(argv)
    if not args.run_disposable_identity:
        parser.error("Explicit --run-disposable-identity is required")

    def extra(connect, restart, temporary):
        from wainak_identity.bootstrap import configure, ephemeral_keys
        keys = ephemeral_keys()  # Generated only in harness memory; never a file/env/argv/log.
        configure(connect, keys=keys)
        # Django schema setup is lazy, AFTER the unchanged 14 phase1 PG tests.
        # No Django connection is opened until IdentityIntegrationTests.setUpClass.
        specification = importlib.util.spec_from_file_location("identity_integration", Path(__file__).with_name("test_identity.py"))
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        module.CONNECT, module.RESTART_DATABASE, module.FIXTURE_KEYS = connect, restart, keys
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        if extra_test_factory is not None:
            # Trusted Python-only QA seam, never a HTTP route/CLI DSN/key argument.
            # Appended cases run after the built-in class has lazily migrated.
            suite.addTests(extra_test_factory(connect, restart, temporary, keys))
        return suite

    return run_postgres.main(extra_test_factory=extra, argv=["--run-disposable-postgres"])


if __name__ == "__main__":
    raise SystemExit(main())
