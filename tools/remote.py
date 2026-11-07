#!/usr/bin/env python3
"""Minimal SSH helper for driving the CXL box during development.

Usage:
    python tools/remote.py <cmd...>       # run a shell command
    python tools/remote.py -f a b         # upload local->remote then run
"""
import sys
import os
import paramiko

HOST = os.environ.get("CXL_HOST", "localhost")
USER = os.environ.get("CXL_USER", "root")
# No default: pass the password through CXL_PASS so it never lands in the repo.
PASS = os.environ.get("CXL_PASS")
if PASS is None:
    sys.exit("error: set CXL_PASS (and optionally CXL_HOST/CXL_USER)")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PASS,
              timeout=15, banner_timeout=15, auth_timeout=15,
              look_for_keys=False, allow_agent=False)
    return c


def run(cmd, timeout=120):
    c = connect()
    try:
        _in, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
    finally:
        c.close()
    return rc, o, e


def put(local, remote):
    c = connect()
    try:
        s = c.open_sftp()
        s.put(local, remote)
        s.chmod(remote, 0o755)
        s.close()
    finally:
        c.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "-f":
        put(a[1], a[2])
        rc, o, e = run(a[3] if len(a) > 3 else "echo uploaded")
    else:
        rc, o, e = run(" ".join(a) if a else "echo hi")
    sys.stdout.write(o)
    if e:
        sys.stderr.write("--- stderr ---\n" + e)
    print("\n[rc=%d]" % rc)
    sys.exit(0 if rc == 0 else 1)
