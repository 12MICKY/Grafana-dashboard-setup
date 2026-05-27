# Grafana Dashboard Setup

Production Grafana and Prometheus monitoring source for the K3s homelab running on `10.33.1.34`.

This repository is the source of truth for Prometheus scrape configuration, Blackbox probe modules, Grafana provisioning, dashboard JSON files, and custom exporter code used by the live monitoring namespace. Runtime secrets are intentionally kept out of Git.

## Current Production Context

The live stack runs in K3s namespace `monitoring` on the homelab cluster.

Main access points:

- Grafana local URL: `http://10.33.1.34:3001`
- Prometheus local URL: `http://10.33.1.34:9090`
- Grafana public URL: `https://grafana.thiraphat.work`
- Primary dashboard: `http://10.33.1.34:3001/d/homelab-overview/01-overview`
- K3s dashboard: `http://10.33.1.34:3001/d/docker-monitoring-overview/03-k3s`

## Architecture

```text
Browsers / Operators
        |
        v
+-------------------+        +---------------------+
|     Grafana       | -----> |     Prometheus      |
| dashboards, SSO,  |        | scrape, rules, TSDB |
| provisioning      |        +----------+----------+
+-------------------+                   |
                                        |
          +-----------------------------+-----------------------------+
          |                             |                             |
          v                             v                             v
+---------------------+       +---------------------+       +---------------------+
| K3s pod discovery   |       | blackbox-exporter   |       | host exporters      |
| cAdvisor, nodes     |       | HTTP/DNS probes     |       | DB, UniFi, Proxmox  |
+---------------------+       +---------------------+       +---------------------+
          |
          v
+---------------------+
| Kubernetes names    |
| namespace/pod/container/node |
+---------------------+
```

Grafana dashboards are provisioned from files in this repository. The UI is not the source of truth.

## Repository Layout

```text
.
├── docker-compose.yml                  # Legacy/local lab compose file only
├── prometheus/
│   ├── prometheus.yml                  # Live K3s Prometheus scrape config source
│   └── alerts.yml                      # Prometheus alert rules
├── blackbox/
│   └── blackbox.yml                    # Live Blackbox probe module source
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml
│   │   └── dashboards/dashboards.yml
│   └── dashboards/*.json               # Provisioned Grafana dashboards
├── host-db-exporter/                   # Host DB process exporter
├── postgres-host-exporter/             # Optional PostgreSQL host exporter
├── unifi-lxc-exporter/                 # UniFi LXC exporter
└── docker-exporter/                    # Legacy Docker exporter code
```

## Live Kubernetes Services

| Service | Kubernetes object | Purpose | Port |
| --- | --- | --- | --- |
| `grafana` | Deployment + NodePort Service | Dashboard UI and provisioning | `3001 -> 3000` |
| `prometheus` | Deployment + NodePort Service | Time-series database and scrape scheduler | `9090 -> 9090` |
| `blackbox-exporter` | Deployment + ClusterIP Service | HTTP/DNS probing | `9115` |
| `node-exporter` | DaemonSet | Host CPU, RAM, disk, network metrics | `9100` |
| `cadvisor` | DaemonSet, host network | K3s container CPU, RAM, disk metrics | `8080` |
| `host-db-exporter` | DaemonSet, host network | Local SQL/Redis process counts and resources | `9102` |

## Grafana Dashboards

Dashboards are loaded from `grafana/dashboards/*.json` into the Grafana folder named `Homelab`.

| File | Dashboard Title | UID | Notes |
| --- | --- | --- | --- |
| `homelab-overview.json` | `01 Overview` | `homelab-overview` | Main status summary |
| `proxmox-home.json` | `02 Proxmox` | `proxmox-home` | Proxmox host, guests, storage, network |
| `docker-overview.json` | `03 K3s` | `docker-monitoring-overview` | K3s dashboard; UID kept for Grafana continuity |
| `server1-services-overview.json` | `04 Server1` | `server1-services-overview` | Server1 HTTP/DNS and host health |
| `db-overview.json` | `05 DB` | `db-servers-overview` | K3s app DB containers plus local SQL processes |
| `postgres-host-overview.json` | `06 PostgreSQL` | `postgres-host-overview` | PostgreSQL host metrics when exporter is present |
| `unifi-lxc-overview.json` | `07 UniFi` | `unifi-lxc-overview` | UniFi LXC and WiFi metrics |
| `home-server-overview.json` | `08 Home DNS` | `home-server-overview` | Backup DNS and Raspberry Pi host health |
| `local-services-overview.json` | `09 Local Services` | `local-services-overview` | Blackbox service and monitoring health |

## Kubernetes Label Model

K3s dashboards use Kubernetes names from cAdvisor metrics:

- `namespace`
- `pod`
- `container`
- `node`

Prometheus maps cAdvisor labels from:

- `container_label_io_kubernetes_pod_namespace` -> `namespace`
- `container_label_io_kubernetes_pod_name` -> `pod`
- `container_label_io_kubernetes_container_name` -> `container`

The raw `container_label_*` labels are dropped after mapping to keep tables readable.

Example PromQL:

```promql
topk(30,
  max by (namespace, pod, container, node) (
    container_memory_usage_bytes{job="cadvisor", namespace=~"$namespace", pod=~"$pod", container=~"$container"}
  )
)
```

## Important Production Targets

| Job | Target | Notes |
| --- | --- | --- |
| `server1-http` / `openspeedtest` | `http://10.10.10.12:8090/` | OpenSpeedTest |
| `server1-http` / `adguard-home` | `http://10.10.10.12/` | AdGuard UI |
| `server1-dns` | `10.10.10.12:53` | Server1 DNS |
| `home-server-http` | `http://10.10.10.14:8080/` | Backup AdGuard UI |
| `home-backup-dns` | `10.10.10.14:53` | Backup DNS |
| `proxmox-home` | `10.10.10.10:9100` | Proxmox node exporter |
| `proxmox-pve` | `10.10.10.10:9200` | Proxmox exporter |
| `unifi-lxc` | `10.10.10.10:9222` | UniFi LXC exporter |
| `unifi-http` | `https://10.10.10.111:8443/`, `http://10.10.10.111:8080/` | UniFi UI and inform probes |

## Deploy From This Repository

Run on `10.33.1.34`:

```bash
cd /home/thiraphat/Grafana-dashboard-setup

kubectl -n monitoring create configmap prometheus-config \
  --from-file=prometheus.yml=prometheus/prometheus.yml \
  --from-file=alerts.yml=prometheus/alerts.yml \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n monitoring create configmap blackbox-config \
  --from-file=blackbox.yml=blackbox/blackbox.yml \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n monitoring rollout restart deploy/blackbox-exporter
kubectl -n monitoring rollout status deploy/blackbox-exporter --timeout=120s

# Prometheus uses a single hostPath TSDB. Scale to zero before restart to avoid lock contention.
kubectl -n monitoring scale deploy/prometheus --replicas=0
kubectl -n monitoring wait --for=delete pod -l app=prometheus --timeout=120s
kubectl -n monitoring scale deploy/prometheus --replicas=1
kubectl -n monitoring rollout status deploy/prometheus --timeout=120s

kubectl -n monitoring rollout restart deploy/grafana
kubectl -n monitoring rollout status deploy/grafana --timeout=120s
```

## Runtime Checks

Pods:

```bash
kubectl -n monitoring get pods -o wide
```

Prometheus targets:

```bash
curl -s 'http://127.0.0.1:9090/api/v1/targets?state=active'
```

Key metric checks:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=count(up == 0)'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=probe_success{job="server1-http",service="openspeedtest"}'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=count(count by (namespace,pod) (container_last_seen{job="cadvisor",container!="",pod!="",namespace!=""}))'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=sum(host_db_process_count)'
```

Grafana provisioning logs:

```bash
kubectl -n monitoring logs deploy/grafana --since=5m | grep -Ei 'failed to save dashboard|error' || true
```

Validate dashboard JSON locally:

```bash
for f in grafana/dashboards/*.json; do
  python3 -m json.tool "$f" >/tmp/$(basename "$f").ok
done
```

## Backup Notes

Dashboard and database backups should stay outside tracked source files. Use paths such as:

```text
/home/thiraphat/Grafana-dashboard-setup-backups/
/var/lib/grafana/grafana.db.backup-YYYYMMDD-HHMM
```

The `.gitignore` excludes generated dashboard backup directories under `grafana/`.
