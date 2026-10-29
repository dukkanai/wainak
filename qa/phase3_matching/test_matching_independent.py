"""QA-owned matching authorization tests; private fixture values never printed."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import mock

from django.db import connections, transaction
from django.test import override_settings
from allauth.account.models import EmailAddress
from wainek_identity.repository import service
from wainek.domain import REPORT_CATEGORIES

BASELINE_HELPERS = None
RESTART_DATABASE = None


class MatchingIndependentTests(unittest.TestCase):
    def setUp(self):
        BASELINE_HELPERS.IndependentIdentityTests.setUp(self)

    def tearDown(self):
        BASELINE_HELPERS.IndependentIdentityTests.tearDown(self)

    def call(self, *a, **kw):
        return BASELINE_HELPERS.IndependentIdentityTests.call(self, *a, **kw)

    def expect_status(self, *a, **kw):
        return BASELINE_HELPERS.IndependentIdentityTests.expect_status(self, *a, **kw)

    def signup(self, *a, **kw):
        return BASELINE_HELPERS.IndependentIdentityTests.signup(self, *a, **kw)

    def account(self, *a, **kw):
        return BASELINE_HELPERS.IndependentIdentityTests.account(self, *a, **kw)

    def matching_pair(self):
        return BASELINE_HELPERS.IndependentIdentityTests.matching_pair(self)

    def ready(self):
        self.a, self.ma, self.b, self.mb = self.matching_pair()
        return self.a, self.ma, self.b, self.mb

    def requested(self):
        self.ready()
        response = self.call('POST', '/v1/relationships',
                             {'candidate_id': self.mb['domain_id']}, self.a,
                             HTTP_IDEMPOTENCY_KEY='qa_matching_request')
        self.expect_status(response, 201)
        self.rel = response[1]['id']
        self.path = '/v1/relationships/' + self.rel
        return response[1]

    def mutate(self, identifier, mutate):
        # Fixture-only edit; no concurrently active request, within disposable DB.
        with transaction.atomic():
            with service().repository.transaction() as state:
                mutate(state.accounts[identifier])

    def state(self):
        with transaction.atomic():
            with service().repository.transaction() as state:
                return copy.deepcopy(state)

    def assert_locked(self, body):
        self.assertEqual(set(body['permissions']),
                         {'can_send_cards','can_send_text','can_send_media','can_disclose_identity'})
        self.assertTrue(all(x is False for x in body['permissions'].values()),
                        'Acceptance/safety state must not open communication')

    def race(self, callbacks):
        barrier = threading.Barrier(len(callbacks))
        def run(callback):
            try:
                barrier.wait(timeout=10)
                return callback()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(callbacks)) as pool:
            return list(pool.map(run, callbacks))

    def test_direction_action_hints_roles_and_locked_acceptance(self):
        outgoing = self.requested()
        self.assertEqual(outgoing['direction'], 'outgoing')
        self.assertEqual(outgoing['available_actions'], ['cancel','block','report'])
        incoming = self.call('GET', self.path, token=self.b)
        self.expect_status(incoming, 200)
        self.assertEqual(incoming[1]['direction'], 'incoming')
        self.assertEqual(incoming[1]['available_actions'], ['accept','decline','block','report'])
        self.expect_status(self.call('POST', self.path+'/respond', {'decision':'accept'}, self.a), 403)
        self.expect_status(self.call('POST', self.path+'/cancel', {}, self.b), 403)
        accepted = self.call('POST', self.path+'/respond', {'decision':'accept'}, self.b)
        self.expect_status(accepted, 200)
        self.assertEqual(accepted[1]['status'], 'accepted_pending_activation')
        for token in (self.a,self.b):
            body=self.call('GET',self.path,token=token)[1]
            self.assertEqual(body['available_actions'], ['end','block','report'])
            self.assert_locked(body)

    def test_unrelated_actor_cannot_read_or_mutate_known_relationship(self):
        self.requested()
        third, _ = self.account('qa_third@example.invalid')
        for method,suffix,data in [('GET','',{}),('GET','/cards',{}),
            ('POST','/respond',{'decision':'accept'}),('POST','/respond',{'decision':'decline'}),
            ('POST','/cancel',{}),('POST','/end',{'confirm':True}),
            ('POST','/exclusive/request',{'confirm':True}),
            ('POST','/exclusive/respond',{'decision':'accept'})]:
            self.expect_status(self.call(method,self.path+suffix,data,third),404)
        self.assertEqual(self.call('GET',self.path,token=self.a)[1]['status'],'requested')

    def test_actor_input_cannot_impersonate_recipient_or_other_requester(self):
        self.requested()
        r=self.call('POST',self.path+'/respond',{'decision':'accept','actor_id':self.mb['domain_id']},self.a)
        self.assertTrue(400 <= r[0] < 500)
        r=self.call('POST',self.path+'/respond',{'decision':'accept'},self.a,
                    HTTP_X_ACTOR_ID=self.mb['domain_id'])
        self.assertTrue(400 <= r[0] < 500)
        self.assertEqual(self.call('GET',self.path,token=self.b)[1]['status'],'requested')

    def test_candidate_projection_is_exact_bounded_public_data(self):
        self.ready()
        r=self.call('GET','/v1/candidates',token=self.a)
        self.expect_status(r,200)
        self.assertEqual(len(r[1]['items']),1)
        item=r[1]['items'][0]
        self.assertEqual(set(item),{'id','alias','age','country','marital_status','marriage_goal','rating','synthetic'})
        self.assertEqual(item['rating'],{'state':'insufficient_data'})
        self.assertEqual(item['id'],self.mb['domain_id'])
        detail=self.call('GET','/v1/candidates/'+item['id'],token=self.a)
        self.expect_status(detail,200)
        self.assertTrue(detail[1]==item,'List/detail public projection must agree')

    def test_missing_peer_consent_cannot_discover_accept_or_project(self):
        self.requested()
        self.mutate(self.ma['domain_id'],lambda a:a.update(consents=None))
        self.assertEqual(self.call('GET','/v1/candidates',token=self.b)[1]['items'],[])
        self.expect_status(self.call('GET','/v1/candidates/'+self.ma['domain_id'],token=self.b),404)
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        r=self.call('GET',self.path,token=self.b)
        self.expect_status(r,200)
        self.assertIsNone(r[1]['peer'])
        self.assertNotIn('accept',r[1]['available_actions'])
        self.assertIn('decline',r[1]['available_actions'])

    def test_stale_actor_can_decline_but_strict_exception_cannot_accept(self):
        self.requested()
        self.mutate(self.mb['domain_id'],lambda a:a.update(consents=None))
        for payload in ({'decision':'accept'}, {'decision':True},
                        {'decision':'decline','actor_id':self.mb['domain_id']},
                        {'decision':'decline','simulate_entitlement':True}):
            self.assertTrue(400 <= self.call('POST',self.path+'/respond',payload,self.b)[0] < 500)
        self.assertEqual(self.call('GET',self.path,token=self.a)[1]['status'],'requested')
        declined=self.call('POST',self.path+'/respond',{'decision':'decline'},self.b)
        self.expect_status(declined,200)
        self.assertEqual(declined[1]['status'],'declined')
        self.assert_locked(declined[1])
        self.assertNotIn('accept',declined[1]['available_actions'])

    def test_stale_decline_exception_still_checks_role_and_full_route(self):
        self.requested()
        self.mutate(self.ma['domain_id'],lambda a:a.update(consents=None))
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'decline'},self.a),403)
        for suffix in ('/respond/','/notrespond','/respond/extra'):
            self.assertTrue(400 <= self.call('POST',self.path+suffix,{'decision':'decline'},self.a)[0] < 500)
        cancelled=self.call('POST',self.path+'/cancel',{},self.a)
        self.expect_status(cancelled,200)
        self.assertEqual(cancelled[1]['status'],'cancelled')

    def test_peer_age_changed_after_request_hides_projection_and_acceptance(self):
        self.requested()
        today=date.today()
        born=date(today.year-17,1,1).isoformat()
        self.mutate(self.ma['domain_id'],lambda a:a.update(birth_date=born))
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        r=self.call('GET',self.path,token=self.b)
        self.assertIsNone(r[1]['peer'])
        self.assertNotIn('accept',r[1]['available_actions'])

    def test_allauth_verification_revocation_is_not_overridden_by_domain_mirror(self):
        self.requested()
        EmailAddress.objects.filter(user_id=self.ma['id']).update(verified=False)
        self.expect_status(self.call('GET','/v1/candidates',token=self.a),403)
        self.assertEqual(self.call('GET','/v1/candidates',token=self.b)[1]['items'],[])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.assertIsNone(self.call('GET',self.path,token=self.b)[1]['peer'])

    def test_reciprocal_preference_change_invalidates_old_accept_hint(self):
        self.requested()
        before=self.call('GET',self.path,token=self.b)[1]
        self.assertIn('accept',before['available_actions'])
        self.expect_status(self.call('PUT','/v1/me/preferences',{
            'min_age':18,'max_age':20,'countries':[],'marital_statuses':['single']},self.a),200)
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.assertNotIn('accept',self.call('GET',self.path,token=self.b)[1]['available_actions'])

    def test_request_replay_is_current_and_key_cannot_change_target(self):
        self.requested()
        replay=self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,
                         HTTP_IDEMPOTENCY_KEY='qa_matching_request')
        self.expect_status(replay,201)
        self.assertEqual(replay[1]['id'],self.rel)
        self.expect_status(self.call('POST','/v1/relationships',{'candidate_id':self.ma['domain_id']},self.a,
                                     HTTP_IDEMPOTENCY_KEY='qa_matching_request'),409)
        self.expect_status(self.call('POST','/v1/blocks',{'target_id':self.ma['domain_id']},self.b),200)
        replay=self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,
                         HTTP_IDEMPOTENCY_KEY='qa_matching_request')
        self.expect_status(replay,201)
        self.assertEqual(replay[1]['id'],self.rel)
        self.assertIsNone(replay[1]['peer'])
        self.assert_locked(replay[1])
        self.assertNotIn('accept',replay[1]['available_actions'])

    def test_parallel_same_key_is_single_durable_request(self):
        self.ready()
        def request():return self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,
                                      HTTP_IDEMPOTENCY_KEY='qa_parallel_key')
        results=self.race([request,request])
        self.assertEqual([r[0] for r in results],[201,201])
        self.assertTrue(results[0][1]['id']==results[1][1]['id'])
        self.assertEqual(len(self.state().relationships),1)

    def test_opposite_direction_requests_have_one_unordered_pair(self):
        self.ready()
        results=self.race([
            lambda:self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,HTTP_IDEMPOTENCY_KEY='qa_opposite_a'),
            lambda:self.call('POST','/v1/relationships',{'candidate_id':self.ma['domain_id']},self.b,HTTP_IDEMPOTENCY_KEY='qa_opposite_b')])
        self.assertEqual(sorted(r[0] for r in results),[201,409])
        self.assertEqual(len(self.state().relationships),1)

    def test_accept_block_race_finishes_locked_and_report_remains_available(self):
        self.requested()
        results=self.race([
            lambda:self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),
            lambda:self.call('POST','/v1/blocks',{'target_id':self.mb['domain_id']},self.a)])
        self.assertIn(results[0][0],(200,409))
        self.expect_status(results[1],200)
        for token in (self.a,self.b):
            r=self.call('GET',self.path,token=token)
            self.expect_status(r,200)
            self.assert_locked(r[1])
            self.assertIsNone(r[1]['peer'])
            self.assertIn('report',r[1]['available_actions'])
        report=self.call('POST','/v1/reports',{'target_id':self.ma['domain_id'],'relationship_id':self.rel,
                         'category':sorted(REPORT_CATEGORIES)[0]},self.b,HTTP_IDEMPOTENCY_KEY='qa_report_after_block')
        self.expect_status(report,201)
        self.assertFalse(report[1]['evidence_uploaded'])

    def test_accept_delete_race_never_leaves_peer_or_communication_enabled(self):
        self.requested()
        results=self.race([
            lambda:self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),
            lambda:self.call('DELETE','/identity/v1/me',{'confirmation':'DELETE'},self.a)])
        self.assertTrue(results[0][0] in (200,404,409))
        self.expect_status(results[1],200)
        self.expect_status(self.call('GET','/identity/v1/me',token=self.a),401)
        r=self.call('GET',self.path,token=self.b)
        self.expect_status(r,200)
        self.assert_locked(r[1])
        self.assertIsNone(r[1]['peer'])
        self.assertNotIn('accept',r[1]['available_actions'])

    def test_no_activation_or_dialogue_endpoint_and_no_invalid_content_persistence(self):
        self.requested()
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),200)
        before=self.state()
        marker='QA_DIALOGUE_NOT_FOR_SERVER_STORAGE'
        for suffix in ('/activate','/answers','/send','/messages','/history','/selected-card','/outbox'):
            r=self.call('POST',self.path+suffix,{'simulate_entitlement':True,'answer':marker,'card_id':marker},self.a)
            self.assertTrue(400 <= r[0] < 500)
        self.assertTrue(400 <= self.call('POST','/v1/dev/session',{'actor_id':self.ma['domain_id']},self.a)[0] < 500)
        self.expect_status(self.call('GET',self.path+'/cards',token=self.a),409)
        self.assertTrue(before == self.state(),'Unsupported requests must not change persisted domain state')
        self.assert_locked(self.call('GET',self.path,token=self.a)[1])

    def test_restart_keeps_recipient_authority_and_terminal_request_replay(self):
        self.requested()
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'decline'},self.b),200)
        connections.close_all()
        RESTART_DATABASE()
        connections.close_all()
        replay=self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,
                         HTTP_IDEMPOTENCY_KEY='qa_matching_request')
        self.expect_status(replay,201)
        self.assertEqual(replay[1]['id'],self.rel)
        self.assertEqual(replay[1]['status'],'declined')
        self.assert_locked(replay[1])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.expect_status(self.call('POST','/v1/relationships',{'candidate_id':self.mb['domain_id']},self.a,
                                     HTTP_IDEMPOTENCY_KEY='qa_no_reopening'),409)

    def test_inactive_framework_peer_is_hidden_despite_domain_verification_mirror(self):
        self.requested()
        from wainek_identity.models import User
        User.objects.filter(pk=self.ma['id']).update(is_active=False)
        self.assertEqual(self.call('GET','/v1/candidates',token=self.b)[1]['items'],[])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.assertIsNone(self.call('GET',self.path,token=self.b)[1]['peer'])

    def test_married_female_and_four_wife_male_remain_ineligible(self):
        self.requested()
        self.mutate(self.mb['domain_id'],lambda a:a['profile'].update(marital_status='married'))
        self.assertEqual(self.call('GET','/v1/candidates',token=self.a)[1]['items'],[])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.mutate(self.mb['domain_id'],lambda a:a['profile'].update(marital_status='single'))
        self.mutate(self.ma['domain_id'],lambda a:a['profile'].update(marital_status='married',declared_wives=4))
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.assertNotIn('accept',self.call('GET',self.path,token=self.b)[1]['available_actions'])

    def test_turning_off_discovery_invalidates_prior_accept_hint_without_new_request(self):
        self.requested()
        self.mutate(self.ma['domain_id'],lambda a:a['profile'].update(discoverable=False))
        self.assertEqual(self.call('GET','/v1/candidates',token=self.b)[1]['items'],[])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),409)
        self.assertNotIn('accept',self.call('GET',self.path,token=self.b)[1]['available_actions'])
        self.expect_status(self.call('POST',self.path+'/respond',{'decision':'decline'},self.b),200)

    def test_future_policy_stales_existing_consents_but_preserves_exact_decline(self):
        self.requested()
        with mock.patch('wainek_identity.repository.POLICY_VERSION','future_qa_policy'):
            self.expect_status(self.call('GET','/v1/candidates',token=self.b),403)
            self.expect_status(self.call('POST',self.path+'/respond',{'decision':'accept'},self.b),403)
            r=self.call('GET',self.path,token=self.b)
            self.expect_status(r,200)
            self.assertIsNone(r[1]['peer'])
            self.assertNotIn('accept',r[1]['available_actions'])
            self.assertIn('decline',r[1]['available_actions'])
            self.expect_status(self.call('POST',self.path+'/respond',{'decision':'decline'},self.b),200)
