import unittest
from datetime import date

from wainek.domain import DevelopmentService, POLICY_VERSION
from wainek.migrations import RepositoryConfigurationError, apply_initial_migration
from wainek.postgres import PostgresRepository
from wainek.repository import MemoryRepository


class RepositoryTests(unittest.TestCase):
    def test_memory_transaction_rolls_back_partial_changes(self):
        repository = MemoryRepository()
        with self.assertRaises(RuntimeError):
            with repository.transaction() as state:
                state.accounts["uncommitted"] = {"private": "synthetic"}
                raise RuntimeError("synthetic failure")
        with repository.transaction() as state:
            self.assertEqual(state.accounts, {})

    def test_memory_transaction_snapshot_cannot_be_mutated_after_commit(self):
        repository = MemoryRepository()
        with repository.transaction() as state:
            state.accounts["example"] = {"value": 1}
        state.accounts["example"]["value"] = 2
        with repository.transaction() as state:
            self.assertEqual(state.accounts["example"]["value"], 1)

    def test_services_share_a_repository_without_sharing_service_lock(self):
        repository = MemoryRepository()
        first = DevelopmentService(today=lambda: date(2026,10,24), repository=repository)
        second = DevelopmentService(today=lambda: date(2026,10,24), repository=repository)
        result = first.register({"email": "repository@example.invalid", "birth_date": "1990-01-01", "is_muslim": True,
                                 "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        actor = second.authenticate(result["access_token"])
        self.assertEqual(second.me(actor)["id"], result["account"]["id"])

    def test_persistence_and_migration_fail_closed_without_explicit_opt_in(self):
        def must_not_connect():
            self.fail("Connection must not be attempted without opt-in")
        with self.assertRaises(RepositoryConfigurationError):
            PostgresRepository(must_not_connect)
        with self.assertRaises(RepositoryConfigurationError):
            apply_initial_migration(must_not_connect)


if __name__ == "__main__":
    unittest.main()
