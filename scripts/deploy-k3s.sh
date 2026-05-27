#!/usr/bin/env sh
set -eu

NAMESPACE=${NAMESPACE:-monitoring}
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "==> validating repo before deploy"
scripts/validate.sh

echo "==> applying Prometheus ConfigMap"
kubectl -n "$NAMESPACE" create configmap prometheus-config \
  --from-file=prometheus.yml=prometheus/prometheus.yml \
  --from-file=alerts.yml=prometheus/alerts.yml \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> applying Blackbox ConfigMap"
kubectl -n "$NAMESPACE" create configmap blackbox-config \
  --from-file=blackbox.yml=blackbox/blackbox.yml \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> ensuring cAdvisor exports Kubernetes labels"
current_args=$(kubectl -n "$NAMESPACE" get ds cadvisor -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null || true)
case "$current_args" in
  *--store_container_labels=true*) ;;
  *--store_container_labels=false*)
    kubectl -n "$NAMESPACE" patch ds cadvisor --type=json \
      -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args/1","value":"--store_container_labels=true"}]'
    kubectl -n "$NAMESPACE" rollout status ds/cadvisor --timeout=120s
    ;;
  *)
    echo "WARNING: could not verify cAdvisor --store_container_labels=true; check DaemonSet manually" >&2
    ;;
esac

echo "==> restarting Blackbox exporter"
kubectl -n "$NAMESPACE" rollout restart deploy/blackbox-exporter
kubectl -n "$NAMESPACE" rollout status deploy/blackbox-exporter --timeout=120s

echo "==> restarting Prometheus with safe hostPath TSDB flow"
kubectl -n "$NAMESPACE" scale deploy/prometheus --replicas=0
kubectl -n "$NAMESPACE" wait --for=delete pod -l app=prometheus --timeout=120s
kubectl -n "$NAMESPACE" scale deploy/prometheus --replicas=1
kubectl -n "$NAMESPACE" rollout status deploy/prometheus --timeout=120s

echo "==> restarting Grafana"
kubectl -n "$NAMESPACE" rollout restart deploy/grafana
kubectl -n "$NAMESPACE" rollout status deploy/grafana --timeout=120s

echo "==> waiting for first scrape"
sleep "${SCRAPE_WAIT_SECONDS:-20}"

echo "==> running smoke test"
PROMETHEUS_URL=${PROMETHEUS_URL:-http://127.0.0.1:9090} scripts/smoke-test.sh

echo "deploy ok"
