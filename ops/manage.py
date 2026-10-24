#!/usr/bin/env python3
"""Local Wainak operations. Restore only trusted archives into NEW databases."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
BACKUPS = ROOT / 'backups'
COMPOSE = ['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT / 'compose.yaml')]


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return run(args, stdout=subprocess.PIPE).stdout.decode().strip()


def private_dir(path, create=False):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f'Expected owned private directory (0700): {path}')


def open_regular(path, private=False):
    """Open once; reject links, devices and FIFOs without following/blocking."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError('Expected regular file')
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise RuntimeError('Expected owned private file (0600)')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def operation_lock(create=False):
    private_dir(RUNTIME, create=create)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        flags |= os.O_CREAT
    fd = os.open(RUNTIME / 'operations.lock', flags, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('Unsafe operations lock file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def configuration():
    return json.loads(output(COMPOSE + ['config', '--format', 'json']))


def deployment_exists():
    config = configuration()
    volume = config['volumes']['db_data']['name']
    volumes = output(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
    containers = output(['docker', 'ps', '-aq', '--filter',
                         f'label=com.docker.compose.project={config["name"]}'])
    return volume in volumes or bool(containers)


def validate_secret():
    private_dir(RUNTIME)
    with open_regular(RUNTIME / 'db_password', private=True) as stream:
        if not 32 <= os.fstat(stream.fileno()).st_size <= 4096:
            raise RuntimeError('Existing password file is invalid; refusing to replace it')


def init():
    """Caller MUST hold operation_lock. Never rotate a missing deployed secret."""
    private_dir(RUNTIME)
    password = RUNTIME / 'db_password'
    try:
        password.lstat()
    except FileNotFoundError:
        if deployment_exists():
            raise RuntimeError('Database deployment exists but its secret is missing; recover the original secret or use an explicit rotation procedure')
        fd = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(48) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    validate_secret()
    private_dir(BACKUPS, create=True)


def dbexec(*args):
    return COMPOSE + ['exec', '-T', 'db', *args]


def database_name(name):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
        raise RuntimeError('Invalid database name')
    return name


def sql(statement, database='wainak'):
    database_name(database)
    return output(dbexec('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'wainak_admin',
                         '-d', database, '-Atc', statement))


def verify_auth(database='wainak'):
    """Verify TCP SCRAM auth using the host secret via stdin, never argv."""
    database_name(database)
    validate_secret()
    script = ('IFS= read -r PGPASSWORD; export PGPASSWORD; '
              'exec psql -X --no-password -h 127.0.0.1 -U wainak_admin -d "$1" -Atqc "SELECT 1"')
    with open_regular(RUNTIME / 'db_password', private=True) as stream:
        result = subprocess.run(dbexec('sh', '-eu', '-c', script, 'auth-check', database),
                                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0 or result.stdout.strip() != b'1':
        raise RuntimeError('Database credential authentication failed; secret was not changed')


def digest_stream(stream):
    h = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
    stream.seek(0)
    return h.hexdigest()


def digest(path):
    with open_regular(path) as stream:
        return digest_stream(stream)


def backup(database='wainak'):
    database_name(database)
    private_dir(BACKUPS)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = BACKUPS / f'wainak-{stamp}-{secrets.token_hex(3)}.dump'
    partial = target.with_suffix('.partial')
    start = time.monotonic()
    try:
        with partial.open('xb') as stream:
            run(dbexec('pg_dump', '-U', 'wainak_admin', '-d', database,
                       '--format=custom', '--no-owner', '--no-acl'), stdout=stream)
            stream.flush()
            os.fsync(stream.fileno())
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)
    manifest = {
        'created_at': stamp, 'sha256': digest(target), 'bytes': target.stat().st_size,
        'database': database, 'postgres_version': sql('SHOW server_version;', database),
        'elapsed_seconds': round(time.monotonic() - start, 3),
        'contains_roles': False, 'encrypted': False,
        'scope': 'database only; secrets, app images, external settings and globals excluded',
    }
    with target.with_suffix('.json').open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    print(f'Backup created: {target}')
    print('Local protected file; NOT an off-server or encrypted backup.')
    return target


@contextmanager
def verified_archive(path, *, trusted_source=False, expected_sha256=None):
    """Verify and restore the same private snapshot FD, never reopen the source.

    A checksum and --trusted-source are NOT source authentication. The operator
    must authenticate provenance independently. Copying into a private anonymous
    file also isolates later in-place changes to the source.
    """
    if not trusted_source:
        raise RuntimeError('Restore requires an explicitly trusted source; a checksum is not source authentication')
    private_dir(RUNTIME)
    path = Path(path).absolute()
    with open_regular(path.with_suffix('.json')) as manifest_file:
        raw = manifest_file.read(65537)
    if len(raw) > 65536:
        raise RuntimeError('Backup manifest is too large')
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise RuntimeError('Invalid backup manifest object')
    checksum = manifest.get('sha256')
    size = manifest.get('bytes')
    if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
        raise RuntimeError('Invalid backup checksum')
    if type(size) is not int or size < 0:
        raise RuntimeError('Invalid backup size')
    if expected_sha256 is not None:
        if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256):
            raise RuntimeError('Invalid expected SHA256')
        if expected_sha256.lower() != checksum:
            raise RuntimeError('Expected SHA256 does not match the manifest')
    with open_regular(path) as source, tempfile.TemporaryFile(mode='w+b', dir=RUNTIME) as snapshot:
        copied = 0
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            copied += len(chunk)
            if copied > size:
                raise RuntimeError('Backup integrity check failed')
            snapshot.write(chunk)
        snapshot.flush()
        if copied != size or digest_stream(snapshot) != checksum:
            raise RuntimeError('Backup integrity check failed')
        yield snapshot


def cleanup_drill_container(name, operation_id):
    """Remove only a container whose unique operation label matches this attempt.

    Docker run can create a container and fail before returning success. Resolve
    the exact name even on that path, then remove by inspected ID, never by name.
    Failure to query Docker is reported; it is not interpreted as proof of cleanup.
    """
    identifiers = output(['docker', 'ps', '-a', '--filter', f'name=^/{name}$',
                          '--format', '{{.ID}}']).splitlines()
    for identifier in identifiers:
        owner = output(['docker', 'inspect', '--type', 'container', '--format',
                        '{{index .Config.Labels "app.wainak.restore-operation"}}', identifier])
        if owner == operation_id:
            run(['docker', 'rm', '-f', identifier], stdout=subprocess.DEVNULL)


def restore_drill(path, *, trusted_source=False, expected_sha256=None):
    with verified_archive(path, trusted_source=trusted_source, expected_sha256=expected_sha256) as archive:
        name = 'wainak-restore-drill-' + secrets.token_hex(6)
        operation_id = secrets.token_hex(16)
        image = configuration()['services']['db']['image']
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='restore-secret-', dir=RUNTIME) as secret_dir:
            password = Path(secret_dir) / 'password'
            fd = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_urlsafe(48) + '\n')
            try:
                run(['docker', 'run', '-d', '--name', name, '--network', 'none',
                     '--label', f'app.wainak.restore-operation={operation_id}',
                     '--memory', '512m', '--cpus', '0.5', '--pids-limit', '150',
                     '--security-opt', 'no-new-privileges:true',
                     '--tmpfs', '/var/lib/postgresql/data:rw,size=268435456',
                     '--mount', f'type=bind,src={password},dst=/run/secrets/db_password,readonly',
                     '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/db_password',
                     '-e', 'POSTGRES_USER=wainak_admin', '-e', 'POSTGRES_DB=wainak', image],
                    stdout=subprocess.DEVNULL)
                for _ in range(60):
                    ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'wainak_admin',
                                            '-d', 'wainak'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if ready.returncode == 0:
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError('Restore sandbox did not become ready')
                run(['docker', 'exec', '-i', name, 'pg_restore', '-U', 'wainak_admin',
                     '-d', 'wainak', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl'], stdin=archive)
                count = output(['docker', 'exec', name, 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                                '-U', 'wainak_admin', '-d', 'wainak', '-Atc',
                                "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"])
                print(f'Restore successful in isolated container; user tables: {count}')
                print(f'Elapsed seconds: {time.monotonic() - start:.2f}')
                print('Small local rehearsal only; 256 MiB temporary disk. Not a server migration benchmark.')
            finally:
                cleanup_drill_container(name, operation_id)


def restore_empty(path, database, *, trusted_source=False, expected_sha256=None):
    """Create a NEW reserved database; never alter an existing destination.

    CONNECTION LIMIT 0 blocks ordinary clients during acceptance, but trusted
    cluster superusers can bypass it. No global lock is claimed. The application
    is never switched and no existing database is renamed/disconnected/dropped.
    """
    database_name(database)
    if not database.startswith('wainak_restore_'):
        raise RuntimeError('New destination name must start with wainak_restore_')
    with verified_archive(path, trusted_source=trusted_source, expected_sha256=expected_sha256) as archive:
        exists = sql(f"SELECT 1 FROM pg_database WHERE datname = '{database}';", 'postgres')
        if exists:
            raise RuntimeError('Destination database already exists; refusing to modify it')
        # PostgreSQL CREATE DATABASE rejects racing creation of the same name.
        sql(f'CREATE DATABASE "{database}" WITH TEMPLATE template0 OWNER wainak_admin CONNECTION LIMIT 0;', 'postgres')
        try:
            run(dbexec('pg_restore', '-U', 'wainak_admin', '-d', database,
                       '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl'), stdin=archive)
        except BaseException:
            print(f'Restore failed. New reserved destination retained: {database}. No existing database was selected as the restore destination.', file=sys.stderr)
            raise
    print(f'Restored into NEW reserved destination: {database}')
    print('Connection limit remains 0. Apply grants, validate data and explicitly switch the application before enabling normal connections.')


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'up', 'status', 'backup', 'restore-drill', 'restore-empty'])
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--database', help='Status/backup database; restore-empty requires a NEW wainak_restore_ name')
    parser.add_argument('--trusted-source', action='store_true', help='Acknowledges independently trusted source, not cryptographic attestation')
    parser.add_argument('--expected-sha256', help='Optional independently obtained digest, not itself proof of source')
    args = parser.parse_args(argv)
    if args.command == 'restore-empty' and (not args.archive or not args.database):
        parser.error('restore-empty requires archive, --database NEW_NAME and --trusted-source')
    if args.command in ('restore-empty', 'restore-drill') and args.archive and not args.trusted_source:
        parser.error('An external archive requires --trusted-source; checksum is not proof of source')
    if args.command == 'status':
        # No init, mkdir, chmod, secret creation, or lock-file creation.
        verify_auth(args.database or 'wainak')
        run(COMPOSE + ['ps'])
        print('Database credential authentication: verified')
        return
    with operation_lock(create=args.command in ('init', 'up')):
        if args.command in ('init', 'up'):
            init()
        else:
            validate_secret()
        if args.command == 'init':
            print('Local directories and database secret prepared; no secret displayed.')
        elif args.command == 'up':
            run(COMPOSE + ['config', '--quiet'])
            run(COMPOSE + ['up', '-d', '--wait', '--wait-timeout', '120'])
            verify_auth()
        elif args.command == 'backup':
            verify_auth(args.database or 'wainak')
            backup(args.database or 'wainak')
        elif args.command == 'restore-drill':
            if args.archive:
                restore_drill(args.archive, trusted_source=True, expected_sha256=args.expected_sha256)
            else:
                verify_auth()
                restore_drill(backup(), trusted_source=True)
        elif args.command == 'restore-empty':
            verify_auth('postgres')
            restore_empty(args.archive, args.database, trusted_source=True, expected_sha256=args.expected_sha256)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
