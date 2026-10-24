import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/api/transport.dart';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/identity/client.dart';

typedef Handler = Future<ApiResponse> Function(String, Uri, Map<String,String>, String?);
ApiResponse reply(int s, Map<String,dynamic> b) => ApiResponse(s,jsonEncode(b));
ApiResponse proof(String actor) => reply(200, {
  'email_verified':true,'email_is_identity_verification':false,
  'mode':'synthetic_identity_sandbox',
  'id': actor=='a'?'11111111-1111-4111-8111-111111111111':'22222222-2222-4222-8222-222222222222',
  'domain_id': actor=='a'?'usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa':'usr_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  'email':'$actor@example.invalid'});
class Fixture implements ApiTransport {
  Handler? intercept;
  final calls=<String>[];
  @override
  Future<ApiResponse> send(String m, Uri u, Map<String,String> h, String? b) async {
    calls.add('$m ${u.path}');
    if(intercept!=null)return intercept!(m,u,h,b);
    return normal(m,u,h,b);
  }
  Future<ApiResponse> normal(String m,Uri u,Map<String,String> h,String? b) async {
    if(u.path.endsWith('/auth/login')){
      final email=(jsonDecode(b!) as Map)['email'] as String;
      return reply(200,{'meta':{'is_authenticated':true,'session_token':'fixture-${email[0]}'}});
    }
    if(u.path=='/identity/v1/me'&&m=='GET')return proof(h['X-Session-Token']=='fixture-a'?'a':'b');
    if(u.path=='/v1/me')return reply(200,{'id':h['X-Session-Token']=='fixture-a'?'usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa':'usr_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'});
    if(u.path=='/identity/v1/reauthenticate')return reply(200,{'reauthenticated':true});
    if(u.path=='/identity/v1/me'&&m=='DELETE')return reply(200,{'identity_erased':true});
    if(u.path=='/identity/v1/logout-all')return reply(200,{'revoked_all':true});
    return reply(404,{'error':{'code':'not_found'}});
  }
  @override void close(){}
}
IdentityClient client(Fixture f)=>IdentityClient(baseUri:Uri.parse('http://127.0.0.1:8089'),transport:f);
Future<void> login(IdentityClient c,String actor)=>c.login('$actor@example.invalid','SyntheticFixtureOnly!123');
Future<bool> rejected(Future<void> f) async {try{await f;return false;}on IdentityFailure{return true;}}
void check(bool b){if(!b)throw StateError('independent lifecycle assertion failed');}
Future<void> retainedB(IdentityClient c) async {
  check(c.authenticated&&c.accountLabel=='b@example.invalid');
  final me=await c.domain('GET','/v1/me');check(me['id']=='usr_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
}
Future<void> main() async {
  final cases=<String,Future<void> Function()>{
    'late A domain401 does not clear B':() async {
      final f=Fixture(), held=Completer<ApiResponse>();final c=client(f);
      try{await login(c,'a');
        f.intercept=(m,u,h,b)=>u.path=='/v1/me'&&h['X-Session-Token']=='fixture-a'?held.future:f.normal(m,u,h,b);
        final late=c.domain('GET','/v1/me').then<void>((_){});final result=rejected(late);
        await login(c,'b');held.complete(reply(401,{'error':{'code':'unauthenticated'}}));
        check(await result);await retainedB(c);
      }finally{c.close();}
    },
    'late A proof cannot replace B':() async {
      final f=Fixture(), held=Completer<ApiResponse>(), started=Completer<void>();final c=client(f);
      try{f.intercept=(m,u,h,b){if(u.path=='/identity/v1/me'&&h['X-Session-Token']=='fixture-a'){started.complete();return held.future;}return f.normal(m,u,h,b);};
        final result=rejected(login(c,'a'));await started.future;await login(c,'b');held.complete(proof('a'));
        check(await result);await retainedB(c);
      }finally{c.close();}
    },
    'A reauth cannot continue deletion after B login':() async {
      final f=Fixture(), held=Completer<ApiResponse>();final c=client(f);
      try{await login(c,'a');f.intercept=(m,u,h,b)=>u.path=='/identity/v1/reauthenticate'?held.future:f.normal(m,u,h,b);
        final result=rejected(c.deleteAccount('SyntheticFixtureOnly!123',confirmed:true,expectedGeneration:c.sessionGeneration));
        await login(c,'b');held.complete(reply(200,{'reauthenticated':true}));check(await result);
        check(!f.calls.contains('DELETE /identity/v1/me'));await retainedB(c);
      }finally{c.close();}
    },
    'stale confirmation sends no request':() async {
      final f=Fixture();final c=client(f);
      try{await login(c,'a');final generation=c.sessionGeneration;await login(c,'b');final before=f.calls.length;
        check(await rejected(c.deleteAccount('SyntheticFixtureOnly!123',confirmed:true,expectedGeneration:generation)));
        check(f.calls.length==before);await retainedB(c);
      }finally{c.close();}
    },
    'close rejects late identity proof':() async {
      final f=Fixture(), held=Completer<ApiResponse>(), started=Completer<void>();final c=client(f);
      f.intercept=(m,u,h,b){if(u.path=='/identity/v1/me'){started.complete();return held.future;}return f.normal(m,u,h,b);};
      final result=rejected(login(c,'a'));await started.future;c.close();held.complete(proof('a'));
      check(await result);check(c.stage==IdentityStage.signedOut&&c.identity==null&&c.accountLabel==null);
    },
    'old logout-all response cannot clear newer B':() async {
      final f=Fixture(), held=Completer<ApiResponse>();final c=client(f);
      try{await login(c,'a');f.intercept=(m,u,h,b)=>u.path=='/identity/v1/logout-all'?held.future:f.normal(m,u,h,b);
        final result=rejected(c.logout(everywhere:true));await login(c,'b');held.complete(reply(200,{'revoked_all':true}));
        check(await result);await retainedB(c);
      }finally{c.close();}
    },
  };
  var failures=0;
  for(final entry in cases.entries){try{await entry.value();stdout.writeln('PASS: ${entry.key}');}catch(_){failures++;stdout.writeln('FAIL: ${entry.key}; private operands suppressed');}}
  stdout.writeln('Independent actor lifecycle cases:${cases.length}; failed:$failures; no network or real credentials.');
  exitCode=failures==0?0:1;
}
