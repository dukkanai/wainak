// QA-only pure Dart: injected transport, no network/server/Flutter compiler.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import '../../apps/mobile/lib/src/api/transport.dart';
import '../../apps/mobile/lib/src/identity/client.dart';
import '../../apps/mobile/lib/src/identity/matching_repository.dart';

const actor='usr_11111111111111111111111111111111';
const peer='usr_22222222222222222222222222222222';
const rid='rel_33333333333333333333333333333333';
Map<String,dynamic> candidate()=>{'id':peer,'alias':'اسم اصطناعي قبل الحظر','age':31,'country':'SA','marital_status':'single','marriage_goal':'build_family','rating':{'state':'insufficient_data'},'synthetic':true};
Map<String,dynamic> relation({String status='requested',bool incoming=false,bool redacted=false})=>{
'id':rid,'initiator_id':incoming?peer:actor,'recipient_id':incoming?actor:peer,'status':status,'peer':redacted?null:candidate(),
'exclusive_requested_by':null,'permissions':{'can_send_cards':false,'can_send_text':false,'can_send_media':false,'can_disclose_identity':false},
'activation_mode':'development_simulation_only','direction':incoming?'incoming':'outgoing',
'available_actions':status=='requested'?(incoming?['accept','decline','block','report']:['cancel','block','report']):status=='blocked'?['block','report']:['end','block','report']};
ApiResponse response(int status,Object body)=>ApiResponse(status,jsonEncode(body));
void require(bool condition,String label){if(!condition)throw StateError(label);}
Future<void> tolerateStale(Future<dynamic> value)async{try{await value;}on IdentityFailure { /* Rejected superseded operations are safe. */ }}

class Fixture implements ApiTransport{
 bool incoming=false,blocked=false,holdRelations=false,holdCandidates=false,holdAct=false,reportPurged=false;
 Completer<ApiResponse>? relationsPending,candidatesPending,actPending;
 @override Future<ApiResponse> send(String method,Uri uri,Map<String,String> headers,String? body)async{
  final path=uri.path;
  if(path.endsWith('/auth/login'))return response(200,{'status':200,'meta':{'is_authenticated':true,'session_token':'qa-synthetic-transport-only'},'data':{'flows':[]}});
  if(path=='/identity/v1/me')return response(200,{'id':'11111111-1111-4111-8111-111111111111','domain_id':actor,'email':'qa@example.invalid','email_verified':true,'email_is_identity_verification':false,'mode':'synthetic_identity_sandbox'});
  if(path=='/v1/relationships'&&method=='GET'){
   if(holdRelations){relationsPending=Completer<ApiResponse>();return relationsPending!.future;}
   return response(200,{'items':[relation(incoming:incoming,status:blocked?'blocked':'requested',redacted:blocked)]});
  }
  if(path=='/v1/candidates'){
   if(holdCandidates){candidatesPending=Completer<ApiResponse>();return candidatesPending!.future;}
   return response(200,{'items':blocked?[]:[candidate()],'mode':'synthetic_development_only'});
  }
  if(path=='/v1/blocks'){blocked=true;return response(200,{'blocked':true});}
  if(path=='/v1/relationships/$rid/respond'){
   if(holdAct){actPending=Completer<ApiResponse>();return actPending!.future;}
   return response(200,relation(status:'accepted_pending_activation',incoming:incoming));
  }
  if(path=='/v1/reports'&&reportPurged)return response(410,{'error':{'code':'report_no_longer_available','message':'fixture'}});
  throw StateError('Unexpected fixed fixture route');
 }
 @override void close(){}
}
Future<(Fixture,IdentityClient,IdentityMatchingRepository)> setup({bool incoming=false})async{
 final f=Fixture()..incoming=incoming;
 final c=IdentityClient(baseUri:Uri.parse('http://127.0.0.1:8099'),transport:f);
 await c.login('qa@example.invalid','SyntheticFixtureOnly!12');
 return(f,c,IdentityMatchingRepository(c));
}
Future<void> waitStarted(bool Function() done)async{
 for(var i=0;i<20&&!done();i++){await Future<void>.delayed(Duration.zero);}
 require(done(),'Deferred fixture request did not start');
}
// Serialization is also safe: if block has not acknowledged, release the older
// operation and then await block. The vulnerable path acknowledges first.
Future<void> blockAndRelease(IdentityMatchingRepository repo,MatchSafetyContext context,void Function() release)async{
 var acknowledged=false;
 final block=repo.block(context).then((_) {acknowledged=true;});
 await Future<void>.delayed(const Duration(milliseconds:10));
 release();
 await block;
 require(acknowledged,'Block did not acknowledge');
}
Future<void> main()async{
 var passed=0,failed=0;
 Future<void> test(String label,Future<void>Function() fn)async{
  try{await fn().timeout(const Duration(seconds:5));passed++;stdout.writeln('PASS $label');}
  catch(error){failed++;final safe=error is StateError && {'Old peer/actions restored','Accepted peer restored','Blocked candidate restored'}.contains(error.message)?error.message:'private fixture operands suppressed';stdout.writeln('FAIL $label ($safe)');}
 }
 await test('late relationship refresh cannot restore peer after block acknowledgement',()async{
  final(f,c,r)=await setup();
  try{
   await r.refreshRelationships();final context=r.relationshipContext(r.relationships.single);
   f.holdRelations=true;final pending=tolerateStale(r.refreshRelationships());await waitStarted(()=>f.relationsPending!=null);
   await blockAndRelease(r,context,()=>f.relationsPending!.complete(response(200,{'items':[relation()]})));
   await pending;
   require(r.relationships.every((x)=>x.peer==null&&!x.can(MatchAction.cancel)),'Old peer/actions restored');
  }finally{r.close();c.close();}
 });
 await test('late accept response cannot restore peer after block acknowledgement',()async{
  final(f,c,r)=await setup(incoming:true);
  try{
   await r.refreshRelationships();final rel=r.relationships.single;final context=r.relationshipContext(rel);
   f.holdAct=true;final pending=tolerateStale(r.act(rel,MatchAction.accept));await waitStarted(()=>f.actPending!=null);
   await blockAndRelease(r,context,()=>f.actPending!.complete(response(200,relation(status:'accepted_pending_activation',incoming:true))));
   await pending;
   require(r.relationships.every((x)=>x.peer==null&&x.status!='accepted_pending_activation'),'Accepted peer restored');
  }finally{r.close();c.close();}
 });
 await test('late candidate refresh cannot restore a blocked target',()async{
  final(f,c,r)=await setup();
  try{
   await r.refreshCandidates();final context=r.candidateContext(r.candidates.single);
   f.holdCandidates=true;final pending=tolerateStale(r.refreshCandidates());await waitStarted(()=>f.candidatesPending!=null);
   await blockAndRelease(r,context,()=>f.candidatesPending!.complete(response(200,{'items':[candidate()],'mode':'synthetic_development_only'})));
   await pending;require(r.candidates.every((x)=>x.id!=peer),'Blocked candidate restored');
  }finally{r.close();c.close();}
 });
 await test('report tombstone410 is business-only, not session loss',()async{
  final(f,c,r)=await setup();
  try{
   await r.refreshCandidates();final context=r.candidateContext(r.candidates.single);
   f.reportPurged=true;var rejected=false;
   try{await r.report(context,'harassment');}on IdentityFailure catch(e){rejected=e.code=='report_no_longer_available';}
   require(rejected&&c.authenticated&&r.current,'Domain410 erased authentication');
  }finally{r.close();c.close();}
 });
 stdout.writeln('QA_MATCHING_RACES passed=$passed failed=$failed');
 exitCode=failed==0?0:1;
}
