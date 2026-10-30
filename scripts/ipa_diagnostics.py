"""Finite Flutter/Xcode IPA observations; never return any captured text."""
import re

PROFILE='flutter_internal_ipa'
PATTERNS={
    'PROFILE_NOT_FOUND':(rb'No profiles for .{1,1024} were found',rb'No profile for team .{1,1024} matching .{1,1024} found',rb'requires a provisioning profile'),
    'PROFILE_MISMATCH':(rb'Provisioning profile .{1,1024} (?:does not|doesn\x27t) (?:include|match|support)',),
    'IDENTITY_MISSING':(rb'No signing certificate .{1,1024} found',rb'No valid code signing certificates were found',rb'No development certificates available to code sign'),
    'SIGNING_ACCESS':(rb'User interaction is not allowed',),
    'SIGNING_OPERATION':(rb'errSecInternalComponent',rb'Command CodeSign failed with a nonzero exit code'),
    'TRUST_CHAIN':(rb'unable to build chain to self-signed root for signer',rb'CSSMERR_TP_NOT_TRUSTED'),
    'SCRIPT_FAILED':(rb'Command PhaseScriptExecution failed with a nonzero exit code',),
    'COMPILE_FAILED':(rb'Swift Compiler Error',rb'Lexical or Preprocessor Issue',rb'Parse Issue \(Xcode\)'),
    'SETTINGS_MISSING':(rb'No Xcode build settings have been found',),
    'DESTINATION_UNAVAILABLE':(rb'Unable to find a destination matching',),
    'ARCHIVE_FAILED':(rb'^\*\* ARCHIVE FAILED \*\*$',rb'Encountered error while archiving for '),
    'EXPORT_FAILED':(rb'Encountered error while creating the IPA:',rb'error: exportArchive'),
}
MILESTONES={
    'archive_requested':rb'^Archiving .{1,2048}',
    'xcode_build_started':rb'^Running Xcode build',
    'archive_completed':rb'(?:^\*\* ARCHIVE SUCCEEDED \*\*$|Built .{1,2048}\.xcarchive(?: .*)?$)',
    'export_started':rb'^Building App Store(?: Connect)? IPA',
    'ipa_built':rb'Built IPA to ',
}
CERTIFICATE_NAMES={
    b'Apple Distribution':'APPLE_DISTRIBUTION',b'iOS Distribution':'IOS_DISTRIBUTION',
    b'iPhone Distribution':'IPHONE_DISTRIBUTION',b'Apple Development':'APPLE_DEVELOPMENT',
    b'iOS Development':'IOS_DEVELOPMENT',b'iPhone Developer':'IPHONE_DEVELOPER',
}
CERTIFICATE_TYPES=frozenset(CERTIFICATE_NAMES.values())|{'OTHER','DEVELOPMENT_UNSPECIFIED'}
TARGETS=frozenset({'RUNNER','RUNNER_TESTS','OTHER'})
REASONS=frozenset('build_ipa_'+x.lower() for x in (*PATTERNS,'UNCLASSIFIED','CLASSIFIER_FAILED'))


def empty(status='UNCLASSIFIED',complete=False):
    return {'status':status,'categories':[],'milestones':{x:False for x in MILESTONES},'complete_output':complete,
        'requested_certificate_types':[],'failure_targets':[]}


def project(value):
    if type(value) is not dict or set(value)!={'status','categories','milestones','complete_output','requested_certificate_types','failure_targets'}:return empty('CLASSIFIER_FAILED')
    if type(value['status']) is not str or value['status'] not in {'RECOGNIZED','UNCLASSIFIED','CLASSIFIER_FAILED'}:return empty('CLASSIFIER_FAILED')
    categories=value['categories'];marks=value['milestones']
    if type(categories) is not list or len(categories)>len(PATTERNS) or any(type(c) is not str or c not in PATTERNS for c in categories):return empty('CLASSIFIER_FAILED')
    if type(marks) is not dict or set(marks)!=set(MILESTONES) or any(type(v) is not bool for v in marks.values()) or type(value['complete_output']) is not bool:return empty('CLASSIFIER_FAILED')
    if (value['status']=='RECOGNIZED')!=bool(categories):return empty('CLASSIFIER_FAILED')
    for field,allowed in (('requested_certificate_types',CERTIFICATE_TYPES),('failure_targets',TARGETS)):
        if type(value[field]) is not list or len(value[field])>len(allowed) or any(type(x) is not str or x not in allowed for x in value[field]):return empty('CLASSIFIER_FAILED')
    return {'status':value['status'],'categories':sorted(set(categories)),'milestones':dict(marks),'complete_output':value['complete_output'],
        'requested_certificate_types':sorted(set(value['requested_certificate_types'])),
        'failure_targets':sorted(set(value['failure_targets']))}


def classify(output,complete):
    result=empty(complete=complete)
    if type(output) not in (bytes,bytearray) or len(output)>16*1024**2:return result
    for line in bytes(output).splitlines():
        if len(line)>4096:continue
        line=line.strip()
        recognized=False
        for name,patterns in PATTERNS.items():
            if any(re.search(p,line) for p in patterns):
                recognized=True
                if name not in result['categories']:result['categories'].append(name)
        if recognized:
            certificate=re.search(rb'No signing certificate ["\x27]([^"\x27]{1,1024})["\x27] found',line)
            if certificate:
                kind=CERTIFICATE_NAMES.get(certificate[1],'OTHER')
                if kind not in result['requested_certificate_types']:result['requested_certificate_types'].append(kind)
            if b'No development certificates available to code sign' in line:
                if 'DEVELOPMENT_UNSPECIFIED' not in result['requested_certificate_types']:result['requested_certificate_types'].append('DEVELOPMENT_UNSPECIFIED')
            target=re.search(rb'\(in target ["\x27]([^"\x27]{1,128})["\x27] from project ["\x27][^"\x27]{1,128}["\x27]\)',line)
            if target:
                kind={b'Runner':'RUNNER',b'RunnerTests':'RUNNER_TESTS'}.get(target[1],'OTHER')
                if kind not in result['failure_targets']:result['failure_targets'].append(kind)
        for name,pattern in MILESTONES.items():
            if re.search(pattern,line):result['milestones'][name]=True
    if result['categories']:result['status']='RECOGNIZED'
    return project(result)


def reason(value):
    value=project(value)
    if value['status']=='CLASSIFIER_FAILED':return 'build_ipa_classifier_failed'
    # Specific findings precede generic archive/export failure markers.
    for name in PATTERNS:
        if name in value['categories']:return 'build_ipa_'+name.lower()
    return 'build_ipa_unclassified'
