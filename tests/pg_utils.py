"""Ensure the local PostgreSQL test cluster is available.

Creates the cluster (initdb) if missing and starts it if stopped.
Uses a cleaned environment because postgres backends fail to spawn
when inheriting the Git-bash PATH (0xC0000142 DLL init failures).
"""

import os
import subprocess
import sys
import time

PGROOT = r"C:\Program Files\PostgreSQL\18"
PGDATA = r"C:\Users\Michael\AppData\Local\Temp\opencode\pgtest_data"
PORT = 5439
DB = "reservations"
USER = "postgres"
HOST = "127.0.0.1"


def _clean_env():
    systemroot = os.environ.get("SystemRoot", r"C:\Windows")
    path_parts = [
        os.path.join(systemroot, "System32"),
        os.path.join(systemroot, "System32", "Wbem"),
        os.path.join(systemroot, "System32", "WindowsPowerShell", "v1.0"),
        systemroot,
        os.path.join(PGROOT, "bin"),
    ]
    env = {
        "SystemRoot": systemroot,
        "COMSPEC": os.environ.get("COMSPEC", os.path.join(systemroot, "System32", "cmd.exe")),
        "WINDIR": systemroot,
        "TEMP": os.environ.get("TEMP", os.path.join(systemroot, "Temp")),
        "TMP": os.environ.get("TMP", os.path.join(systemroot, "Temp")),
        "PATH": ";".join(path_parts),
    }
    # Unset common problematic vars
    for var in [
        "MSYSTEM", "MSYS", "MSYS2_PATH_TYPE", "TERM", "HOME", "LANG", "LC_ALL",
        "PKG_CONFIG_PATH", "ACLOCAL_PATH", "MANPATH", "INFOPATH",
        "GIT_EXEC_PATH", "GIT_SSH", "SSH_ASKPASS", "DISPLAY",
    ]:
        env[var] = ""
    return env


def _run(args, check=False, timeout=None):
    try:
        return subprocess.run(
            args, env=_clean_env(), capture_output=True, text=True, timeout=timeout, check=check
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out: {args}\nstdout={e.stdout}\nstderr={e.stderr}") from e

def _connects() -> bool:
    try:
        import psycopg

        with psycopg.connect(
            f"host={HOST} port={PORT} dbname=postgres user={USER}", connect_timeout=3
        ) as conn:
            conn.execute("select 1")
        return True
    except Exception:
        return False


def _cleanup_stale_state(pgdata):
    """Remove stale postmaster files if cluster is not running."""
    for fname in ["postmaster.pid", "postmaster.opts", "postmaster.lock"]:
        fpath = os.path.join(pgdata, fname)
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
        except Exception:
            pass


def ensure_database(dbname: str) -> None:
    """Create the given database (and btree_gist) on the local cluster if missing."""
    import psycopg

    with psycopg.connect(
        f"host={HOST} port={PORT} dbname=postgres user={USER}", autocommit=True
    ) as conn:
        row = conn.execute("select 1 from pg_database where datname = %s", (dbname,)).fetchone()
        if row is None:
            conn.execute(f'create database "{dbname}"')
    with psycopg.connect(
        f"host={HOST} port={PORT} dbname={dbname} user={USER}", autocommit=True
    ) as conn:
        conn.execute("create extension if not exists btree_gist")


def _ensure_db() -> None:
    ensure_database(DB)


def ensure_server() -> None:
    if _connects():
        _ensure_db()
        return

    pgdata = PGDATA
    os.makedirs(os.path.dirname(pgdata), exist_ok=True)

    if not os.path.exists(os.path.join(pgdata, "PG_VERSION")):
        r = _run(
            [
                os.path.join(PGROOT, "bin", "initdb.exe"),
                "-D", pgdata,
                "-U", USER,
                "-A", "trust",
                "-E", "UTF8",
                "--no-locale",
            ]
        )
        if r.returncode != 0:
            raise RuntimeError(f"initdb failed:\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")

    # Configure postgresql.conf
    conf = os.path.join(pgdata, "postgresql.conf")
    try:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        text = ""
    # Ensure our required settings
    settings_to_ensure = []
    if "port =" not in text or "opencode-pgport" not in text:
        settings_to_ensure.append(f"port = {PORT}  # opencode-pgport")
    if "listen_addresses" not in text:
        settings_to_ensure.append("listen_addresses = '127.0.0.1'")
    # Reduce background workers that might have env issues
    if "autovacuum" not in text or "autovacuum = off" not in text:
        # Be conservative - but to avoid crashes from autovac workers, better to control
        settings_to_ensure.append("autovacuum = off")
    if "bgwriter_lru_maxpages" not in text:
        settings_to_ensure.append("bgwriter_lru_maxpages = 0")
    if settings_to_ensure:
        with open(conf, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(settings_to_ensure) + "\n")

    pg_ctl = os.path.join(PGROOT, "bin", "pg_ctl.exe")
    r = _run([pg_ctl, "status", "-D", pgdata])
    if r.returncode != 0:
        _cleanup_stale_state(pgdata)
        log = os.path.join(pgdata, "opencode-server.log")
        r = _run([pg_ctl, "start", "-D", pgdata, "-w", "-l", log], timeout=180)
        if r.returncode != 0:
            raise RuntimeError(
                f"pg_ctl start failed (rc={r.returncode}):\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}\n"
                f"LOG: {log}"
            )

    for _ in range(120):  # wait up to 60 seconds
        if _connects():
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("postgres did not become ready within timeout")
    _ensure_db()
