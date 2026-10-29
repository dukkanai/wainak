"""Regression for lists exceeding the native transport's 64 KiB bound."""
import io
import json
import unittest

import test_domain
from wainek.api import DevelopmentApplication, relationship_cursor
from wainek.domain import DomainError


class RelationshipPaginationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_domain.DomainTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.actor, self.token = self.fixture.create('female')

    def incoming(self, count):
        identifiers = []
        for index in range(count):
            sender, _ = self.fixture.create()
            relation = self.service.request(sender, {'candidate_id': self.actor}, f'page-{index:05d}')
            identifiers.append(relation['id'])
        return sorted(identifiers)

    def request(self, query='', method='GET', path='/v1/relationships'):
        result = {}
        app = DevelopmentApplication(enable_development=True, service=self.service)
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': query,
               'HTTP_HOST': 'localhost', 'HTTP_AUTHORIZATION': 'Bearer ' + self.token,
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': '2', 'wsgi.input': io.BytesIO(b'{}')}
        def start(status, headers):
            result['status'] = int(status.split()[0])
        raw = b''.join(app(env, start))
        return result['status'], json.loads(raw), len(raw)

    def test_105_valid_requests_fit_bounded_pages_and_remain_actionable(self):
        expected = self.incoming(105)
        identifiers, cursor, pages = [], None, []
        while True:
            status, page, size = self.request('' if cursor is None else 'cursor=' + cursor)
            self.assertEqual(status, 200)
            self.assertLess(size, 65536)
            # Django JsonResponse uses ASCII escaping and whitespace by default.
            self.assertLess(len(json.dumps(page, ensure_ascii=True).encode()), 65536)
            self.assertLessEqual(len(page['items']), 20)
            pages.append(len(page['items']))
            identifiers.extend(item['id'] for item in page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                break
            self.assertEqual(cursor, page['items'][-1]['id'])
        self.assertEqual(pages, [20, 20, 20, 20, 20, 5])
        self.assertEqual(identifiers, expected)
        self.assertEqual(len(set(identifiers)), 105)
        self.assertEqual(self.service.respond(self.actor, identifiers[-1], {'decision': 'accept'})['status'],
                         'accepted_pending_activation')
        self.assertEqual(self.service.respond(self.actor, identifiers[-2], {'decision': 'decline'})['status'], 'declined')
        last = self.service.relationship(self.actor, identifiers[-3])
        self.assertTrue(self.service.block(self.actor, {'target_id': last['initiator_id']})['blocked'])
        report = self.service.report(self.actor, {'target_id': last['initiator_id'],
            'relationship_id': last['id'], 'category': 'harassment'})
        self.assertFalse(report['evidence_uploaded'])

    def test_cursor_ownership_and_unknown_cursor_have_same_safe_error(self):
        own = self.incoming(2)
        a, b, foreign = self.fixture.pair(activate=False)
        results = []
        for cursor in (foreign, 'rel_' + '0' * 32):
            status, body, _ = self.request('cursor=' + cursor)
            self.assertEqual(status, 400)
            self.assertNotIn(cursor, json.dumps(body))
            results.append(body)
        self.assertEqual(results[0], results[1])
        for cursor in ('', [], 2, True, 'rel_' + 'A' * 32):
            with self.subTest(cursor=cursor), self.assertRaises(DomainError):
                self.service.list_relationships(self.actor, cursor)
        self.assertEqual(self.service.list_relationships(self.actor, own[-1]), {'items': [], 'next_cursor': None})

    def test_only_exact_cursor_query_on_exact_get_route_is_allowed(self):
        cursor = 'rel_' + 'a' * 32
        self.assertEqual(relationship_cursor('GET', '/v1/relationships', 'cursor=' + cursor), cursor)
        for query in ('cursor=', 'cursor=' + cursor + '&cursor=' + cursor, 'cursor=' + cursor + '&limit=20',
                      'limit=20', 'health=diabetes', 'token=secret', 'cursor=' + cursor + '&token=secret',
                      '%63ursor=' + cursor, 'cursor=%72' + cursor[1:], 'cursor=' + cursor + '%26x=y',
                      'cursor=' + cursor + ';x=y', 'cursor=' + cursor + '#x', 'cursor=' + cursor.upper()):
            with self.subTest(query=query):
                self.assertEqual(self.request(query)[0], 400)
        for method, path in (('POST', '/v1/relationships'), ('GET', '/v1/relationships/'),
                             ('GET', '/v1/candidates'), ('GET', '/_allauth/app/v1/auth/session')):
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request('cursor=' + cursor, method, path)[0], 400)

    def test_stable_order_across_reconstruction_and_current_block_redaction(self):
        expected = self.incoming(21)
        first = self.service.list_relationships(self.actor)
        # Repository ordering is not a pagination contract, including SQL loads.
        with self.service.repository.transaction() as state:
            state.relationships = dict(reversed(list(state.relationships.items())))
        from wainek.domain import DevelopmentService
        restored = DevelopmentService(today=self.service.today, repository=self.service.repository)
        page = restored.list_relationships(self.actor, first['next_cursor'])
        self.assertEqual([x['id'] for x in page['items']], expected[20:])
        peer = page['items'][0]['initiator_id']
        restored.block(peer, {'target_id': self.actor})
        current = restored.list_relationships(self.actor, first['next_cursor'])['items'][0]
        self.assertEqual(current['status'], 'blocked')
        self.assertIsNone(current['peer'])
        self.assertFalse(any(current['permissions'].values()))


if __name__ == '__main__':
    unittest.main()
