import unittest
from query_public_maven_advisories import checked_coordinates, query

ROW = {"name": "org.example:public-test-fixture", "version": "1.2.3", "public_reviewed": True}


class PublicAdvisoryTests(unittest.TestCase):
    def test_no_match_is_not_a_security_claim(self):
        result = query([ROW], lambda _: {"results": [{}]})
        self.assertTrue(result["pagination_complete"])
        self.assertEqual(result["results"][0]["vulnerabilities"], [])
        self.assertIn("empty result does not establish database coverage", result["limits"])

    def test_private_or_unreviewed_is_rejected_before_fetch(self):
        for row in [dict(ROW, name="wainak.local:private"), dict(ROW, public_reviewed=False)]:
            with self.assertRaises(ValueError):
                checked_coordinates([row])

    def test_duplicate_coordinates_are_one_query(self):
        self.assertEqual(len(checked_coordinates([ROW, ROW])), 1)

    def test_pagination_is_followed_and_deduplicated(self):
        calls = []
        def fetch(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {"results": [{"vulns": [{"id": "GHSA-test-one"}], "next_page_token": "public-next"}]}
            self.assertEqual(payload["queries"][0]["page_token"], "public-next")
            return {"results": [{"vulns": [{"id": "GHSA-test-one"}, {"id": "GHSA-test-two"}]}]}
        result = query([ROW], fetch)
        self.assertEqual(len(result["results"][0]["vulnerabilities"]), 2)

    def test_pagination_cycle_fails_closed(self):
        tokens = iter(["first", "second", "first"])
        with self.assertRaisesRegex(ValueError, "advisory_pagination"):
            query([ROW], lambda _: {"results": [{"next_page_token": next(tokens)}]})

    def test_total_response_memory_is_bounded(self):
        large = "x" * (9 * 1024 * 1024)
        calls = [0]
        def fetch(_):
            calls[0] += 1
            return {"results": [{"next_page_token": str(calls[0]), "public_fixture": large}]}
        with self.assertRaisesRegex(ValueError, "total_advisory_response_bound"):
            query([ROW], fetch)

    def test_errors_and_wrong_counts_are_not_empty_passes(self):
        for response in [{"results": []}, {"results": [{"error": "fixture"}]}]:
            with self.assertRaises(ValueError):
                query([ROW], lambda _: response)


if __name__ == "__main__":
    unittest.main()
