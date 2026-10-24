import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/identity/client.dart';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/api/transport_io.dart';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/tool/identity_fixture_bridge.dart';

void check(bool value){if(!value)throw StateError('independent live lifecycle assertion failed');}
String nonce()=>base64UrlEncode(List<int>.generate(18,(_)=>Random.secure().nextInt(256))).replaceAll('=','');
String email()=> 'qa_${nonce().toLowerCase().replaceAll(RegExp('[^a-z0-9]'),'')}@example.invalid';
Future<void> signup(IdentityClient c,String mail,String password)=>c.signup(email:mail,password:password,age:29,adult:true,muslim:true,terms:true,privacy:true);
Future<bool> rejects(Future<void> action) async {try{await action;return false;}on IdentityFailure{return true;}}

Future<void> main(List<String> args) async {
  if(args.length!=1||args.single!='--run-disposable-identity'){
    stderr.writeln('Explicit isolated identity opt-in required; no fixture started.');exitCode=2;return;
  }
  IdentityFixtureBridge? fixture;
  final clients=<IdentityClient>[];
  var passed=false;
  try{
    fixture=await IdentityFixtureBridge.start();
    IdentityClient fresh(){final c=IdentityClient(baseUri:fixture!.baseUri,transport:NativeApiTransport(timeout:const Duration(seconds:35)));clients.add(c);return c;}

    // Actual current pending flow, not a forged email-only deletion request.
    final pending=fresh(), former=fresh();
    final pendingMail=email(), pendingPassword='${nonce()}!7aZ';
    await signup(pending,pendingMail,pendingPassword);
    check(pending.stage==IdentityStage.pendingVerification);
    check(await rejects(pending.deleteAccount('${nonce()}!8aZ',confirmed:true,expectedGeneration:pending.sessionGeneration)));
    check(pending.stage==IdentityStage.pendingVerification);
    await pending.deleteAccount(pendingPassword,confirmed:true,expectedGeneration:pending.sessionGeneration);
    check(pending.stage==IdentityStage.signedOut&&pending.identity==null);
    check(await rejects(former.login(pendingMail,pendingPassword)));
    check(former.stage==IdentityStage.signedOut);

    // A duplicate anti-enumeration signup flow must not erase an existing actor,
    // even when this controlled test supplies that actor's current password.
    final owner=fresh(), duplicate=fresh(), oldSession=fresh();
    final existingMail=email(), existingPassword='${nonce()}!7aZ';
    await signup(owner,existingMail,existingPassword);
    final verification=await fixture.verification(existingMail);
    await owner.verify(verification.code);check(owner.authenticated);
    await oldSession.login(existingMail,existingPassword);check(oldSession.authenticated);
    await signup(duplicate,existingMail,existingPassword);
    check(duplicate.stage==IdentityStage.pendingVerification);
    check(await rejects(duplicate.deleteAccount(existingPassword,confirmed:true,expectedGeneration:duplicate.sessionGeneration)));
    check(duplicate.stage==IdentityStage.signedOut);
    final actual=await owner.domain('GET','/v1/me');
    check(actual['id']==owner.identity?['domain_id']&&owner.authenticated);
    await owner.deleteAccount(existingPassword,confirmed:true,expectedGeneration:owner.sessionGeneration);
    check(owner.stage==IdentityStage.signedOut);
    check(await rejects(oldSession.domain('GET','/v1/me').then<void>((_){})));
    check(oldSession.stage==IdentityStage.signedOut&&oldSession.identity==null);

    await fixture.shutdown();passed=true;
    stdout.writeln('INDEPENDENT_LIVE_DELETION_PASS: owned pending deletion and duplicate-flow isolation; framework/HTTP/PG; normal cleanup acknowledged.');
  }catch(_){
    stderr.writeln('INDEPENDENT_LIVE_DELETION_FAILED: private values suppressed; no successful cleanup claim.');exitCode=1;
  }finally{
    for(final c in clients){c.close();}
    if(!passed&&fixture!=null){try{await fixture.abort();}catch(_){stderr.writeln('OWNED_FIXTURE_AUDIT_REQUIRED');exitCode=1;}}
  }
}
