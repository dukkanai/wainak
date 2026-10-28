"""Fixed-label unsigned-check evidence. No paths, identities, or raw tool text."""
import json
import os
import re
import stat
import struct

PREFIX = 'WAINAK_UNSIGNED_DIAGNOSTIC '
CATEGORIES = {'bundle_metadata', 'invalid_arguments', 'signature_present',
              'unexpected_codesign_output', 'codesign_timeout', 'codesign_tool_error',
              'codesign_output_bound'}
SIGNATURE_CLASSES = {'adhoc', 'other_or_unknown_signature', 'not_reported', 'unavailable'}
MACHO_STATES = {'present', 'absent', 'malformed', 'unavailable', 'unsupported'}
KEYS = {'category', 'codesign_returncode', 'unsigned_sentinel', 'signature_class', 'macho_signature'}
MAX_COMMAND_BYTES = 1024 * 1024


def signature_class(output, returncode):
    """Classify presence only; never retain signing identity/identifier values."""
    if not isinstance(output, bytes) or len(output) > 65536:
        return 'unavailable'
    if re.search(rb'(?m)^Signature=adhoc\r?$', output) or re.search(rb'flags=0x[0-9a-fA-F]+\([^\r\n)]*\badhoc\b', output):
        return 'adhoc'
    if returncode == 0 or re.search(rb'(?m)^(?:Signature=|Authority=|CodeDirectory(?:\s|=))', output):
        return 'other_or_unknown_signature'
    return 'not_reported'


def macho_signature(app):
    """Inspect only bounded thin Mach-O load commands of the app's Runner binary."""
    directory = binary = None
    try:
        directory = os.open(app, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        binary = os.open('Runner', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(binary)
        if not stat.S_ISREG(info.st_mode):
            return 'unavailable'
        header = os.pread(binary, 32, 0)
        if len(header) != 32:
            return 'malformed'
        if header[:4] != b'\xcf\xfa\xed\xfe':
            return 'unsupported'
        values = struct.unpack('<8I', header)
        ncmds, sizeofcmds = values[4], values[5]
        if ncmds > 4096 or sizeofcmds > MAX_COMMAND_BYTES or 32 + sizeofcmds > info.st_size:
            return 'malformed'
        commands = os.pread(binary, sizeofcmds, 32)
        if len(commands) != sizeofcmds:
            return 'malformed'
        offset = 0
        for _ in range(ncmds):
            if offset + 8 > len(commands):
                return 'malformed'
            cmd, size = struct.unpack_from('<II', commands, offset)
            # A recognized signature command is positive evidence even if its
            # payload or later commands are malformed. Never erase that evidence.
            if cmd == 0x1d:
                return 'present'
            if size < 8 or size % 4 or offset + size > len(commands):
                return 'malformed'
            offset += size
        if offset != len(commands):
            return 'malformed'
        return 'absent'
    except OSError:
        return 'unavailable'
    finally:
        if binary is not None:
            os.close(binary)
        if directory is not None:
            os.close(directory)


def valid_report(row):
    return (type(row) is dict and set(row) == KEYS
            and row['category'] in CATEGORIES
            and (row['codesign_returncode'] is None or
                 (type(row['codesign_returncode']) is int and -255 <= row['codesign_returncode'] <= 255))
            and type(row['unsigned_sentinel']) is bool
            and row['signature_class'] in SIGNATURE_CLASSES
            and row['macho_signature'] in MACHO_STATES)


def failure_report(category, app=None, returncode=None, output=b''):
    row = {'category': category, 'codesign_returncode': returncode,
           'unsigned_sentinel': b'code object is not signed at all' in output,
           'signature_class': 'unavailable' if returncode is None else signature_class(output, returncode),
           'macho_signature': 'unavailable' if app is None else macho_signature(app)}
    if not valid_report(row):
        raise ValueError('invalid_unsigned_report')
    return row


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def unsigned_summary(output):
    """Project only the exact helper schema; arbitrary child output is never exported."""
    if not isinstance(output, (bytes, bytearray)) or len(output) > 8192:
        return {'availability': 'invalid'}
    if bytes(output).strip() == b'PASS_UNSIGNED_APP':
        return {'availability': 'pass_sentinel'}
    try:
        text = bytes(output).decode('utf-8').strip()
        if not text:
            return {'availability': 'missing'}
        if not text.startswith(PREFIX) or '\n' in text or len(text) > 2048:
            return {'availability': 'invalid'}
        row = json.loads(text[len(PREFIX):], object_pairs_hook=_unique_pairs)
        if not valid_report(row):
            return {'availability': 'invalid'}
        return {'availability': 'present', **row}
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        return {'availability': 'invalid'}
