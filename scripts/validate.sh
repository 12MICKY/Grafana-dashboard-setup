#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "==> validating required operator docs"
test -s AGENTS.md
test -s MONITORING_CONFIG.md
grep -q "MONITORING_CONFIG.md" AGENTS.md
grep -q "Production is K3s" AGENTS.md
grep -q "Do not rely on \`README.md\`" MONITORING_CONFIG.md

echo "==> checking for public-repo secret patterns"
if grep -RInE '(password|secret|token|client_secret|api[_-]?key)[[:space:]]*[:=][[:space:]]*[^ <$"{]' \
  --exclude-dir=.git \
  --exclude='*.md' \
  --exclude='.env.example' \
  --exclude='smoke-test.sh' \
  .; then
  echo "Potential committed secret found. Review the matches above." >&2
  exit 1
fi

echo "==> validating Grafana dashboard JSON"
for f in grafana/dashboards/*.json; do
  python3 -m json.tool "$f" >/tmp/"$(basename "$f")".ok
done

echo "==> validating dashboard UID invariants"
python3 - <<'PY'
import json
from pathlib import Path

expected = {
    "homelab-overview.json": ("01 Overview", "homelab-overview"),
    "proxmox-home.json": ("02 Proxmox", "proxmox-home"),
    "docker-overview.json": ("03 K3s", "docker-monitoring-overview"),
    "server1-services-overview.json": ("04 Server1", "server1-services-overview"),
    "db-overview.json": ("05 DB", "db-servers-overview"),
    "postgres-host-overview.json": ("06 PostgreSQL", "postgres-host-overview"),
    "unifi-lxc-overview.json": ("07 UniFi", "unifi-lxc-overview"),
    "home-server-overview.json": ("08 Home DNS", "home-server-overview"),
    "local-services-overview.json": ("09 Local Services", "local-services-overview"),
}
expected_links = {
    "Overview": "/d/homelab-overview/01-overview?orgId=1&refresh=10s",
    "Proxmox": "/d/proxmox-home/02-proxmox?orgId=1&refresh=10s",
    "K3s": "/d/docker-monitoring-overview/03-k3s?orgId=1&refresh=10s",
    "Server1": "/d/server1-services-overview/04-server1?orgId=1&refresh=10s",
    "DB": "/d/db-servers-overview/05-db?orgId=1&refresh=10s",
    "PostgreSQL": "/d/postgres-host-overview/06-postgresql?orgId=1&refresh=10s",
    "UniFi": "/d/unifi-lxc-overview/07-unifi?orgId=1&refresh=10s",
    "Home DNS": "/d/home-server-overview/08-home-dns?orgId=1&refresh=10s",
    "Local Services": "/d/local-services-overview/09-local-services?orgId=1&refresh=10s",
}

dash_dir = Path("grafana/dashboards")
seen = set()
for filename, (title, uid) in expected.items():
    path = dash_dir / filename
    data = json.loads(path.read_text())
    assert data.get("title") == title, f"{filename}: title mismatch"
    assert data.get("uid") == uid, f"{filename}: uid mismatch"
    assert data.get("id") in (None, 0), f"{filename}: provisioned dashboard id must be null"
    assert len(data.get("links", [])) >= 9, f"{filename}: expected shared nav links"
    for link in data.get("links", []):
        if link.get("title") in expected_links:
            assert link.get("url") == expected_links[link["title"]], f"{filename}: stale link for {link['title']}"
    seen.add(data["uid"])

assert len(seen) == len(expected), "dashboard UIDs must be unique"

k3s = json.loads((dash_dir / "docker-overview.json").read_text())
variables = {v["name"] for v in k3s.get("templating", {}).get("list", [])}
for name in ("top", "namespace", "pod", "container", "node"):
    assert name in variables, f"03 K3s missing ${name} variable"

db = json.loads((dash_dir / "db-overview.json").read_text())
db_text = json.dumps(db)
for label in ("namespace", "pod", "container", "node"):
    assert label in db_text, f"05 DB should use Kubernetes {label} labels"

local_services = json.loads((dash_dir / "local-services-overview.json").read_text())
local_services_text = json.dumps(local_services)
assert "docker-exporter" not in local_services_text, "09 Local Services should not reference legacy docker-exporter"
PY

echo "==> validating YAML syntax"
python3 - <<'PY'
from pathlib import Path
import sys

try:
    import yaml
except Exception:
    print("PyYAML not installed; skipping YAML parser validation")
    sys.exit(0)

for path in [
    "prometheus/prometheus.yml",
    "prometheus/alerts.yml",
    "blackbox/blackbox.yml",
    ".github/workflows/deploy.yml",
]:
    with open(path) as f:
        yaml.safe_load(f)
PY

if command -v promtool >/dev/null 2>&1; then
  echo "==> validating Prometheus config with promtool"
  promtool check config prometheus/prometheus.yml
else
  echo "==> promtool not installed; skipped Prometheus semantic validation"
fi

echo "validation ok"
