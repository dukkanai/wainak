// Independent QA only: no network, Flutter, storage or real relationship.
import 'dart:io';
import '../../apps/mobile/lib/src/local_cards/catalog.dart';
import '../../apps/mobile/lib/src/local_cards/controller.dart';

void require(bool value) { if (!value) throw StateError('QA invariant failed'); }
String state(LocalDraftController c) => '${c.stage}|${c.acknowledged}|${c.card?.id}|${c.response?.id}';
void rejects(void Function() call, LocalDraftFailureCode code) {
  var found=false;
  try { call(); } on LocalDraftFailure catch(e) { found=e.code==code && e.toString()=='LocalDraftFailure'; }
  require(found);
}
void catalogRejects(void Function() call) {
  var found=false;
  try { call(); } on LocalCatalogFailure catch(e) { found=e.toString()=='LocalCatalogFailure'; }
  require(found);
}
LocalCardResponse response(String id)=>LocalCardResponse(id:id,label:'اختيار محلي للاختبار');
LocalDialogueCard card(String id,List<LocalCardResponse> r)=>LocalDialogueCard(id:id,topic:LocalCardTopic.dailyLife,title:'بطاقة محلية',prompt:'سؤال محلي للاختبار',responses:r);
LocalDraftController fresh()=>LocalDraftController(sampleLocalCatalog());
void begin(LocalDraftController c)=>c.start(c.viewToken,acceptedLocalOnly:true);
void openFirst(LocalDraftController c) { begin(c);c.openCard(c.viewToken,c.catalog.cards.first.id); }
void makePreview(LocalDraftController c) { openFirst(c);c.choose(c.viewToken,c.card!.responses.first.id);c.preview(c.viewToken); }
void emptyLocked(LocalDraftController c)=>require(c.stage==LocalDraftStage.locked&&!c.acknowledged&&c.card==null&&c.response==null);

void main() {
 final cases=<String,void Function()>{
  'development opt-in and release gate fail closed':(){
    for(final enabled in [false,true])for(final release in [false,true])for(final mode in ['local_cards','identity','api','fake','LOCAL_CARDS','']){
      require(localCardsModeAllowed(developmentEnabled:enabled,releaseMode:release,mode:mode)==(enabled&&!release&&mode=='local_cards'));
    }
  },
  'static sample bounds and deferred choice remain non-scoring':(){
    final k=sampleLocalCatalog();require(k.locale=='ar'&&k.cards.length==4);
    for(final c in k.cards){require(c.responses.length>=2&&c.responses.length<=5);require(c.responses.any((r)=>r.id.endsWith('_defer')));}
    require(k.toString()=='LocalDialogueCatalog'&&k.cards.first.toString()=='LocalDialogueCard'&&k.cards.first.responses.first.toString()=='LocalCardResponse');
  },
  'invalid IDs and copy boundaries reject at runtime':(){
    for(final id in ['', 'x','UPPER','with space','aa-bb',List.filled(49,'a').join()]){catalogRejects(()=>response(id));}
    for(final label in ['', ' ', ' مسبوق','لاحق ','أ\u0000ب','أ\u202eب',List.filled(121,'أ').join()]){catalogRejects(()=>LocalCardResponse(id:'valid_id',label:label));}
  },
  'card response bounds and duplicate responses reject':(){
    catalogRejects(()=>card('card_x',[response('resp_a')]));
    catalogRejects(()=>card('card_x',List.generate(6,(i)=>response('resp_$i'))));
    catalogRejects(()=>card('card_x',[response('resp_a'),response('resp_a')]));
  },
  'catalog cardinality locale and response namespace reject':(){
    final a=card('card_a',[response('resp_a'),response('resp_b')]);
    catalogRejects(()=>LocalDialogueCatalog(version:'version_a',locale:'ar',cards:[]));
    catalogRejects(()=>LocalDialogueCatalog(version:'version_a',locale:'en',cards:[a]));
    catalogRejects(()=>LocalDialogueCatalog(version:'version_a',locale:'ar',cards:[a,a]));
    final b=card('card_b',[response('resp_a'),response('resp_c')]);
    catalogRejects(()=>LocalDialogueCatalog(version:'version_a',locale:'ar',cards:[a,b]));
    final many=List.generate(13,(i)=>card('card_$i',[response('resp_${i}_a'),response('resp_${i}_b')]));
    catalogRejects(()=>LocalDialogueCatalog(version:'version_a',locale:'ar',cards:many));
  },
  'deep immutability includes original input aliases':(){
    final responses=[response('resp_a'),response('resp_b')];final a=card('card_a',responses);responses.clear();require(a.responses.length==2);
    final cards=[a];final k=LocalDialogueCatalog(version:'version_a',locale:'ar',cards:cards);cards.clear();require(k.cards.length==1);
    var outer=false,inner=false;
    try{k.cards.clear();}on UnsupportedError{outer=true;}
    try{k.cards.first.responses.clear();}on UnsupportedError{inner=true;}
    require(outer&&inner&&k.cards.first.responses.length==2);
  },
  'initial state and denied acknowledgement are atomic':(){
    final c=fresh();try{emptyLocked(c);final token=c.viewToken;final before=state(c);rejects(()=>c.start(token,acceptedLocalOnly:false),LocalDraftFailureCode.acknowledgementRequired);require(state(c)==before);c.start(token,acceptedLocalOnly:true);require(c.stage==LocalDraftStage.catalog);}finally{c.dispose();}
  },
  'successful transition invalidates prior rendered token':(){
    final c=fresh();try{final token=c.viewToken;begin(c);final before=state(c);rejects(()=>c.start(token,acceptedLocalOnly:true),LocalDraftFailureCode.staleView);require(state(c)==before);}finally{c.dispose();}
  },
  'current token cannot repeat start in catalog':(){
    final c=fresh();try{begin(c);final token=c.viewToken;final before=state(c);rejects(()=>c.start(token,acceptedLocalOnly:true),LocalDraftFailureCode.invalidAction);require(state(c)==before);c.openCard(token,c.catalog.cards.first.id);}finally{c.dispose();}
  },
  'cross-controller equal revision and card tokens reject':(){
    final a=fresh(),b=fresh();try{openFirst(a);openFirst(b);final before=state(b);rejects(()=>b.choose(a.viewToken,b.card!.responses.first.id),LocalDraftFailureCode.staleView);require(state(b)==before);}finally{a.dispose();b.dispose();}
  },
  'host current-view predicate is false for stale foreign and disposed tokens':(){
    final a=fresh(),b=fresh();try{final old=a.viewToken;require(a.isCurrentView(old)&&!b.isCurrentView(old));begin(a);require(!a.isCurrentView(old)&&a.isCurrentView(a.viewToken));final before=state(a);require(!a.isCurrentView(b.viewToken)&&state(a)==before);a.dispose();require(!a.isCurrentView(a.viewToken));}finally{a.dispose();b.dispose();}
  },
  'cross-version controller tokens reject':(){
    final a=fresh();final b=LocalDraftController(LocalDialogueCatalog(version:'other_v1',locale:'ar',cards:a.catalog.cards));try{rejects(()=>b.start(a.viewToken,acceptedLocalOnly:true),LocalDraftFailureCode.staleView);emptyLocked(b);}finally{a.dispose();b.dispose();}
  },
  'unknown card preserves existing draft and token':(){
    final c=fresh();try{makePreview(c);final token=c.viewToken;final before=state(c);rejects(()=>c.openCard(token,'unknown_card'),LocalDraftFailureCode.unknownCard);require(state(c)==before);c.returnToCatalog(token);}finally{c.dispose();}
  },
  'wrong-card response preserves current state and token':(){
    final c=fresh();try{openFirst(c);final token=c.viewToken;final before=state(c);rejects(()=>c.choose(token,c.catalog.cards[1].responses.first.id),LocalDraftFailureCode.unknownResponse);require(state(c)==before);c.choose(token,c.card!.responses.first.id);}finally{c.dispose();}
  },
  'preview requires a selected allowlisted response':(){
    final c=fresh();try{openFirst(c);final token=c.viewToken;final before=state(c);rejects(()=>c.preview(token),LocalDraftFailureCode.invalidAction);require(state(c)==before);c.choose(token,c.card!.responses.first.id);}finally{c.dispose();}
  },
  'repeat selection and preview have no extra transition':(){
    final c=fresh();try{openFirst(c);c.choose(c.viewToken,c.card!.responses.first.id);final token=c.viewToken;final before=state(c);c.choose(token,c.response!.id);require(state(c)==before);c.preview(token);final preview=c.viewToken;final after=state(c);c.preview(preview);c.preview(preview);require(state(c)==after);}finally{c.dispose();}
  },
  'changing cards clears response and rejects former callbacks':(){
    final c=fresh();try{makePreview(c);final old=c.viewToken;c.openCard(old,c.catalog.cards[1].id);require(c.response==null&&c.stage==LocalDraftStage.choosing);final before=state(c);rejects(()=>c.choose(old,c.catalog.cards.first.responses.first.id),LocalDraftFailureCode.staleView);require(state(c)==before);}finally{c.dispose();}
  },
  'return to catalog retains only local acceptance':(){
    final c=fresh();try{makePreview(c);final old=c.viewToken;c.returnToCatalog(old);require(c.stage==LocalDraftStage.catalog&&c.acknowledged&&c.card==null&&c.response==null);rejects(()=>c.preview(old),LocalDraftFailureCode.staleView);}finally{c.dispose();}
  },
  'clear removes acknowledgement and rejects queued start':(){
    final c=fresh();try{final start=c.viewToken;makePreview(c);final responseToken=c.viewToken;c.clear();emptyLocked(c);rejects(()=>c.start(start,acceptedLocalOnly:true),LocalDraftFailureCode.staleView);rejects(()=>c.preview(responseToken),LocalDraftFailureCode.staleView);emptyLocked(c);begin(c);require(c.stage==LocalDraftStage.catalog&&c.response==null);}finally{c.dispose();}
  },
  'all invalidation reasons remove preview without token authority':(){
    for(final reason in LocalDraftInvalidation.values){final c=fresh();try{makePreview(c);final old=c.viewToken;c.invalidate(reason);emptyLocked(c);rejects(()=>c.preview(old),LocalDraftFailureCode.staleView);}finally{c.dispose();}}
  },
  'repeated clear keeps locked empty state and invalidates view':(){
    final c=fresh();try{c.clear();final old=c.viewToken;c.clear();emptyLocked(c);rejects(()=>c.start(old,acceptedLocalOnly:true),LocalDraftFailureCode.staleView);}finally{c.dispose();}
  },
  'disposed is terminal even with a newly read inert token':(){
    final c=fresh();makePreview(c);final old=c.viewToken;c.dispose();c.clear();c.invalidate(LocalDraftInvalidation.background);c.dispose();require(c.stage==LocalDraftStage.disposed&&!c.acknowledged&&c.card==null&&c.response==null);rejects(()=>c.start(c.viewToken,acceptedLocalOnly:true),LocalDraftFailureCode.closed);rejects(()=>c.preview(old),LocalDraftFailureCode.closed);
  },
  'diagnostic string surfaces exclude chosen content':(){
    final c=fresh();try{makePreview(c);require(c.toString()=='LocalDraftController'&&c.viewToken.toString()=='LocalDraftViewToken');rejects(()=>c.choose(c.viewToken,'private_unknown_fixture'),LocalDraftFailureCode.invalidAction);}finally{c.dispose();}
  },
 };
 var failed=0;
 for(final e in cases.entries){try{e.value();stdout.writeln('PASS ${e.key}');}catch(_){failed++;stdout.writeln('FAIL ${e.key}; private operands suppressed');}}
 stdout.writeln('QA_LOCAL_CARDS cases=${cases.length} failed=$failed; pure Dart fixture only');
 exitCode=failed==0?0:1;
}
