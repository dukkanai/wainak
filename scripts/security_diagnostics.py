"""Finite Apple security import diagnostics; no output fragments cross this API.

Messages/statuses: apple-oss-distributions/Security, base/SecBase.h.
Prefixes: SecurityTool/macOS/keychain_import.c. This is classification of a
reported error, not proof that a password is wrong or an algorithm unsupported.
"""
PROFILE = 'apple_security_import'
ERRORS = {
    'PKCS12_VERIFY_FAILURE': (-25264, b'MAC verification failed during PKCS12 import (wrong password?)'),
    'UNKNOWN_FORMAT': (-25257, b'Unknown format in import.'),
    'PASSPHRASE_REQUIRED': (-25260, b'Passphrase is required for import/export.'),
    'AUTH_FAILED': (-25293, b'The user name or passphrase you entered is not correct.'),
    'NO_SUCH_KEYCHAIN': (-25294, b'The specified keychain could not be found.'),
    'NO_DEFAULT_KEYCHAIN': (-25307, b'A default keychain could not be found.'),
    'INTERACTION_NOT_ALLOWED': (-25308, b'User interaction is not allowed.'),
    'DUPLICATE_ITEM': (-25299, b'The specified item already exists in the keychain.'),
    'DECODE': (-26275, b'Unable to decode the provided data.'),
}
PREFIXES = (b'security: SecKeychainItemImport: ', b'security: SecPKCS12Import: ',
            b'security: SecKeychainOpen: ')
CODES = frozenset(ERRORS) | {'UNCLASSIFIED', 'CLASSIFIER_FAILED', 'NOT_APPLICABLE'}
REASONS = frozenset('security_' + code.lower() for code in CODES - {'NOT_APPLICABLE'})


def project(value):
    return value if type(value) is str and value in CODES else 'CLASSIFIER_FAILED'


def classify(output):
    # Match a complete known line only. No substring, arbitrary numeric status,
    # path extraction, length heuristic, digest or exception text is returned.
    if type(output) not in (bytes, bytearray) or not 0 < len(output) <= 4096:
        return 'UNCLASSIFIED'
    lines=bytes(output).splitlines()
    if len(lines)!=1:return 'UNCLASSIFIED'
    for prefix in PREFIXES:
        for code,(status,message) in ERRORS.items():
            if lines[0] in (prefix+message,prefix+b'OSStatus '+str(status).encode('ascii')):
                return code
    return 'UNCLASSIFIED'
