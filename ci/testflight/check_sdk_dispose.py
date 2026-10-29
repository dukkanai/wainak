"""Execute the exact reviewed Dart helper against deterministic owned-process models."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ci.testflight import sdk_overlay as s
from scripts.ci_process import run_bounded

FIXTURE = r'''
import 'dart:async';
import 'dart:io' as io;
import 'package:flutter_tools/src/base/io.dart';

class OwnedProcess implements Process {
  final done = Completer<int>();
  final String mode;
  int calls = 0;
  bool collected = false;
  OwnedProcess(this.mode);
  Future<int> get exitCode => done.future.then((value) { collected = true; return value; });
  bool kill([io.ProcessSignal signal = io.ProcessSignal.sigterm]) {
    calls++;
    if (calls == 1) {
      if (mode == 'error') { scheduleMicrotask(() => done.completeError(StateError('CANARY'))); }
      else if (['ok', 'false', 'throw', 'race'].contains(mode)) {
        Timer(const Duration(milliseconds: 5), () => done.complete(0));
      }
      if (mode == 'false') return false;
      if (mode == 'throw') throw StateError('CANARY');
    } else {
      if (signal != io.ProcessSignal.sigkill) throw StateError('wrong_signal');
      if (['timeout', 'kill_false'].contains(mode)) done.complete(-9);
      if (mode == 'kill_false') return false;
      if (mode == 'kill_throw') throw StateError('CANARY');
    }
    return true;
  }
  dynamic noSuchMethod(Invocation invocation) => throw StateError('unexpected_process_operation');
}
void require(bool value) { if (!value) throw StateError('fixture_assertion'); }
Future<void> main(List<String> args) async {
  var count = 0;
  for (final mode in ['ok','false','throw','race','error','timeout','never','kill_false','kill_throw']) {
    // Already exited: kill may still report success; collect its future first.
    final owner = OwnedProcess(mode == 'race' ? 'never' : mode);
    if (mode == 'race') owner.done.complete(0);
    String? failure;
    try {
      await stopAnalysisServerOwnedProcess(owner,
        termTimeout: const Duration(milliseconds: 100), killTimeout: const Duration(milliseconds: 30));
    } catch (e) { failure = e.toString(); }
    if (['ok','race'].contains(mode)) {
      require(failure == null && owner.collected && owner.calls == 1);
    } else {
      final expected = ['false','throw'].contains(mode) ? 'SIGNAL_FAILED' :
          ['timeout','kill_false'].contains(mode) ? 'TERM_TIMEOUT' : 'EXIT_UNVERIFIED';
      require(failure == 'Bad state: WAINEK_ANALYSIS_SERVER_$expected');
      require(!failure!.contains('CANARY'));
      if (['timeout','never','kill_false','kill_throw'].contains(mode)) require(owner.calls == 2);
      if (['false','throw','timeout','kill_false'].contains(mode)) require(owner.collected);
    }
    count++;
  }
  for (final ignoreTerm in [false, true]) {
    final child = await io.Process.start(args.single, ['-u', '-c',
      'import signal,time; '+(ignoreTerm ? 'signal.signal(signal.SIGTERM,signal.SIG_IGN); ' : '')+
      'print("READY",flush=True); time.sleep(30)']);
    String? failure;
    try {
      await child.stdout.first.timeout(const Duration(seconds: 3));
      try {
        await stopAnalysisServerOwnedProcess(child,
          termTimeout: const Duration(milliseconds: 100), killTimeout: const Duration(seconds: 2));
      } catch (e) { failure = e.toString(); }
      require(failure == (ignoreTerm ? 'Bad state: WAINEK_ANALYSIS_SERVER_TERM_TIMEOUT' : null));
      await child.exitCode.timeout(const Duration(seconds: 1));
    } finally {
      child.kill(io.ProcessSignal.sigkill);
      await child.exitCode.timeout(const Duration(seconds: 2));
    }
    count++;
  }
  print('PASS_SDK_DISPOSE_MODELS_$count');
}
'''


def check(overlay, work, env):
    overlay.verify()
    _, helper=s.delta()
    fixture=work/'sdk_dispose_fixture.dart'
    with fixture.open('x') as output:output.write(FIXTURE+'\n'+helper.decode())
    result=run_bounded([overlay.base/'bin/cache/dart-sdk/bin/dart','--disable-dart-dev',
        '--packages='+str(overlay.destination/'package_config.json'),fixture,sys.executable],
        cwd=work,env=env,seconds=30,check=True)
    overlay.verify()
    if result.stdout.strip() != 'PASS_SDK_DISPOSE_MODELS_11':raise ValueError('sdk_dispose_fixture')
    return {'status':'PASS_SDK_DISPOSE_MODELS','cases':11,'helper_sha256':s.delta()[0]['helper_sha256']}
