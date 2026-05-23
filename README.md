# Grafana Dashboard Setup

ชุดไฟล์สำหรับรัน Grafana + Prometheus monitoring บน Docker Swarm พร้อม dashboard ที่ provision เข้า Grafana อัตโนมัติ

ระบบนี้ถูกใช้งานจริงกับ homelab/server `10.33.1.34` และออกแบบให้เก็บไฟล์ config ทั้งหมดไว้ใน GitHub ได้ โดยไม่ commit secret จริง เช่น `.env`, OAuth secret, password หรือ backup database

## สิ่งที่อยู่ใน repo

```text
.
├── swarm-stack.yml                         # Docker Swarm stack หลักที่ใช้ deploy production
├── docker-compose.yml                      # compose แบบ standalone สำหรับ lab/local test
├── .env.example                            # template environment variables, ไม่มี secret จริง
├── prometheus/
│   ├── prometheus.yml                      # scrape jobs, targets, blackbox probe config
│   └── alerts.yml                          # Prometheus alert rules
├── blackbox/
│   └── blackbox.yml                        # blackbox-exporter probe modules
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml      # auto-create Prometheus datasource
│   │   └── dashboards/dashboards.yml       # auto-load dashboards from JSON files
│   └── dashboards/                         # Grafana dashboard JSON files
├── docker-exporter/docker_exporter.py      # custom Docker Swarm/container metrics exporter
├── host-db-exporter/host_db_exporter.py    # custom DB process metrics exporter
├── postgres-host-exporter/                 # optional host-level PostgreSQL exporter service files
└── unifi-lxc-exporter/                     # optional UniFi LXC exporter service files
```

## Services ที่ deploy ใน Docker Swarm

`swarm-stack.yml` จะสร้าง stack ชื่อ `monitoring` และ services เหล่านี้

| Service | หน้าที่ | Port |
| --- | --- | --- |
| `grafana` | แสดง dashboard และ login ผ่าน local admin/OAuth | `3001 -> 3000` |
| `prometheus` | เก็บ metrics และ evaluate alert rules | `9090 -> 9090` |
| `node-exporter` | host metrics ของทุก Swarm node | internal `9100` |
| `cadvisor` | container resource metrics | internal `8080` |
| `blackbox-exporter` | probe HTTP/DNS services | internal `9115` |
| `docker-exporter` | custom Docker service/container status metrics | internal `9101` |
| `host-db-exporter` | custom database process status metrics | internal `9102` |

## Dashboards ใน Grafana

Grafana จะ provision dashboard จาก `grafana/dashboards/*.json` เข้า folder `Homelab` อัตโนมัติ

| File | Dashboard title | UID |
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

หลัง deploy แล้วเข้า Grafana ได้ที่

- Local: `http://10.33.1.34:3001`
- Domain ถ้าตั้ง reverse proxy/OAuth แล้ว: `https://grafana.thiraphat.work`
- ตัวอย่าง dashboard: `http://10.33.1.34:3001/d/local-services-overview/local-services-overview`

## วิธี deploy บน Docker Swarm

1. Clone repo

```bash
git clone https://github.com/12MICKY/Grafana-dashboard-setup.git
cd Grafana-dashboard-setup
```

2. สร้าง `.env` จากตัวอย่าง แล้วแก้ค่า secret จริง

```bash
cp .env.example .env
nano .env
```

ตัวอย่างค่าที่ต้องตั้ง

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=CHANGEME
GRAFANA_ROOT_URL=https://grafana.example.com
GRAFANA_OAUTH_CLIENT_ID=grafana
GRAFANA_OAUTH_CLIENT_SECRET=CHANGEME
```

3. Validate config ก่อน deploy

```bash
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v2.54.1 \
  check config /etc/prometheus/prometheus.yml

set -a
. ./.env
set +a
docker stack config -c swarm-stack.yml >/tmp/monitoring-stack-rendered.yml

for f in grafana/dashboards/*.json; do
  python3 -m json.tool "$f" >/tmp/$(basename "$f").ok
done
```

4. Deploy

```bash
set -a
. ./.env
set +a
docker stack deploy -c swarm-stack.yml monitoring
```

5. ตรวจสถานะหลัง deploy

```bash
docker service ls --filter label=com.docker.stack.namespace=monitoring
docker stack ps monitoring --no-trunc
curl -s http://127.0.0.1:3001/api/health
curl -s http://127.0.0.1:9090/api/v1/targets?state=active
```

## วิธีดูใน Grafana

1. เปิด `http://10.33.1.34:3001`
2. Login ด้วย user/password จาก `.env` หรือ OAuth ถ้าตั้ง Authentik แล้ว
3. ไปที่ `Dashboards` -> folder `Homelab`
4. เปิด dashboard ที่ต้องการ เช่น
   - `01 Overview` สำหรับภาพรวมทั้งหมด
   - `03 Docker` สำหรับ service/container status
   - `09 Local Services` สำหรับ HTTP/DNS service checks

Datasource ชื่อ `Prometheus` จะถูกสร้างอัตโนมัติจาก `grafana/provisioning/datasources/prometheus.yml` และชี้ไปที่ `http://prometheus:9090` ภายใน Docker network

## หมายเหตุเรื่อง Docker Swarm configs

Docker Swarm config เป็น immutable ถ้าแก้ไฟล์เหล่านี้แล้ว deploy ทับ stack เดิม อาจเจอ error ว่า `only updates to Labels are allowed`

ไฟล์ที่เป็น Swarm config ใน repo นี้คือ

- `prometheus/prometheus.yml`
- `prometheus/alerts.yml`
- `blackbox/blackbox.yml`
- `docker-exporter/docker_exporter.py`
- `host-db-exporter/host_db_exporter.py`

ถ้าแก้ไฟล์เหล่านี้ ให้ bump ชื่อ config ใน `swarm-stack.yml` เช่น

```yaml
configs:
  prometheus_config_v2:
    file: ./prometheus/prometheus.yml
```

และแก้ `source:` ของ service ให้ตรงกันด้วย

## Public repo safety

ไฟล์ที่ไม่ควร commit

- `.env`
- backup files เช่น `*.bak*`
- Grafana database backup
- token/password/OAuth client secret จริง

repo นี้มี `.gitignore` กันไฟล์เหล่านี้ไว้แล้ว แต่ควร scan ก่อน push ทุกครั้ง

```bash
grep -RInE 'password|secret|token|api_key|private_key|BEGIN .*PRIVATE' --exclude-dir=.git .
```
