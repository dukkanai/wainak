"""Strict settings JSON and finite public projections. Never log Xcode's dump."""
import json
import math
from ci.testflight import policy as p

REASONS=frozenset({'signed_settings_json','signed_settings_duplicate_key','signed_settings_nonfinite',
    'signed_settings_shape','signed_settings_defines_type','signed_settings_json_bound','signed_settings'})
PUBLIC={
    'PRODUCT_BUNDLE_IDENTIFIER':frozenset({p.BUNDLE}),
    'DEVELOPMENT_TEAM':frozenset({p.TEAM}),
    'CONFIGURATION':frozenset({'Release','Debug','Profile'}),
    'PLATFORM_NAME':frozenset({'iphoneos','iphonesimulator','macosx'}),
    'CODE_SIGNING_ALLOWED':frozenset({'YES','NO'}),
    'CODE_SIGNING_REQUIRED':frozenset({'YES','NO'}),
    'CODE_SIGN_STYLE':frozenset({'Manual','Automatic'}),
    'CODE_SIGN_IDENTITY':frozenset({'Apple Distribution','Apple Development',''}),
}


def project(settings,pins):
    result={}
    for key,allowed in PUBLIC.items():
        value=settings.get(key)
        result[key]=('MISSING' if key not in settings else 'WRONG_TYPE' if type(value) is not str
                     else value if value in allowed else 'OTHER')
    value=settings.get('PROVISIONING_PROFILE_SPECIFIER')
    result['PROVISIONING_PROFILE_SPECIFIER']=('MISSING' if value is None else 'WRONG_TYPE' if type(value) is not str
        else 'REVIEWED_UUID' if value==pins['profile_uuid'] else 'REVIEWED_NAME' if value==pins['profile_name']
        else 'EMPTY' if not value else 'OTHER')
    return result


def validate(text,pins):
    stage='JSON';reason='NONE';outcome='FAILED';projection={}
    def pairs(items):
        result={}
        for key,value in items:
            p.require(key not in result,'signed_settings_duplicate_key');result[key]=value
        return result
    def constant(_):raise p.PolicyError('signed_settings_nonfinite')
    def integer(value):
        p.require(len(value)<=64,'signed_settings_json_bound');return int(value)
    def floating(value):
        p.require(len(value)<=128,'signed_settings_json_bound')
        result=float(value);p.require(math.isfinite(result),'signed_settings_nonfinite');return result
    try:
        p.require(type(text) is str and len(text)<=16*1024**2,'signed_settings_json_bound')
        try:items=json.loads(text,object_pairs_hook=pairs,parse_constant=constant,parse_int=integer,parse_float=floating)
        except p.PolicyError:raise
        except json.JSONDecodeError:raise p.PolicyError('signed_settings_json') from None
        except (RecursionError,ValueError):raise p.PolicyError('signed_settings_json_bound') from None
        stage='SHAPE'
        p.require(type(items) is list and 0<len(items)<=128,'signed_settings_shape')
        p.require(all(type(x) is dict and type(x.get('target')) is str for x in items),'signed_settings_shape')
        runners=[x for x in items if x['target']=='Runner']
        p.require(len(runners)==1,'runner_settings')
        b=runners[0].get('buildSettings');p.require(type(b) is dict,'signed_settings_shape')
        projection=project(b,pins)
        p.require(type(b.get('DART_DEFINES','')) is str,'signed_settings_defines_type')
        stage='POLICY'
        p.validate_settings(items)  # All existing identity, signing and UI checks.
        stage='PROFILE'
        p.require(b.get('PROVISIONING_PROFILE_SPECIFIER')==pins['profile_uuid'],'signed_settings')
        outcome='PASS';stage='COMPLETE'
    except p.PolicyError as error:
        # Policy functions use fixed reason strings only; values are never included.
        allowed=REASONS|{'runner_settings','missing_profile','native_archive_enabled','missing_dart_defines',
            'invalid_dart_define','duplicate_or_invalid_define','wrong_ui_mode','settings_type'}|{
            'settings_'+key for key in PUBLIC}
        reason=error.args[0] if error.args and type(error.args[0]) is str and error.args[0] in allowed else 'OTHER'
        raise
    finally:
        print(json.dumps({'event':'GITHUB_SIGNING_SETTINGS','outcome':outcome,'stage':stage,
            'safe_reason':reason,'public_settings':projection}),flush=True)
