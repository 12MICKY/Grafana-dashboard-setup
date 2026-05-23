import json
import os
import socket
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOCKER_SOCKET = "/var/run/docker.sock"
CGROUP_ROOT = "/host/sys/fs/cgroup/system.slice"
PORT = 9101
NODE_NAME = socket.gethostname()


def docker_get(path):
    request = (
        f"GET {path} HTTP/1.0\r\n"
        "Host: docker\r\n"
        "\r\n"
    ).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(DOCKER_SOCKET)
        sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(65536)
        header, _, body = response.partition(b"\r\n\r\n")
        headers = {}
        for row in header.splitlines()[1:]:
            key, _, value = row.decode("utf-8", "replace").partition(":")
            headers[key.lower()] = value.strip()
        if headers.get("transfer-encoding") == "chunked":
            while b"\r\n0\r\n\r\n" not in body:
                body += sock.recv(65536)
        elif headers.get("content-length", "").isdigit():
            length = int(headers["content-length"])
            while len(body) < length:
                body += sock.recv(65536)
            body = body[:length]
        else:
            while True:
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    break
                if not data:
                    break
                body += data
    status = header.splitlines()[0].decode("utf-8", "replace")
    if " 200 " not in status:
        raise RuntimeError(status)
    if headers.get("transfer-encoding") == "chunked":
        body = decode_chunked(body)
    return json.loads(body.decode("utf-8"))


def decode_chunked(body):
    decoded = b""
    while body:
        size_text, _, rest = body.partition(b"\r\n")
        size = int(size_text.split(b";", 1)[0], 16)
        if size == 0:
            break
        decoded += rest[:size]
        body = rest[size + 2 :]
    return decoded


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def esc(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def line(name, labels, value):
    label_text = ",".join(f'{key}="{esc(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def container_name(container):
    names = container.get("Names") or []
    return names[0].lstrip("/") if names else container.get("Id", "")[:12]


def swarm_label(labels, key):
    return (labels or {}).get(key, "")


def db_type(name, image):
    value = f"{name} {image}".lower()
    if "mariadb" in value or "mysql" in value:
        return "mysql"
    if "postgres" in value or "postgis" in value:
        return "postgres"
    if "redis" in value or "valkey" in value:
        return "redis"
    return ""


def parse_docker_time(value):
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def cgroup_path(container_id):
    return os.path.join(CGROUP_ROOT, f"docker-{container_id}.scope")


def cpu_seconds(path):
    for row in read_text(os.path.join(path, "cpu.stat")).splitlines():
        key, _, value = row.partition(" ")
        if key == "usage_usec" and value.isdigit():
            return int(value) / 1_000_000
    return 0


def memory(path):
    current = read_text(os.path.join(path, "memory.current")).strip()
    maximum = read_text(os.path.join(path, "memory.max")).strip()
    usage = int(current) if current.isdigit() else 0
    limit = int(maximum) if maximum.isdigit() else 0
    return usage, limit


def block_io(path):
    read_bytes = 0
    write_bytes = 0
    for row in read_text(os.path.join(path, "io.stat")).splitlines():
        for part in row.split()[1:]:
            key, _, value = part.partition("=")
            if not value.isdigit():
                continue
            if key == "rbytes":
                read_bytes += int(value)
            elif key == "wbytes":
                write_bytes += int(value)
    return read_bytes, write_bytes


def collect():
    started = time.time()
    info = docker_get("/info")
    node_name = info.get("Name") or NODE_NAME
    containers = docker_get("/containers/json")
    output = [
        "# HELP docker_container_up Whether the Docker container is running.",
        "# TYPE docker_container_up gauge",
        "# HELP docker_container_cpu_usage_seconds_total Docker container cumulative CPU usage.",
        "# TYPE docker_container_cpu_usage_seconds_total counter",
        "# HELP docker_container_memory_usage_bytes Docker container memory usage.",
        "# TYPE docker_container_memory_usage_bytes gauge",
        "# HELP docker_containers_running Running Docker containers.",
        "# TYPE docker_containers_running gauge",
    ]
    running = 0

    for container in containers:
        state = container.get("State", "")
        container_id = container.get("Id", "")
        docker_labels = container.get("Labels") or {}
        labels = {
            "id": container_id[:12],
            "node": node_name,
            "name": container_name(container),
            "image": container.get("Image", ""),
            "state": state,
            "stack": swarm_label(docker_labels, "com.docker.stack.namespace"),
            "service": swarm_label(docker_labels, "com.docker.swarm.service.name"),
            "task": swarm_label(docker_labels, "com.docker.swarm.task.name"),
        }
        is_running = 1 if state == "running" else 0
        running += is_running
        output.append(line("docker_container_up", labels, is_running))
        if not is_running:
            continue

        path = cgroup_path(container_id)
        mem_usage, mem_limit = memory(path)
        read_bytes, write_bytes = block_io(path)
        output.append(line("docker_container_cpu_usage_seconds_total", labels, cpu_seconds(path)))
        output.append(line("docker_container_memory_usage_bytes", labels, mem_usage))
        output.append(line("docker_container_memory_limit_bytes", labels, mem_limit))
        output.append(line("docker_container_block_read_bytes_total", labels, read_bytes))
        output.append(line("docker_container_block_write_bytes_total", labels, write_bytes))

        database = db_type(labels["name"], labels["image"])
        if database:
            details = docker_get(f"/containers/{container_id}/json")
            state_info = details.get("State") or {}
            db_labels = {
                "id": labels["id"],
                "node": node_name,
                "name": labels["name"],
                "image": labels["image"],
                "db_type": database,
                "service": labels["service"],
                "stack": labels["stack"],
            }
            health = (state_info.get("Health") or {}).get("Status") or "none"
            output.append(line("db_container_up", db_labels, 1))
            output.append(line("db_container_restart_count", db_labels, details.get("RestartCount", 0)))
            output.append(line("db_container_started_seconds", db_labels, parse_docker_time(state_info.get("StartedAt"))))
            output.append(line("db_container_health_status", {**db_labels, "health": health}, 1))

    output.append(line("docker_containers_running", {"node": node_name}, running))
    output.append(f"docker_exporter_scrape_duration_seconds {time.time() - started:.6f}")
    output.append("docker_exporter_up 1")
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
            body = f"docker_exporter_up 0\n# error: {exc}\n".encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
