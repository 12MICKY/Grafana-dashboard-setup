#!/usr/bin/env python3
import re
import subprocess
import time
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9222
VMID = "102"
NAME = "unifi"
EXPECTED_TCP_PORTS = [8443, 8080, 8843, 8880, 6789, 28082, 27117]
EXPECTED_UDP_PORTS = [3478, 10001, 5514]


def esc(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def line(name, labels, value):
    label_text = ",".join(f'{key}="{esc(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def run(command, timeout=8):
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        return ""
    return result.stdout


def pct_exec(*args, timeout=8):
    return run(["pct", "exec", VMID, "--", *args], timeout=timeout)


def is_active(service):
    return 1 if pct_exec("systemctl", "is-active", service).strip() == "active" else 0


def port_open(protocol, port, ss_output):
    needle = f":{port}"
    for row in ss_output.splitlines():
        if row.startswith(protocol) and needle in row:
            return 1
    return 0


def process_rss(process_name, ps_output):
    total = 0
    for row in ps_output.splitlines():
        parts = row.split(None, 2)
        if len(parts) < 3:
            continue
        rss, comm, _args = parts
        if comm == process_name and rss.isdigit():
            total += int(rss) * 1024
    return total


def process_count(process_name, ps_output):
    count = 0
    for row in ps_output.splitlines():
        parts = row.split(None, 2)
        if len(parts) >= 2 and parts[1] == process_name:
            count += 1
    return count


def uptime_seconds():
    raw = pct_exec("cat", "/proc/uptime").split()
    if not raw:
        return 0
    try:
        return float(raw[0])
    except ValueError:
        return 0


def mongo_json(database, javascript, timeout=12):
    raw = pct_exec(
        "mongosh",
        "--quiet",
        "--port",
        "27117",
        database,
        "--eval",
        javascript,
        timeout=timeout,
    ).strip()
    if not raw:
        return None
    # mongosh can print warnings before JSON on some versions; keep the last JSON-looking line.
    for row in reversed(raw.splitlines()):
        row = row.strip()
        if row.startswith("{") or row.startswith("["):
            try:
                return json.loads(row)
            except json.JSONDecodeError:
                continue
    return None


def collect_wlan_metrics():
    snapshot = mongo_json(
        "ace",
        """
        const wlans = db.wlanconf.find({}, {
          name: 1, enabled: 1, wlan_band: 1, security: 1
        }).toArray().map(w => ({
          id: String(w._id),
          name: w.name || String(w._id),
          enabled: w.enabled === true ? 1 : 0,
          band: w.wlan_band || "",
          security: w.security || ""
        }));

        const now = Math.floor(Date.now() / 1000);
        const users = db.user.find({
          is_wired: false,
          wlanconf_id: {$exists: true},
          last_seen: {$gt: now - 900}
        }, {
          wlanconf_id: 1, mac: 1
        }).toArray().map(u => ({
          wlan_id: String(u.wlanconf_id),
          mac: u.mac || ""
        }));

        const sibling = db.getSiblingDB("ace_stat");
        const site_stats = sibling.stat_5minutes.find({o: "site"}).sort({time: -1}).limit(1).toArray()[0] || {};
        const daily_rows = sibling.stat_daily.find({o: "ap_analytics"}).sort({time: -1}).limit(90).toArray();
        const daily_stats = daily_rows.find(r => Object.keys(r).some(k => k.endsWith("-rx_bytes") || k.endsWith("-tx_bytes"))) || daily_rows[0] || {};
        const latest_user_stat = sibling.stat_daily.find({o: "user"}).sort({time: -1}).limit(1).toArray()[0] || {};
        const user_daily_traffic = {};
        if (latest_user_stat.time) {
          sibling.stat_daily.find({o: "user", time: latest_user_stat.time}).limit(5000).toArray().forEach(row => {
            let wlan_id = "";
            for (const key of Object.keys(row)) {
              if (!key.startsWith("x-") && key.endsWith("-wlan_conf_id_most_common")) {
                wlan_id = String(row[key] || "");
                break;
              }
            }
            if (!wlan_id) {
              for (const key of Object.keys(row)) {
                if (key.startsWith("x-counters-") && key.endsWith("-wlan_conf_id_most_common")) {
                  const counters = row[key] || {};
                  const ids = Object.keys(counters);
                  if (ids.length > 0) {
                    wlan_id = ids[0];
                    break;
                  }
                }
              }
            }
            if (!wlan_id) return;
            if (!user_daily_traffic[wlan_id]) user_daily_traffic[wlan_id] = {rx_bytes: 0, tx_bytes: 0};
            user_daily_traffic[wlan_id].rx_bytes += Number(row.rx_bytes || 0);
            user_daily_traffic[wlan_id].tx_bytes += Number(row.tx_bytes || 0);
          });
        }
        print(JSON.stringify({wlans, users, site_stats, daily_stats, user_daily_traffic}));
        """,
    ) or {}

    wlans = snapshot.get("wlans") or []
    users = snapshot.get("users") or []
    site_stats = snapshot.get("site_stats") or {}
    daily_stats = snapshot.get("daily_stats") or {}
    user_daily_traffic = snapshot.get("user_daily_traffic") or {}

    wlan_by_id = {str(wlan.get("id", "")): wlan for wlan in wlans}
    client_counts = {}
    for user in users:
        wlan_id = str(user.get("wlan_id", ""))
        client_counts[wlan_id] = client_counts.get(wlan_id, 0) + 1

    stat_5m_counts = {}
    for key, value in site_stats.items():
        match = re.match(r"wlan_configuration-([0-9a-f]+)-num_sta_max$", key)
        if match:
            stat_5m_counts[match.group(1)] = float(value or 0)

    traffic = {}
    id_pattern = r"([0-9a-f]{24})"
    for key, value in daily_stats.items():
        if key.startswith("x-"):
            continue
        match = re.match(rf".*-{id_pattern}-(rx_bytes|tx_bytes|performance|client_signal_avg|wifi_tx_latency_avg|sta_dns_failures|sta_dhcp_failures)$", key)
        if not match:
            continue
        wlan_id, metric = match.groups()
        traffic.setdefault(wlan_id, {})
        traffic[wlan_id][metric] = float(value or 0)

    for wlan_id, stats in user_daily_traffic.items():
        traffic.setdefault(str(wlan_id), {})
        traffic[str(wlan_id)]["rx_bytes"] = float(stats.get("rx_bytes") or 0)
        traffic[str(wlan_id)]["tx_bytes"] = float(stats.get("tx_bytes") or 0)

    lines = [
        "# HELP unifi_wlan_enabled UniFi WLAN enabled state.",
        "# TYPE unifi_wlan_enabled gauge",
        "# HELP unifi_wlan_clients UniFi active wireless clients by WLAN.",
        "# TYPE unifi_wlan_clients gauge",
        "# HELP unifi_wlan_clients_5m_max UniFi maximum wireless clients in the latest 5 minute stat by WLAN.",
        "# TYPE unifi_wlan_clients_5m_max gauge",
        "# HELP unifi_wlan_rx_bytes_daily UniFi daily receive bytes by WLAN.",
        "# TYPE unifi_wlan_rx_bytes_daily gauge",
        "# HELP unifi_wlan_tx_bytes_daily UniFi daily transmit bytes by WLAN.",
        "# TYPE unifi_wlan_tx_bytes_daily gauge",
        "# HELP unifi_wlan_performance UniFi WLAN performance score.",
        "# TYPE unifi_wlan_performance gauge",
        "# HELP unifi_wlan_client_signal_dbm UniFi WLAN average client signal.",
        "# TYPE unifi_wlan_client_signal_dbm gauge",
        "# HELP unifi_wlan_wifi_tx_latency_ms UniFi WLAN WiFi transmit latency.",
        "# TYPE unifi_wlan_wifi_tx_latency_ms gauge",
        "# HELP unifi_wlan_dns_failures_daily UniFi daily DNS failures by WLAN.",
        "# TYPE unifi_wlan_dns_failures_daily gauge",
        "# HELP unifi_wlan_dhcp_failures_daily UniFi daily DHCP failures by WLAN.",
        "# TYPE unifi_wlan_dhcp_failures_daily gauge",
    ]

    for wlan_id, wlan in wlan_by_id.items():
        labels = {
            "vmid": VMID,
            "name": NAME,
            "wlan_id": wlan_id,
            "ssid": wlan.get("name", wlan_id),
            "band": wlan.get("band", ""),
            "security": wlan.get("security", ""),
        }
        stats = traffic.get(wlan_id, {})
        lines.append(line("unifi_wlan_enabled", labels, wlan.get("enabled", 0)))
        lines.append(line("unifi_wlan_clients", labels, client_counts.get(wlan_id, 0)))
        lines.append(line("unifi_wlan_clients_5m_max", labels, stat_5m_counts.get(wlan_id, 0)))
        lines.append(line("unifi_wlan_rx_bytes_daily", labels, stats.get("rx_bytes", 0)))
        lines.append(line("unifi_wlan_tx_bytes_daily", labels, stats.get("tx_bytes", 0)))
        if "performance" in stats:
            lines.append(line("unifi_wlan_performance", labels, stats["performance"]))
        if "client_signal_avg" in stats:
            lines.append(line("unifi_wlan_client_signal_dbm", labels, stats["client_signal_avg"]))
        if "wifi_tx_latency_avg" in stats:
            lines.append(line("unifi_wlan_wifi_tx_latency_ms", labels, stats["wifi_tx_latency_avg"]))
        lines.append(line("unifi_wlan_dns_failures_daily", labels, stats.get("sta_dns_failures", 0)))
        lines.append(line("unifi_wlan_dhcp_failures_daily", labels, stats.get("sta_dhcp_failures", 0)))

    return lines


def collect():
    started = time.time()
    base = {"vmid": VMID, "name": NAME}
    output = [
        "# HELP unifi_lxc_exporter_up UniFi LXC exporter scrape status.",
        "# TYPE unifi_lxc_exporter_up gauge",
        "# HELP unifi_lxc_service_up UniFi LXC systemd service status.",
        "# TYPE unifi_lxc_service_up gauge",
        "# HELP unifi_lxc_port_open UniFi LXC expected port status.",
        "# TYPE unifi_lxc_port_open gauge",
        "# HELP unifi_lxc_process_rss_bytes UniFi LXC process RSS memory.",
        "# TYPE unifi_lxc_process_rss_bytes gauge",
        "# HELP unifi_lxc_process_count UniFi LXC process count.",
        "# TYPE unifi_lxc_process_count gauge",
        "# HELP unifi_lxc_uptime_seconds UniFi LXC uptime.",
        "# TYPE unifi_lxc_uptime_seconds gauge",
    ]

    status = run(["pct", "status", VMID]).strip()
    running = 1 if "status: running" in status else 0
    output.append(line("unifi_lxc_up", base, running))
    if not running:
        output.append("unifi_lxc_exporter_up 1")
        return "\n".join(output) + "\n"

    ss_output = pct_exec("ss", "-lntup")
    ps_output = pct_exec("ps", "-eo", "rss,comm,args")

    output.append(line("unifi_lxc_service_up", {**base, "service": "unifi"}, is_active("unifi")))
    output.append(line("unifi_lxc_process_rss_bytes", {**base, "process": "java"}, process_rss("java", ps_output)))
    output.append(line("unifi_lxc_process_rss_bytes", {**base, "process": "mongod"}, process_rss("mongod", ps_output)))
    output.append(line("unifi_lxc_process_count", {**base, "process": "java"}, process_count("java", ps_output)))
    output.append(line("unifi_lxc_process_count", {**base, "process": "mongod"}, process_count("mongod", ps_output)))
    output.append(line("unifi_lxc_uptime_seconds", base, uptime_seconds()))
    output.extend(collect_wlan_metrics())

    for port in EXPECTED_TCP_PORTS:
        output.append(line("unifi_lxc_port_open", {**base, "protocol": "tcp", "port": port}, port_open("tcp", port, ss_output)))
    for port in EXPECTED_UDP_PORTS:
        output.append(line("unifi_lxc_port_open", {**base, "protocol": "udp", "port": port}, port_open("udp", port, ss_output)))

    output.append(f"unifi_lxc_exporter_scrape_duration_seconds {time.time() - started:.6f}")
    output.append("unifi_lxc_exporter_up 1")
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
            body = f"unifi_lxc_exporter_up 0\n# error: {exc}\n".encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
