#!/usr/bin/env python3
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("POSTGRES_EXPORTER_PORT", "9187"))
PGHOST = os.getenv("PGHOST", "127.0.0.1")
PGPORT = os.getenv("PGPORT", "5432")
PGUSER = os.getenv("PGUSER", "grafana_exporter")
PGDATABASE = os.getenv("PGDATABASE", "postgres")


def esc(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def line(name, labels, value):
    label_text = ",".join(f'{key}="{esc(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def psql(query):
    env = os.environ.copy()
    command = [
        "psql",
        "-h",
        PGHOST,
        "-p",
        PGPORT,
        "-U",
        PGUSER,
        "-d",
        PGDATABASE,
        "-At",
        "-F",
        "\t",
        "-c",
        query,
    ]
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=12)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [row.split("\t") for row in result.stdout.splitlines() if row.strip()]


def collect():
    started = time.time()
    output = [
        "# HELP postgres_host_exporter_up PostgreSQL host exporter scrape status.",
        "# TYPE postgres_host_exporter_up gauge",
        "# HELP postgres_host_database_size_bytes PostgreSQL database size.",
        "# TYPE postgres_host_database_size_bytes gauge",
        "# HELP postgres_host_database_numbackends PostgreSQL active backend count by database.",
        "# TYPE postgres_host_database_numbackends gauge",
        "# HELP postgres_host_database_xact_commit_total PostgreSQL committed transactions by database.",
        "# TYPE postgres_host_database_xact_commit_total counter",
        "# HELP postgres_host_database_xact_rollback_total PostgreSQL rolled back transactions by database.",
        "# TYPE postgres_host_database_xact_rollback_total counter",
        "# HELP postgres_host_database_blks_read_total PostgreSQL disk blocks read by database.",
        "# TYPE postgres_host_database_blks_read_total counter",
        "# HELP postgres_host_database_blks_hit_total PostgreSQL buffer cache hits by database.",
        "# TYPE postgres_host_database_blks_hit_total counter",
        "# HELP postgres_host_database_deadlocks_total PostgreSQL deadlocks by database.",
        "# TYPE postgres_host_database_deadlocks_total counter",
        "# HELP postgres_host_connections PostgreSQL connection count by state.",
        "# TYPE postgres_host_connections gauge",
        "# HELP postgres_host_locks PostgreSQL lock count by mode and granted state.",
        "# TYPE postgres_host_locks gauge",
        "# HELP postgres_host_setting_max_connections PostgreSQL max_connections setting.",
        "# TYPE postgres_host_setting_max_connections gauge",
    ]

    for datname, size in psql(
        "select datname, pg_database_size(datname) from pg_database where datallowconn order by datname"
    ):
        output.append(line("postgres_host_database_size_bytes", {"database": datname}, size))

    for row in psql(
        """
        select datname, numbackends, xact_commit, xact_rollback, blks_read, blks_hit, deadlocks, temp_bytes
        from pg_stat_database
        where datname is not null
        order by datname
        """
    ):
        datname, numbackends, xact_commit, xact_rollback, blks_read, blks_hit, deadlocks, temp_bytes = row
        labels = {"database": datname}
        output.append(line("postgres_host_database_numbackends", labels, numbackends))
        output.append(line("postgres_host_database_xact_commit_total", labels, xact_commit))
        output.append(line("postgres_host_database_xact_rollback_total", labels, xact_rollback))
        output.append(line("postgres_host_database_blks_read_total", labels, blks_read))
        output.append(line("postgres_host_database_blks_hit_total", labels, blks_hit))
        output.append(line("postgres_host_database_deadlocks_total", labels, deadlocks))
        output.append(line("postgres_host_database_temp_bytes_total", labels, temp_bytes))

    for state, count in psql(
        "select coalesce(state, 'none'), count(*) from pg_stat_activity group by 1 order by 1"
    ):
        output.append(line("postgres_host_connections", {"state": state}, count))

    for mode, granted, count in psql(
        "select mode, granted::text, count(*) from pg_locks group by 1,2 order by 1,2"
    ):
        output.append(line("postgres_host_locks", {"mode": mode, "granted": granted}, count))

    for value, in psql("select setting from pg_settings where name = 'max_connections'"):
        output.append(line("postgres_host_setting_max_connections", {}, value))

    output.append(f"postgres_host_exporter_scrape_duration_seconds {time.time() - started:.6f}")
    output.append("postgres_host_exporter_up 1")
    return "\n".join(output) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = collect().encode()
            self.send_response(200)
        except Exception as exc:
            body = f"postgres_host_exporter_up 0\n# error: {exc}\n".encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
