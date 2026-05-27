# Mandatory Operator Instructions

Before changing anything in this repository or on the live monitoring stack, read
`MONITORING_CONFIG.md` completely.

Do not use `README.md` as the operational source of truth. `README.md` is only a
human overview. `MONITORING_CONFIG.md` is the required config/runbook for
implementation work.

Hard rules:

- Production is K3s, not Docker Swarm.
- Do not run `docker stack deploy`.
- Do not recreate Prometheus with a rolling update while another Prometheus pod
  is still using the same hostPath TSDB.
- Do not change Grafana dashboard UIDs unless the Grafana database state is
  intentionally migrated.
- Do not store passwords, OAuth client secrets, kubeconfig contents, or private
  tokens in this repository.
