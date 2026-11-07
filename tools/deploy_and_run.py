#!/usr/bin/env python3
"""One-shot deploy + run of cxl_dump.py on the remote CXL host.

Deploys src/cxl_dump.py to /root/cxl/ on the target, then runs it against
the given BDF.  Kept separate from tools/remote.py so the transfer step is
repeatable and idempotent.
"""
import os
import sys

import paramiko

HOST = os.environ.get("CXL_HOST", "localhost")
USER = os.environ.get("CXL_USER", "root")
# No default: pass the password through CXL_PASS so it never lands in the repo.
PASS = os.environ.get("CXL_PASS")
if PASS is None:
    sys.exit("error: set CXL_PASS (and optionally CXL_HOST/CXL_USER/CXL_BDF)")
BDF = os.environ.get("CXL_BDF", "0000:a8:00.0")
REMOTE_DIR = "/root/cxl"

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_SRC = os.path.join(HERE, "..", "src", "cxl_dump.py")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PASS, timeout=15, auth_timeout=15,
              banner_timeout=15, look_for_keys=False, allow_agent=False)
    return c


def main():
    cli = connect()
    try:
        sftp = cli.open_sftp()
        cli.exec_command("mkdir -p %s" % REMOTE_DIR)[1].channel.recv_exit_status()
        sftp.put(LOCAL_SRC, REMOTE_DIR + "/cxl_dump.py")
        sftp.chmod(REMOTE_DIR + "/cxl_dump.py", 0o755)
        sftp.close()

        cmd = ("cd %s && python3 cxl_dump.py -d %s 2>&1"
               % (REMOTE_DIR, BDF))
        _i, out, err = cli.exec_command(cmd, timeout=180)
        sys.stdout.write(out.read().decode("utf-8", "replace"))
        e = err.read().decode("utf-8", "replace")
        if e:
            sys.stderr.write(e)
        return out.channel.recv_exit_status()
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
