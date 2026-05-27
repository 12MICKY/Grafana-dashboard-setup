#!/usr/bin/env sh
set -eu

PROMETHEUS_URL=${PROMETHEUS_URL:-http://127.0.0.1:9090}
GRAFANA_URL=${GRAFANA_URL:-http://127.0.0.1:3001}
GRAFANA_USER=${GRAFANA_USER:-}
GRAFANA_PASSWORD=${GRAFANA_PASSWORD:-}

query() {
  expr=$1
  python3 - "$PROMETHEUS_URL" "$expr" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

base, expr = sys.argv[1], sys.argv[2]
url = base.rstrip("/") + "/api/v1/query?query=" + urllib.parse.quote(expr)
with urllib.request.urlopen(url, timeout=15) as r:
    data = json.load(r)
if data.get("status") != "success":
    raise SystemExit(f"query failed: {expr}: {data}")
result = data.get("data", {}).get("result", [])
print(json.dumps(result))
PY
}

require_nonempty() {
  expr=$1
  result=$(query "$expr")
  python3 - "$expr" "$result" <<'PY'
import json
import sys
expr = sys.argv[1]
result = json.loads(sys.argv[2])
if not result:
    raise SystemExit(f"no data for query: {expr}")
PY
}

require_value() {
  expr=$1
  expected=$2
  result=$(query "$expr")
  python3 - "$expr" "$expected" "$result" <<'PY'
import json
import sys
expr, expected = sys.argv[1], sys.argv[2]
result = json.loads(sys.argv[3])
if not result:
    raise SystemExit(f"no data for query: {expr}")
value = result[0]["value"][1]
if value != expected:
    raise SystemExit(f"unexpected value for {expr}: got {value}, want {expected}")
PY
}

echo "==> checking Prometheus health at $PROMETHEUS_URL"
require_nonempty 'up'
require_value 'sum(up == 0) or vector(0)' '0'

echo "==> checking OpenSpeedTest target"
require_value 'probe_success{job="server1-http",service="openspeedtest"}' '1'

echo "==> checking Kubernetes container labels"
require_nonempty 'count(count by (namespace,pod) (container_last_seen{job="cadvisor",container!="",pod!="",namespace!=""}))'
require_nonempty 'topk(5, max by (namespace,pod,container,node) (container_memory_usage_bytes{job="cadvisor",container!="",pod!="",namespace!=""}))'

echo "==> checking DB metrics"
require_nonempty 'count(count by (namespace,pod,container,node) (container_last_seen{job="cadvisor",container=~"postgresql|database|db|redis|mysql|mariadb|valkey",namespace=~"authentik|immich|librenms|nextcloud"}))'
require_nonempty 'sum(host_db_process_count)'

if [ -n "$GRAFANA_USER" ] && [ -n "$GRAFANA_PASSWORD" ]; then
  echo "==> checking Grafana API at $GRAFANA_URL"
  python3 - "$GRAFANA_URL" "$GRAFANA_USER" "$GRAFANA_PASSWORD" <<'PY'
import base64
import json
import sys
import urllib.request

url, user, password = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request(url.rstrip() + "/api/search?query=03")
token = base64.b64encode(f"{user}:{password}".encode()).decode()
req.add_header("Authorization", "Basic " + token)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.load(r)
if not any(d.get("uid") == "docker-monitoring-overview" and d.get("title") == "03 K3s" for d in data):
    raise SystemExit("03 K3s dashboard not found through Grafana API")
PY
else
  echo "==> Grafana API check skipped; set GRAFANA_USER and GRAFANA_PASSWORD to enable"
fi

echo "smoke test ok"
