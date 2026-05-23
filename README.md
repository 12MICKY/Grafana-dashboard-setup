# Grafana Dashboard Setup

Production-ready Grafana and Prometheus monitoring stack for a Docker Swarm homelab. The repository contains the stack definition, Prometheus scrape configuration, alert rules, Grafana provisioning files, Grafana dashboard JSON files, and custom exporters used by the running monitoring environment.

This repository is designed to be safe for a public GitHub repository. Runtime secrets are kept out of Git and must be supplied through a local `.env` file.

## Current Production Context

The stack is currently used on the homelab server at `10.33.1.34` with Docker Swarm stack name `monitoring`.

Main access points:

- Grafana local URL: `http://10.33.1.34:3001`
- Prometheus local URL: `http://10.33.1.34:9090`
- Example Grafana dashboard URL: `http://10.33.1.34:3001/d/local-services-overview/local-services-overview`
- Optional public Grafana URL: `https://grafana.thiraphat.work`

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
           +----------------------------+----------------------------+
           |                            |                            |
           v                            v                            v
+---------------------+      +---------------------+      +---------------------+
| node-exporter       |      | blackbox-exporter   |      | custom exporters    |
| host metrics        |      | HTTP/DNS probes     |      | Docker + DB status  |
+---------------------+      +---------------------+      +---------------------+
           |
           v
+---------------------+
| Docker Swarm nodes  |
| services, hosts, DB |
+---------------------+
```

Grafana does not store dashboard definitions manually in the UI as the source of truth. Dashboards and the Prometheus datasource are provisioned from files in this repository.

## Repository Layout

```text
.
├── swarm-stack.yml
├── docker-compose.yml
├── .env.example
├── .gitignore
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── blackbox/
│   └── blackbox.yml
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml
│   │   └── dashboards/dashboards.yml
│   └── dashboards/
├── docker-exporter/
│   └── docker_exporter.py
├── host-db-exporter/
│   └── host_db_exporter.py
├── postgres-host-exporter/
└── unifi-lxc-exporter/
```

## File Responsibilities

| Path | Purpose |
| --- | --- |
| `swarm-stack.yml` | Main Docker Swarm deployment file for the production monitoring stack. |
| `docker-compose.yml` | Standalone Compose file for local/lab usage. The Swarm file is the production target. |
| `.env.example` | Public-safe environment template. Copy this to `.env` and fill real values locally. |
| `prometheus/prometheus.yml` | Prometheus scrape jobs, service discovery, blackbox probe targets, and rule file reference. |
| `prometheus/alerts.yml` | Prometheus alert rules. |
| `blackbox/blackbox.yml` | Blackbox exporter probe modules, including HTTP and DNS probes. |
| `grafana/provisioning/datasources/prometheus.yml` | Automatically creates the Grafana Prometheus datasource. |
| `grafana/provisioning/dashboards/dashboards.yml` | Automatically loads dashboard JSON files into Grafana. |
| `grafana/dashboards/*.json` | Dashboard source-of-truth files. |
| `docker-exporter/docker_exporter.py` | Custom exporter for Docker Swarm service/container metrics. |
| `host-db-exporter/host_db_exporter.py` | Custom exporter for host database process metrics. |
| `postgres-host-exporter/*` | Optional systemd files and exporter script for PostgreSQL host-level metrics. |
| `unifi-lxc-exporter/*` | Optional systemd files and exporter script for UniFi LXC metrics. |

## Services

`swarm-stack.yml` deploys the following services under stack name `monitoring`.

| Service | Mode | Purpose | Port |
| --- | --- | --- | --- |
| `grafana` | replicated | Dashboard UI, datasource provisioning, dashboard provisioning, optional OAuth login. | `3001 -> 3000` |
| `prometheus` | replicated | Time-series database, scrape scheduler, alert rule evaluator. | `9090 -> 9090` |
| `node-exporter` | global | Host-level CPU, memory, disk, filesystem, and node metrics on every Swarm node. | internal `9100` |
| `cadvisor` | replicated | Container-level resource metrics. | internal `8080` |
| `blackbox-exporter` | replicated | HTTP and DNS checks for internal services. | internal `9115` |
| `docker-exporter` | global | Custom Docker service/container status metrics on every Swarm node. | internal `9101` |
| `host-db-exporter` | global | Custom database process status metrics on every Swarm node. | internal `9102` |

## Grafana Dashboards

Dashboards are automatically loaded from `grafana/dashboards/*.json` into the Grafana folder named `Homelab`.

| File | Dashboard Title | UID |
| --- | --- | --- |
| `homelab-overview.json` | `01 Overview` | `homelab-overview` |
| `proxmox-home.json` | `02 Proxmox` | `proxmox-home` |
| `docker-overview.json` | `03 Docker` | `docker-monitoring-overview` |
| `server1-services-overview.json` | `04 Server1` | `server1-services-overview` |
| `db-overview.json` | `05 DB` | `db-servers-overview` |
| `postgres-host-overview.json` | `06 PostgreSQL` | `postgres-host-overview` |
| `unifi-lxc-overview.json` | `07 UniFi` | `unifi-lxc-overview` |
| `home-server-overview.json` | `08 Home DNS` | `home-server-overview` |
| `local-services-overview.json` | `09 Local Services` | `local-services-overview` |

## Prerequisites

- Docker Engine with Swarm mode enabled.
- Docker Compose plugin or Docker CLI with `docker stack` support.
- A manager node that can run `docker stack deploy`.
- Network access from Prometheus to all configured scrape targets.
- Optional: Authentik or another OAuth provider if OAuth login is enabled.

Check Swarm status:

```bash
docker node ls
```

If Swarm is not initialized yet:

```bash
docker swarm init
```

## Environment Variables

Create a local `.env` file from the public-safe example.

```bash
cp .env.example .env
nano .env
```

Example:

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=CHANGEME
GRAFANA_ROOT_URL=https://grafana.example.com
GRAFANA_OAUTH_CLIENT_ID=grafana
GRAFANA_OAUTH_CLIENT_SECRET=CHANGEME
```

Do not commit `.env`. It is intentionally ignored by `.gitignore`.

## Deployment

Clone the repository:

```bash
git clone https://github.com/12MICKY/Grafana-dashboard-setup.git
cd Grafana-dashboard-setup
```

Load environment variables:

```bash
set -a
. ./.env
set +a
```

Deploy the stack:

```bash
docker stack deploy -c swarm-stack.yml monitoring
```

## Validation Before Deploy

Validate Prometheus configuration and alert rules:

```bash
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v2.54.1 \
  check config /etc/prometheus/prometheus.yml
```

Render the Swarm stack:

```bash
set -a
. ./.env
set +a
docker stack config -c swarm-stack.yml >/tmp/monitoring-stack-rendered.yml
```

Validate all Grafana dashboard JSON files:

```bash
for f in grafana/dashboards/*.json; do
  python3 -m json.tool "$f" >/tmp/$(basename "$f").ok
done
```

## Runtime Checks

List stack services:

```bash
docker service ls --filter label=com.docker.stack.namespace=monitoring
```

Inspect stack tasks:

```bash
docker stack ps monitoring --no-trunc
```

Check Grafana health:

```bash
curl -s http://127.0.0.1:3001/api/health
```

Expected result:

```json
{
  "database": "ok",
  "version": "11.2.2"
}
```

Check Prometheus active targets:

```bash
curl -s http://127.0.0.1:9090/api/v1/targets?state=active
```

## Viewing Dashboards in Grafana

1. Open `http://10.33.1.34:3001` or the configured public Grafana URL.
2. Log in with the local admin account from `.env`, or use OAuth if configured.
3. Open `Dashboards`.
4. Open the `Homelab` folder.
5. Select a dashboard such as `01 Overview`, `03 Docker`, or `09 Local Services`.

The datasource named `Prometheus` is automatically provisioned and points to `http://prometheus:9090` inside the Docker network.

## Prometheus Scrape Design

The Prometheus configuration combines several target types:

- Docker DNS service discovery for Swarm tasks such as `docker-exporter` and `host-db-exporter`.
- Static targets for hosts, Proxmox, UniFi, DNS, and HTTP services.
- Blackbox exporter probe targets for HTTP and DNS availability checks.
- Node exporter targets for host resource metrics.

This keeps infrastructure metrics, service health, and application-level availability checks in one Prometheus instance.

## Docker Swarm Config Versioning

Docker Swarm configs are immutable. If a file-backed config changes, Swarm cannot update the existing config object in place. You may see an error like this:

```text
only updates to Labels are allowed
```

Files mounted as Swarm configs:

- `prometheus/prometheus.yml`
- `prometheus/alerts.yml`
- `blackbox/blackbox.yml`
- `docker-exporter/docker_exporter.py`
- `host-db-exporter/host_db_exporter.py`

When changing one of these files, bump the corresponding config name in `swarm-stack.yml`.

Example:

```yaml
services:
  prometheus:
    configs:
      - source: prometheus_config_v2
        target: /etc/prometheus/prometheus.yml

configs:
  prometheus_config_v2:
    file: ./prometheus/prometheus.yml
```

The `source:` name used by the service and the name in the top-level `configs:` section must match.

## Updating Dashboards

Dashboard JSON files are mounted into Grafana from `grafana/dashboards`. Grafana provisioning is configured with:

```yaml
allowUiUpdates: true
updateIntervalSeconds: 30
```

Recommended workflow:

1. Edit a dashboard in Grafana UI.
2. Export the dashboard JSON.
3. Replace the matching file in `grafana/dashboards/`.
4. Commit the JSON change.
5. Redeploy or restart Grafana if needed.

## Troubleshooting

Check service logs:

```bash
docker service logs monitoring_grafana --tail 100
docker service logs monitoring_prometheus --tail 100
docker service logs monitoring_blackbox-exporter --tail 100
```

Check why a service is not running:

```bash
docker service ps monitoring_grafana --no-trunc
```

Check Prometheus config inside a container:

```bash
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v2.54.1 \
  check config /etc/prometheus/prometheus.yml
```

Common issues:

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Grafana starts but dashboards are missing | Provisioning path or mount is wrong | Check `grafana/provisioning/dashboards/dashboards.yml` and stack volume mounts. |
| Prometheus service keeps restarting | Invalid Prometheus config or alert rule | Run `promtool check config`. |
| `docker stack deploy` fails on config update | Swarm config name was reused after file content changed | Bump config names in `swarm-stack.yml`. |
| Prometheus targets are down | Target address, network route, or exporter service is unavailable | Check `/api/v1/targets`, service logs, and network reachability. |
| OAuth login fails | Root URL, callback URL, client ID, or client secret mismatch | Check Grafana OAuth environment variables and Authentik provider settings. |

## Security Notes

This is a public repository. Never commit:

- `.env`
- OAuth client secrets
- Grafana admin passwords
- GitHub tokens
- private keys
- Grafana database backups
- backup files containing runtime values

Before pushing, run a quick scan:

```bash
grep -RInE 'password|secret|token|api_key|private_key|BEGIN .*PRIVATE' --exclude-dir=.git .
```

The scan may report placeholder text in documentation. Review matches before pushing.

## Current Verification Snapshot

The stack has been verified with:

```bash
docker service ls --filter label=com.docker.stack.namespace=monitoring
curl -s http://127.0.0.1:3001/api/health
```

Expected running services:

```text
monitoring_blackbox-exporter   1/1
monitoring_cadvisor            1/1
monitoring_docker-exporter     3/3
monitoring_grafana             1/1
monitoring_host-db-exporter    3/3
monitoring_node-exporter       3/3
monitoring_prometheus          1/1
```

## License

No license is currently specified. Add a license file before distributing or reusing this project broadly.
