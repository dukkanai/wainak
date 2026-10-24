#!/usr/bin/env python3
"""Create/test/remove ONLY this harness's new isolated synthetic PostgreSQL.

No ports, no existing database, no supplied DSN, no persistent secret or service.
Requires Docker, the already-present pinned image, and optional psycopg dependency.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"backend"))
IMAGE="postgres:17-alpine@sha256:eee6c6e1b0894fa4fe0075eb054af9fd1cf39a35321c2d4110626cfe506411fb"
LABEL="com.wainak.disposable-postgres-test"


def command(args,check=True):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=90)
    if check and result.returncode:
        # Do not echo arbitrary Docker output or connection configuration.
        raise RuntimeError(f"Disposable harness command failed ({args[0]} {args[1]}, exit {result.returncode}).")
    return result


def metadata(kind,name):
    result=command(["docker",kind,"inspect",name],check=False)
    if result.returncode:
        missing=("no such object","no such container","no such volume")
        if any(message in result.stderr.lower() for message in missing):
            return None
        raise RuntimeError("Cannot establish Docker resource state; cleanup is not verified")
    return json.loads(result.stdout)[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-disposable-postgres",action="store_true")
    args=parser.parse_args()
    if not args.run_disposable_postgres:
        parser.error("Explicit --run-disposable-postgres is required; no existing DB is accepted")
    import psycopg
    from wainak.migrations import apply_initial_migration
    os.umask(0o077)
    command(["docker","image","inspect",IMAGE])  # Never pulls implicitly.
    tag=secrets.token_hex(6)
    name="wainak-pgtest-"+tag
    volume=name+"-data"
    database="wainak_test_"+tag
    if metadata("container",name) or metadata("volume",volume):
        raise RuntimeError("Generated test resource name already exists; refusing reuse")
    password=secrets.token_urlsafe(48)
    success=False
    with tempfile.TemporaryDirectory(prefix="wainak-postgres-test-") as directory:
        temporary=Path(directory)
        socket=temporary/"socket"
        socket.mkdir(mode=0o755)
        secret=temporary/"test_password"
        secret.write_text(password+"\n")
        secret.chmod(0o600)
        def connect(db=database):
            return psycopg.connect(host=str(socket),dbname=db,user="wainak_test_admin",password=password,connect_timeout=3)
        def wait_ready():
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                try:
                    with connect() as connection:
                        connection.execute("SELECT 1")
                    return
                except psycopg.OperationalError:
                    state=metadata("container",name)
                    if not state or not state["State"]["Running"]:
                        raise RuntimeError("New disposable database container stopped during initialization")
                    time.sleep(0.5)
            raise RuntimeError("New disposable database did not become ready within its initialization window")
        def restart():
            command(["docker","restart","--time","15",name])
            wait_ready()
        try:
            command(["docker","volume","create","--label",f"{LABEL}={tag}",volume])
            command(["docker","run","--detach","--pull","never","--name",name,
                "--label",f"{LABEL}={tag}","--network","none","--memory","192m","--cpus","0.5","--pids-limit","100",
                "--shm-size","32m","--security-opt","no-new-privileges:true",
                "--mount",f"type=volume,source={volume},target=/var/lib/postgresql/data",
                "--mount",f"type=bind,source={socket},target=/var/run/postgresql",
                "--mount",f"type=bind,source={secret},target=/run/secrets/test_password,readonly",
                "--env",f"POSTGRES_DB={database}","--env","POSTGRES_USER=wainak_test_admin",
                "--env","POSTGRES_PASSWORD_FILE=/run/secrets/test_password",
                "--env","POSTGRES_INITDB_ARGS=--auth-local=scram-sha-256 --auth-host=scram-sha-256",
                IMAGE,"postgres","-c","listen_addresses=","-c","shared_buffers=32MB","-c","max_connections=20",
                "-c","unix_socket_permissions=0777","-c","log_statement=none","-c","log_min_error_statement=panic",
                "-c","log_parameter_max_length_on_error=0"])
            container=metadata("container",name)
            if container["HostConfig"]["NetworkMode"]!="none" or container["HostConfig"].get("PortBindings"):
                raise RuntimeError("Disposable isolation verification failed")
            wait_ready()
            apply_initial_migration(connect,allow_new_disposable_database=True)
            spec=importlib.util.spec_from_file_location("wainak_postgres_integration",Path(__file__).with_name("test_postgres.py"))
            module=importlib.util.module_from_spec(spec)
            sys.modules[spec.name]=module
            spec.loader.exec_module(module)
            module.CONNECT=connect
            module.CONNECT_WRONG_DATABASE=lambda:connect("postgres")
            module.RESTART_CONTAINER=restart
            suite=unittest.defaultTestLoader.loadTestsFromModule(module)
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            success=result.wasSuccessful()
            with connect() as connection:
                version=connection.execute("SHOW server_version").fetchone()[0]
            print(json.dumps({"postgres_version":version,"driver_version":psycopg.__version__,"test_count":result.testsRun,
                "tests_passed":success,"published_ports":False,"network_mode":"none","synthetic_only":True},sort_keys=True))
        finally:
            container=metadata("container",name)
            if container:
                if container["Config"].get("Labels",{}).get(LABEL)!=tag:
                    raise RuntimeError("Refusing cleanup of a container not owned by this test")
                if container["State"]["Running"]:
                    # Only this newly-created, privately nested socket directory.
                    # Allow the creating user to remove it after PostgreSQL stops.
                    command(["docker","exec","--user","0",name,"chmod","0777","/var/run/postgresql"])
                command(["docker","rm","--force",name])
            info=metadata("volume",volume)
            if info:
                if info.get("Labels",{}).get(LABEL)!=tag:
                    raise RuntimeError("Refusing cleanup of a volume not owned by this test")
                command(["docker","volume","rm",volume])
            if metadata("container",name) or metadata("volume",volume):
                raise RuntimeError("Disposable resources were not fully removed")
            print("Verified removal of this test's container and volume; temporary secret/socket directory is removed on exit.")
    if temporary.exists():
        raise RuntimeError("Temporary test directory was not removed")
    print("Verified removal of temporary test directory; no persistent credentials created.")
    return 0 if success else 1


if __name__=="__main__":
    raise SystemExit(main())
