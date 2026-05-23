import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROC_ROOT = "/host/proc"
PORT = 9102
NODE_NAME = os.getenv("NODE_NAME", socket.gethostname())
TICKS = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


def esc(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def line(name, labels, value):
    label_text = ",".join(f'{key}="{esc(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def db_type(command):
    value = command.lower()
    if "postgres" in value:
        return "postgres"
    if "mysqld" in value or "mariadbd" in value or "mysql" in value:
        return "mysql"
    if "redis-server" in value:
        return "redis"
    if "valkey-server" in value:
        return "valkey"
    return ""


def proc_cmd(pid):
    raw = read_text(os.path.join(PROC_ROOT, pid, "cmdline"))
    if raw:
        return raw.replace("\x00", " ").strip()
    return read_text(os.path.join(PROC_ROOT, pid, "comm")).strip()


def proc_stat(pid):
    raw = read_text(os.path.join(PROC_ROOT, pid, "stat"))
    if not raw:
        return 0, 0
    after_name = raw.rsplit(") ", 1)[-1].split()
    # procfs fields after comm start at state. utime/stime are fields 14/15.
    utime = int(after_name[11])
    stime = int(after_name[12])
    rss_pages = int(after_name[21])
    return (utime + stime) / TICKS, rss_pages * PAGE_SIZE


def collect():
    output = [
        "# HELP host_db_process_up Host database process is present.",
        "# TYPE host_db_process_up gauge",
        "# HELP host_db_process_cpu_seconds_total Host database process cumulative CPU seconds.",
        "# TYPE host_db_process_cpu_seconds_total counter",
        "# HELP host_db_process_memory_rss_bytes Host database process RSS memory.",
        "# TYPE host_db_process_memory_rss_bytes gauge",
    ]
    counts = {}

    for pid in os.listdir(PROC_ROOT):
        if not pid.isdigit():
            continue
        command = proc_cmd(pid)
        database = db_type(command)
        if not database:
            continue
        cpu, rss = proc_stat(pid)
        name = command.split()[0].split("/")[-1] if command else "unknown"
        labels = {
            "node": NODE_NAME,
            "pid": pid,
            "db_type": database,
            "process": name,
            "command": command[:160],
        }
        output.append(line("host_db_process_up", labels, 1))
        output.append(line("host_db_process_cpu_seconds_total", labels, cpu))
        output.append(line("host_db_process_memory_rss_bytes", labels, rss))
        counts[database] = counts.get(database, 0) + 1

    for database, count in counts.items():
        output.append(line("host_db_process_count", {"node": NODE_NAME, "db_type": database}, count))

    output.append(line("host_db_exporter_up", {"node": NODE_NAME}, 1))
    output.append(f"host_db_exporter_scrape_timestamp_seconds {time.time():.0f}")
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
            body = f"host_db_exporter_up 0\n# error: {exc}\n".encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
