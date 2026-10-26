"""Bounded logical-byte receipts and successful-run-only native tool retirement.

No general cleanup API: five literal entries of the new private native run only.
Not a hostile same-UID/privileged-mount transaction or an allocation quota.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

from verify import GateError, require, pairs, inventory, framework_slices
from diagnostics import safe_error
from build_guards import tree_size

LIMIT = 8 * 1024 ** 3
MIN_FREE = 4 * 1024 ** 3
TARGETS = ('go-darwin-arm64.tar.gz', 'toolchain', 'gocache', 'compiler-tmp', 'bin')
RETAIN = ('Archivebridge.xcframework', 'result.json', 'commands.json',
          'licenses', 'licenses.json', 'logs')
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

RETIREMENT_GATES = frozenset({
    'native_retirement_boundary', 'native_retirement_type', 'native_retirement_hardlink',
    'native_retirement_directory_access', 'native_retirement_bound', 'native_retirement_mount',
    'native_retirement_drift', 'native_retirement_receipt', 'native_retirement_native_not_quiescent',
    'native_retirement_timeout', 'native_retirement_artifact', 'native_retirement_retained_drift',
    'cancelled',
})


def retirement_error(error):
    row = safe_error(error)
    if type(error) is GateError and str(error) in RETIREMENT_GATES:
        row['gate'] = str(error)
    return row


def budget_snapshot(work, app, flutter, flutter_start, measure=tree_size):
    # Subtotals are disjoint roots; never add a nested native subtotal again.
    components = {
        'work': measure(work),
        'app_build': measure(app / 'build'),
        'app_dart_tool': measure(app / '.dart_tool'),
        'app_ios_ephemeral': measure(app / 'ios/Flutter/ephemeral'),
        'flutter_growth': max(0, measure(flutter) - flutter_start),
    }
    require(all(type(n) is int and n >= 0 for n in components.values()), 'resource_measurement')
    return {'components': components, 'total_logical_bytes': sum(components.values()),
            'limit_bytes': LIMIT, 'free_disk_bytes': shutil.disk_usage(work).free,
            'minimum_free_bytes': MIN_FREE, 'hard_quota': False}


def identity(info):
    return info.st_dev, info.st_ino


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _check_info(info, device, directory=None):
    require(info.st_dev == device and info.st_uid == os.geteuid(), 'native_retirement_boundary')
    require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'native_retirement_type')
    if directory is not None:
        require(stat.S_ISDIR(info.st_mode) is directory, 'native_retirement_type')
    if stat.S_ISREG(info.st_mode):
        require(info.st_nlink == 1, 'native_retirement_hardlink')
    else:
        # No chmod fallback, including for read-only compiler/module directories.
        require(info.st_mode & 0o300 == 0o300, 'native_retirement_directory_access')


def _scan(parent_fd, name, path, device, tick, hash_files=False):
    records = {}
    total = 0
    def visit(fd, child_name, child_path, relative, depth):
        nonlocal total
        tick()
        require(depth <= 64 and len(records) < 200000, 'native_retirement_bound')
        info = os.stat(child_name, dir_fd=fd, follow_symlinks=False)
        _check_info(info, device)
        total += info.st_size
        require(total <= LIMIT, 'native_retirement_bound')
        row = {'stat': signature(info)}
        records[relative] = row
        if stat.S_ISDIR(info.st_mode):
            require(not os.path.ismount(child_path), 'native_retirement_mount')
            opened = os.open(child_name, DIR_FLAGS, dir_fd=fd)
            try:
                require(signature(os.fstat(opened)) == signature(info), 'native_retirement_drift')
                with os.scandir(opened) as entries:
                    names = sorted(entry.name for entry in entries)
                for part in names:
                    visit(opened, part, child_path / part, relative + '/' + part, depth + 1)
                require(signature(os.fstat(opened)) == signature(info), 'native_retirement_drift')
            finally:
                os.close(opened)
        elif hash_files:
            opened = os.open(child_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                require(signature(os.fstat(opened)) == signature(info), 'native_retirement_drift')
                digest = hashlib.sha256()
                read = 0
                while block := os.read(opened, 1024 * 1024):
                    tick()
                    read += len(block)
                    require(read <= info.st_size, 'native_retirement_drift')
                    digest.update(block)
                require(read == info.st_size and signature(os.fstat(opened)) == signature(info),
                        'native_retirement_drift')
                row['sha256'] = digest.hexdigest()
            finally:
                os.close(opened)
    visit(parent_fd, name, path, name, 0)
    return {'records': records, 'logical_bytes': total}


def _remove(parent_fd, name, path, snapshot, device, tick):
    records = snapshot['records']
    children = {}
    for key in records:
        if '/' in key:
            parent, leaf = key.rsplit('/', 1)
            children.setdefault(parent, []).append(leaf)
    def remove(fd, child_name, child_path, relative):
        tick()
        info = os.stat(child_name, dir_fd=fd, follow_symlinks=False)
        _check_info(info, device)
        require(signature(info) == records[relative]['stat'], 'native_retirement_drift')
        if stat.S_ISDIR(info.st_mode):
            require(not os.path.ismount(child_path), 'native_retirement_mount')
            opened = os.open(child_name, DIR_FLAGS, dir_fd=fd)
            try:
                require(signature(os.fstat(opened)) == signature(info), 'native_retirement_drift')
                with os.scandir(opened) as entries:
                    names = sorted(entry.name for entry in entries)
                expected = sorted(children.get(relative, []))
                require(names == expected, 'native_retirement_drift')
                for part in names:
                    remove(opened, part, child_path / part, relative + '/' + part)
                # Child removal legitimately changes directory size/timestamps/link count.
                current = os.stat(child_name, dir_fd=fd, follow_symlinks=False)
                _check_info(current, device, directory=True)
                require(identity(current) == identity(info) == identity(os.fstat(opened)),
                        'native_retirement_drift')
                os.rmdir(child_name, dir_fd=fd)
            finally:
                os.close(opened)
        else:
            os.unlink(child_name, dir_fd=fd)
    remove(parent_fd, name, path, name)


def _read_json_at(fd, name):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(opened)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 4 * 1024 ** 2, 'native_retirement_receipt')
        data = bytearray()
        while block := os.read(opened, 65536):
            data.extend(block)
            require(len(data) <= 4 * 1024 ** 2, 'native_retirement_receipt')
        require(signature(os.fstat(opened)) == signature(info), 'native_retirement_drift')
        return json.loads(data, object_pairs_hook=pairs)
    finally:
        os.close(opened)


def retire_native_tools(work, work_identity, command, check=lambda: None):
    """Only the caller's just-successful, quiescent native run may retire tools.

    An exclusive marker prevents replay/reuse, including after partial failure.
    Every target is preflighted before the first unlink. No chmod, external tool,
    broad rmtree, existing server cache, retry, or failed-native cleanup.
    """
    work = Path(work)
    require(work.name == '.ci-work' and work.absolute() == work.resolve(strict=True),
            'native_retirement_boundary')
    require(type(command) is dict and command.get('label') == 'native' and
            command.get('status') == 'PASS' and command.get('exit_code') == 0 and
            command.get('primary') is None and command.get('cleanup_errors') == [],
            'native_retirement_native_not_quiescent')
    deadline = time.monotonic() + 120
    def tick():
        check()
        require(time.monotonic() <= deadline, 'native_retirement_timeout')
    work_fd = os.open(work, DIR_FLAGS)
    native_fd = receipt_fd = None
    receipt = {'status': 'FAILED', 'retired': [], 'policy': 'fixed_five_after_native_pass',
               'retained_evidence_verified': False}
    def write_receipt():
        data = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
        require(len(data) <= 16384, 'native_retirement_receipt')
        current = os.stat('native-retirement.json', dir_fd=work_fd, follow_symlinks=False)
        require(identity(current) == identity(os.fstat(receipt_fd)) and
                stat.S_ISREG(current.st_mode) and current.st_nlink == 1,
                'native_retirement_drift')
        os.lseek(receipt_fd, 0, os.SEEK_SET)
        os.ftruncate(receipt_fd, 0)
        remaining = memoryview(data)
        while remaining:
            written = os.write(receipt_fd, remaining)
            require(written > 0, 'native_retirement_receipt')
            remaining = remaining[written:]
        os.fsync(receipt_fd)
    try:
        work_info = os.fstat(work_fd)
        _check_info(work_info, work_info.st_dev, directory=True)
        require(identity(work_info) == tuple(work_identity) and
                stat.S_IMODE(work_info.st_mode) == 0o700, 'native_retirement_boundary')
        native_fd = os.open('native', DIR_FLAGS, dir_fd=work_fd)
        native_info = os.fstat(native_fd)
        _check_info(native_info, work_info.st_dev, directory=True)
        require(stat.S_IMODE(native_info.st_mode) == 0o700 and
                not os.path.ismount(work / 'native'), 'native_retirement_boundary')
        device = work_info.st_dev
        native_path = work / 'native'
        retained = {name: _scan(native_fd, name, native_path / name, device, tick, True)
                    for name in RETAIN}
        result = _read_json_at(native_fd, 'result.json')
        require(result.get('status') == 'PASS_UNSIGNED_NATIVE_BUILD_ONLY' and
                result.get('native_runtime_test') is False and result.get('final_budget_audit') == 'PASS' and
                result.get('final_audit_errors') == [] and result.get('resource_final_audit_failed') is False,
                'native_retirement_receipt')
        require(result.get('commands_manifest_sha256') == retained['commands.json']['records']['commands.json']['sha256'] and
                result.get('licenses_manifest_sha256') == retained['licenses.json']['records']['licenses.json']['sha256'],
                'native_retirement_receipt')
        require(result.get('artifact_files') == inventory(native_path / 'Archivebridge.xcframework'),
                'native_retirement_artifact')
        framework_slices(native_path / 'Archivebridge.xcframework')
        targets = {name: _scan(native_fd, name, native_path / name, device, tick) for name in TARGETS}
        for name in TARGETS:
            root_stat = targets[name]['records'][name]['stat']
            require(stat.S_ISREG(root_stat[2]) if name.endswith('.tar.gz') else stat.S_ISDIR(root_stat[2]),
                    'native_retirement_type')
        require(identity(os.stat('native', dir_fd=work_fd, follow_symlinks=False)) == identity(native_info),
                'native_retirement_drift')
        receipt.update(target_logical_bytes={name: targets[name]['logical_bytes'] for name in TARGETS},
                       retained_evidence_sha256=_hash_json(retained))
        # Refuse repeat invocation before deleting anything.
        receipt_fd = os.open('native-retirement.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=work_fd)
        write_receipt()
        for name in TARGETS:
            tick()
            require(identity(os.stat('native', dir_fd=work_fd, follow_symlinks=False)) == identity(native_info) and
                    identity(os.stat(work, follow_symlinks=False)) == identity(work_info),
                    'native_retirement_drift')
            _remove(native_fd, name, native_path / name, targets[name], device, tick)
            receipt['retired'].append(name)
            write_receipt()
        after = {name: _scan(native_fd, name, native_path / name, device, tick, True) for name in RETAIN}
        require(after == retained, 'native_retirement_retained_drift')
        receipt.update(status='PASS', retained_evidence_verified=True,
                       retired_logical_bytes=sum(x['logical_bytes'] for x in targets.values()))
        write_receipt()
        return receipt
    except BaseException as error:
        if receipt_fd is not None:
            receipt.update(status='FAILED', error=retirement_error(error))
            try:
                write_receipt()
            except BaseException:
                pass  # Preserve the primary failure; never turn partial disposal into success.
        raise
    finally:
        for fd in (receipt_fd, native_fd, work_fd):
            if fd is not None:
                os.close(fd)


# Diagnostic-only role labels: never emit actual paths, filenames or file contents.
_DIAGNOSTIC_PREFIXES = (
    ('home/Library/Developer/Xcode/DerivedData/CompilationCache.noindex', 'home_compilation_cache'),
    ('home/Library/Developer/Xcode/DerivedData/ModuleCache.noindex', 'home_module_cache'),
    ('derived-iphoneos/CompilationCache.noindex', 'device_compilation_cache'),
    ('derived-iphoneos/ModuleCache.noindex', 'device_module_cache'),
    ('derived-iphonesimulator/CompilationCache.noindex', 'simulator_compilation_cache'),
    ('derived-iphonesimulator/ModuleCache.noindex', 'simulator_module_cache'),
    ('derived-iphoneos', 'device_derived'),
    ('derived-iphonesimulator', 'simulator_derived'),
    ('native', 'native'),
    ('home', 'home_other'),
    ('pub-cache', 'pub_cache'),
    ('tmp', 'temporary'),
    ('logs', 'logs'),
)


def _diagnostic_role(relative):
    for prefix, label in _DIAGNOSTIC_PREFIXES:
        if relative == prefix or relative.startswith(prefix + '/'):
            return label
    return 'other_work'


class _DiagnosticBound(Exception):
    pass


def large_file_summary(work, maximum_rows=8, maximum_entries=100000, seconds=1.0):
    """Separate best-effort metadata snapshot; never changes logical accounting.

    Only bounded enum/numeric metadata leaves this function. It is not atomic,
    cannot identify an exact filename, and may be incomplete while tools run.
    """
    import heapq
    rows = []
    visited = regular = churn = 0
    deadline = time.monotonic() + seconds
    require(1 <= maximum_rows <= 8 and 1 <= maximum_entries <= 100000 and 0 < seconds <= 1,
            'resource_diagnostic_bound')
    def tick():
        if time.monotonic() >= deadline:
            raise _DiagnosticBound('deadline')
        if visited >= maximum_entries:
            raise _DiagnosticBound('entry_limit')
    def walk(fd, parent, depth=0):
        nonlocal visited, regular, churn
        if depth > 64:
            raise _DiagnosticBound('depth_limit')
        with os.scandir(fd) as entries:
            for entry in entries:
                tick()
                visited += 1
                relative = parent + '/' + entry.name if parent else entry.name
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                        try:
                            if identity(os.fstat(child)) != identity(info):
                                churn += 1
                                continue
                            walk(child, relative, depth + 1)
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        regular += 1
                        blocks = getattr(info, 'st_blocks', None)
                        allocated = blocks * 512 if type(blocks) is int and blocks >= 0 else None
                        suffix = next((label for suffix, label in
                                       (('.index', 'index_suffix'), ('.data', 'data_suffix'), ('.db', 'database_suffix'))
                                       if entry.name.endswith(suffix)), 'other')
                        row = {'role': _diagnostic_role(relative), 'name_kind': suffix,
                               'logical_bytes': info.st_size, 'allocated_bytes': allocated,
                               'hard_links': info.st_nlink,
                               'allocation_below_logical': None if allocated is None else allocated < info.st_size}
                        item = (info.st_size, regular, row)
                        if len(rows) < maximum_rows:
                            heapq.heappush(rows, item)
                        else:
                            heapq.heappushpop(rows, item)
                    # Links are not followed or opened. No file contents are read.
                except FileNotFoundError:
                    churn += 1
    result = {'availability': 'present', 'complete': True, 'snapshot': 'separate_non_atomic',
              'maximum_rows': maximum_rows, 'rows': []}
    fd = None
    try:
        fd = os.open(work, DIR_FLAGS)
        walk(fd, '')
    except _DiagnosticBound as error:
        result.update(availability='incomplete', complete=False, reason=str(error))
    except BaseException as error:
        result.update(availability='incomplete', complete=False, reason='io_or_scan_failure',
                      error=safe_error(error))
    finally:
        if fd is not None:
            os.close(fd)
    if churn:
        result.update(availability='incomplete', complete=False)
    result.update(visited_entries=visited, scanned_regular_files=regular, churn_events=churn,
                  rows=[row for _, _, row in sorted(rows, reverse=True)])
    return result
