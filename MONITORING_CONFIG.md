# Monitoring Config

This file is the operational source of truth for the homelab monitoring stack.
Read it before making any change. Do not rely on `README.md` for implementation
details.

## Live Environment

Production runs on the K3s cluster reachable from `10.33.1.34`.

Primary node:

- Host: `10.33.1.34`
- User for normal SSH: `thiraphat`
- K3s namespace: `monitoring`
- Repository path: `/home/thiraphat/Grafana-dashboard-setup`

Important URLs:

- Grafana local: `http://10.33.1.34:3001`
- Prometheus local: `http://10.33.1.34:9090`
- Grafana public: `https://grafana.thiraphat.work`

Important external targets:

| Name | Address | Purpose |
| --- | --- | --- |
| Proxmox node exporter | `10.10.10.10:9100` | Proxmox host metrics |
| Proxmox exporter | `10.10.10.10:9200` | Proxmox guests/storage metrics |
| UniFi LXC exporter | `10.10.10.10:9222` | UniFi LXC process, port, WiFi metrics |
| UniFi UI | `https://10.10.10.111:8443/` | Blackbox HTTPS probe |
| UniFi inform | `http://10.10.10.111:8080/` | Blackbox HTTP probe |
| Server1 node exporter | `10.10.10.12:9100` | Server1 host metrics |
| Server1 OpenSpeedTest | `http://10.10.10.12:8090/` | Blackbox HTTP probe |
| Server1 AdGuard UI | `http://10.10.10.12/` | Blackbox HTTP probe |
| Server1 AdGuard DNS | `10.10.10.12:53` | Blackbox DNS probe |
| Home backup node exporter | `10.10.10.14:9100` | Raspberry Pi host metrics |
| Home backup AdGuard UI | `http://10.10.10.14:8080/` | Blackbox HTTP probe |
| Home backup DNS | `10.10.10.14:53` | Blackbox DNS probe |

## Production Is K3s

The live monitoring stack is not Docker Swarm. Do not deploy with Swarm commands.

Forbidden for production:

```bash
docker stack deploy
docker service update
docker stack services monitoring
```

Use Kubernetes commands through `kubectl`.

Core live workloads:

```bash
kubectl -n monitoring get deploy,ds,svc,pods -o wide
```

Expected workload model:

| Workload | Kind | Notes |
| --- | --- | --- |
| `grafana` | Deployment | Mounts dashboard/provisioning files from hostPath repository |
| `prometheus` | Deployment | Uses hostPath TSDB; must restart carefully |
| `blackbox-exporter` | Deployment | Uses `blackbox-config` ConfigMap |
| `node-exporter` | DaemonSet | Scraped through Kubernetes pod discovery |
| `cadvisor` | DaemonSet | Host network, exposes K3s container labels |
| `host-db-exporter` | DaemonSet | Host network, scrapes local SQL/Redis process state |

## Repository Source Of Truth

Production source files:

| Path | Role |
| --- | --- |
| `prometheus/prometheus.yml` | Prometheus scrape jobs and service discovery |
| `prometheus/alerts.yml` | Prometheus alert rules |
| `blackbox/blackbox.yml` | Blackbox probe modules |
| `grafana/provisioning/datasources/prometheus.yml` | Grafana Prometheus datasource |
| `grafana/provisioning/dashboards/dashboards.yml` | Grafana dashboard file provider |
| `grafana/dashboards/*.json` | Dashboard source files |
| `host-db-exporter/host_db_exporter.py` | Local host DB process exporter |
| `unifi-lxc-exporter/unifi_lxc_exporter.py` | UniFi LXC exporter |
| `postgres-host-exporter/postgres_host_exporter.py` | Optional PostgreSQL host exporter |

Legacy or non-production:

| Path | Status |
| --- | --- |
| `docker-compose.yml` | Local/lab reference only |
| `docker-exporter/` | Legacy Docker exporter code |
| `swarm-stack.yml` | Removed/obsolete for this K3s production stack |

## Grafana Dashboard Rules

Dashboards are provisioned from `grafana/dashboards/*.json`.

Do not treat UI edits as source of truth. If a dashboard is edited in Grafana UI,
export the JSON and commit the file change.

Dashboard list:

| File | Title | UID |
| --- | --- | --- |
| `homelab-overview.json` | `01 Overview` | `homelab-overview` |
| `proxmox-home.json` | `02 Proxmox` | `proxmox-home` |
| `docker-overview.json` | `03 K3s` | `docker-monitoring-overview` |
| `server1-services-overview.json` | `04 Server1` | `server1-services-overview` |
| `db-overview.json` | `05 DB` | `db-servers-overview` |
| `postgres-host-overview.json` | `06 PostgreSQL` | `postgres-host-overview` |
| `unifi-lxc-overview.json` | `07 UniFi` | `unifi-lxc-overview` |
| `home-server-overview.json` | `08 Home DNS` | `home-server-overview` |
| `local-services-overview.json` | `09 Local Services` | `local-services-overview` |

Important UID rule:

- `docker-overview.json` is now the K3s dashboard.
- Its UID must remain `docker-monitoring-overview`.
- Keep the `03 K3s` title and `docker-monitoring-overview` UID stable.
- That UID is kept to avoid Grafana provisioning/database conflicts.

Every dashboard should keep:

- Shared dashboard navigation links for all 9 dashboards.
- `refresh: 10s` unless there is a specific reason not to.
- `graphTooltip: 1` for shared crosshair tooltip behavior.
- Stat panels should use `options.textMode: value` when the panel is intended
  to show one number.
- Stat panel PromQL should aggregate to one series with `sum`, `max`, `avg`,
  `count`, or `count(count by (...))`.
- Table panels should expose human names, not runtime IDs.

## Kubernetes Label Model

K3s dashboards use these labels:

- `namespace`
- `pod`
- `container`
- `node`

cAdvisor exports raw Kubernetes labels. Prometheus maps them in
`prometheus/prometheus.yml`:

```yaml
metric_relabel_configs:
  - source_labels:
      - container_label_io_kubernetes_pod_namespace
    target_label: namespace
  - source_labels:
      - container_label_io_kubernetes_pod_name
    target_label: pod
  - source_labels:
      - container_label_io_kubernetes_container_name
    target_label: container
  - regex: container_label_.*
    action: labeldrop
```

The `labeldrop` rule is intentional. Keep it unless a dashboard explicitly needs
raw image labels. Raw `container_label_*` fields make Grafana tables noisy.

Required cAdvisor DaemonSet argument:

```text
--store_container_labels=true
```

Without this, `namespace`, `pod`, and `container` cannot be mapped reliably.

## K3s Dashboard Query Pattern

Use Kubernetes names in legends:

```text
{{namespace}}/{{pod}}/{{container}}
```

Memory table pattern:

```promql
topk(
  $top,
  max by (namespace, pod, container, node) (
    container_memory_usage_bytes{
      job="cadvisor",
      namespace=~"$namespace",
      pod=~"$pod",
      container=~"$container",
      container!="",
      pod!="",
      node=~"$node"
    }
  )
)
```

CPU pattern:

```promql
topk(
  10,
  max by (namespace, pod, container) (
    rate(container_cpu_usage_seconds_total{
      job="cadvisor",
      namespace=~"$namespace",
      pod=~"$pod",
      container=~"$container",
      container!="",
      pod!="",
      node=~"$node"
    }[5m]) * 100
  )
)
```

Why `max by` instead of `sum by`:

- It deduplicates overlapping stale series after cAdvisor or Prometheus restarts.
- It avoids double-counting during label migration windows.
- It is safer for per-container point-in-time gauges like memory.

## DB Dashboard Model

There are two DB data sources:

1. K3s app DB containers from cAdvisor.
2. Local DB processes on the host from `host-db-exporter`.

K3s app DB filter:

```promql
container=~"postgresql|database|db|redis|mysql|mariadb|valkey"
namespace=~"authentik|immich|librenms|nextcloud"
```

Current known K3s DB namespaces:

- `authentik`
- `immich`
- `librenms`
- `nextcloud`

Local DB metric examples:

```promql
host_db_process_count
sum(host_db_process_count)
sum by (node, db_type) (host_db_process_memory_rss_bytes)
sum by (node, db_type) (rate(host_db_process_cpu_seconds_total[5m])) * 100
```

When adding a new K3s app DB namespace, update the DB dashboard filters and
Prometheus validation checks if that namespace should appear in `05 DB`.

## Prometheus Restart Rule

Prometheus uses a single hostPath TSDB. Do not do a normal rolling restart that
temporarily runs two Prometheus pods against the same storage directory.

Safe restart:

```bash
kubectl -n monitoring scale deploy/prometheus --replicas=0
kubectl -n monitoring wait --for=delete pod -l app=prometheus --timeout=120s
kubectl -n monitoring scale deploy/prometheus --replicas=1
kubectl -n monitoring rollout status deploy/prometheus --timeout=120s
```

If this rule is ignored, the new pod may crash with:

```text
opening storage failed: lock DB directory: resource temporarily unavailable
```

## Deploy Config Changes

Run from `/home/thiraphat/Grafana-dashboard-setup` on `10.33.1.34`.

Prometheus ConfigMap:

```bash
kubectl -n monitoring create configmap prometheus-config \
  --from-file=prometheus.yml=prometheus/prometheus.yml \
  --from-file=alerts.yml=prometheus/alerts.yml \
  --dry-run=client -o yaml | kubectl apply -f -
```

Blackbox ConfigMap:

```bash
kubectl -n monitoring create configmap blackbox-config \
  --from-file=blackbox.yml=blackbox/blackbox.yml \
  --dry-run=client -o yaml | kubectl apply -f -
```

Restart Blackbox:

```bash
kubectl -n monitoring rollout restart deploy/blackbox-exporter
kubectl -n monitoring rollout status deploy/blackbox-exporter --timeout=120s
```

Restart Prometheus safely:

```bash
kubectl -n monitoring scale deploy/prometheus --replicas=0
kubectl -n monitoring wait --for=delete pod -l app=prometheus --timeout=120s
kubectl -n monitoring scale deploy/prometheus --replicas=1
kubectl -n monitoring rollout status deploy/prometheus --timeout=120s
```

Restart Grafana:

```bash
kubectl -n monitoring rollout restart deploy/grafana
kubectl -n monitoring rollout status deploy/grafana --timeout=120s
```

## Validation Before Deploy

Validate dashboard JSON:

```bash
for f in grafana/dashboards/*.json; do
  python3 -m json.tool "$f" >/tmp/$(basename "$f").ok
done
```

Validate Prometheus config with promtool if available:

```bash
promtool check config prometheus/prometheus.yml
```

If local `promtool` is not installed, use the Prometheus container image where
available:

```bash
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v2.54.1 \
  check config /etc/prometheus/prometheus.yml
```

## Validation After Deploy

Pods:

```bash
kubectl -n monitoring get pods -o wide
```

No Grafana provisioning errors:

```bash
kubectl -n monitoring logs deploy/grafana --since=5m \
  | grep -Ei 'failed to save dashboard|error' || true
```

OpenSpeedTest must be up:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=probe_success{job="server1-http",service="openspeedtest"}'
```

K3s pods must be visible by Kubernetes name:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=count(count by (namespace,pod) (container_last_seen{job="cadvisor",container!="",pod!="",namespace!=""}))'
```

K3s app DB containers must be visible:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=count(count by (namespace,pod,container,node) (container_last_seen{job="cadvisor",container=~"postgresql|database|db|redis|mysql|mariadb|valkey",namespace=~"authentik|immich|librenms|nextcloud"}))'
```

Local DB processes must be visible:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=sum(host_db_process_count)'
```

No down scrape targets:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=count(up == 0)'
```

## Grafana DB Conflict Recovery

Avoid dashboard UID changes. Grafana 11 stores dashboard state in both classic
dashboard tables and unified storage tables. A bad UID migration can create a
stale resource that appears as a duplicate provisioned dashboard.

Known bad symptom:

```text
failed to save dashboard ... unexpected number of dashboards for id 7. found: 2. desired: 1
found more than one provisioned dashboard with ID 7
```

Preferred prevention:

- Keep `docker-overview.json` UID as `docker-monitoring-overview`.
- Change dashboard title/content without changing UID.

Recovery requires a database backup first. Do not edit Grafana SQLite directly
unless the UI/API cannot delete the stale resource and the exact stale row is
known.

Backup paths used previously:

```text
/var/lib/grafana/grafana.db.backup-YYYYMMDD-HHMM
/home/thiraphat/Grafana-dashboard-setup-backups/
```

## Backup Rules

Do not keep generated backups inside tracked source paths.

Allowed backup locations:

```text
/home/thiraphat/Grafana-dashboard-setup-backups/
/tmp/
/var/lib/grafana/grafana.db.backup-YYYYMMDD-HHMM
```

Ignored backup patterns:

```text
grafana/dashboards.backup-*/
backups/
*.bak*
*.tmp
```

## Change Checklist

Before changing files:

1. Read this file.
2. Check `git status --short`.
3. Identify whether the change affects dashboards, Prometheus, Blackbox, or live
   Kubernetes workload arguments.
4. Avoid unrelated refactors.

Before deployment:

1. Validate all dashboard JSON files.
2. Check PromQL for changed panels against Prometheus.
3. Confirm Prometheus restart uses the safe scale-to-zero flow.

After deployment:

1. Confirm pods are running.
2. Confirm Grafana provisioning logs are clean.
3. Confirm OpenSpeedTest is up on `http://10.10.10.12:8090/`.
4. Confirm K3s container metrics expose `namespace`, `pod`, `container`, `node`.
5. Confirm local DB process metrics are present.
