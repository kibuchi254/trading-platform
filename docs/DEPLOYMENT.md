# ATLAS — Deployment Guide

This guide covers local development, single-VM production (Docker Compose), and Kubernetes deployment.

## Prerequisites

### Local Development
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (fast Python package manager)
- Docker + Docker Compose
- PostgreSQL 16+ (or use the Docker service)
- Redis 7+ (or use the Docker service)

### Production
- Ubuntu 22.04 LTS (existing infrastructure)
- Docker + Docker Compose
- WineHQ Stable + MetaTrader 5 (existing infrastructure)
- 4 CPU cores / 8 GB RAM minimum (16 GB recommended)
- 100 GB SSD for PostgreSQL + tick storage

## Quick Start (Local Development)

```bash
# 1. Clone or extract the source
unzip atlas-trading-platform.zip
cd trading-platform/

# 2. Install dependencies
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.13
uv pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY, BRIDGE_AUTH_TOKEN to random strings

# 4. Start infrastructure services
docker compose -f docker/docker-compose.yml up -d postgres redis

# 5. Run database migrations
alembic upgrade head

# 6. Start the API (terminal 1)
uvicorn platform.main:app --reload --port 8000

# 7. Start the Bridge Service (terminal 2)
python -m platform.bridge.server --port 9000

# 8. Start the Celery worker (terminal 3)
celery -A platform.infrastructure.celery_app worker -l info

# 9. Start Celery Beat for periodic tasks (terminal 4)
celery -A platform.infrastructure.celery_app beat -l info

# 10. Open API docs at http://localhost:8000/docs
```

## Single-VM Production (Docker Compose)

The included `docker/docker-compose.yml` is production-ready for a single VM.

```bash
# 1. Copy and edit environment
cp .env.example .env.production
# Set all secrets, set ENV=production

# 2. Pull and start all services
docker compose --env-file .env.production up -d

# 3. Run migrations
docker compose exec api alembic upgrade head

# 4. Verify
curl http://localhost/health
curl http://localhost/health/detailed
```

### Service Topology

| Service | Port | Purpose |
|---------|------|---------|
| nginx | 80, 443 | Edge — TLS, routing, rate limit |
| api | 8000 (internal) | FastAPI REST + WebSocket |
| bridge | 9000 (internal) | MT5 terminal WebSocket server |
| worker | — | Celery background tasks |
| flower | 5555 | Celery monitoring |
| postgres | 5432 | Primary database |
| redis | 6379 | Cache + pubsub + Celery broker |
| prometheus | 9091 | Metrics scraper |
| grafana | 3000 | Dashboards |

### Logs

All services log to stdout in JSON format. Docker's logging driver captures them.

```bash
# View API logs
docker compose logs -f api

# View Bridge logs
docker compose logs -f bridge

# View worker logs
docker compose logs -f worker
```

For production log aggregation, configure Docker's logging driver to ship to Loki, Elasticsearch, or Datadog.

## Kubernetes Deployment

### Prerequisites
- Kubernetes 1.28+
- kubectl configured
- cert-manager installed (for TLS)
- nginx-ingress controller
- A container registry (GHCR, ECR, GCR)

### Steps

```bash
# 1. Build and push images
docker build -t ghcr.io/yourorg/atlas-api:latest -f docker/backend.Dockerfile .
docker push ghcr.io/yourorg/atlas-api:latest

# 2. Edit the config and secrets
vim deploy/kubernetes/config.yaml
# Replace all CHANGE_ME values

# 3. Create namespace
kubectl apply -f deploy/kubernetes/namespace.yaml

# 4. Apply config + secrets
kubectl apply -f deploy/kubernetes/config.yaml

# 5. Apply API deployment (with HPA + PDB)
kubectl apply -f deploy/kubernetes/api.yaml

# 6. Apply Bridge StatefulSet (sticky sessions)
kubectl apply -f deploy/kubernetes/bridge.yaml

# 7. Apply ingress (TLS + WebSocket routing)
kubectl apply -f deploy/kubernetes/ingress.yaml

# 8. Run database migrations (one-shot)
kubectl run atlas-migrate --rm -it --restart=Never \
  --image=ghcr.io/yourorg/atlas-api:latest \
  --namespace=atlas \
  --env-from=secret/atlas-secrets \
  --env-from=configmap/atlas-config \
  --command -- alembic upgrade head

# 9. Verify
kubectl get pods -n atlas
kubectl get svc -n atlas
kubectl get ingress -n atlas
```

### Scaling

- **API**: HPA scales 3-20 pods based on CPU (70%) and memory (80%).
- **Bridge**: StatefulSet with 3 replicas, sticky sessions via ClientIP. Scale by increasing replicas.
- **Workers**: Deploy separate worker Deployments per queue (ticks, trades, backtest, notifications).

### Zero-Downtime Deployments

```bash
# Rolling update
kubectl set image deployment/atlas-api api=ghcr.io/yourorg/atlas-api:v1.2.3 -n atlas

# Monitor rollout
kubectl rollout status deployment/atlas-api -n atlas

# Rollback if needed
kubectl rollout undo deployment/atlas-api -n atlas
```

The API's `preStop` hook sleeps 10 seconds to drain in-flight requests. The Bridge's `preStop` sleeps 30 seconds to allow terminal reconnection to a healthy node.

## MT5 Terminal Setup

The MT5 Bridge EA (`mql5/BridgeEA.mq5`) runs inside MetaTrader 5 under Wine.

### Prerequisites
- WineHQ Stable installed
- MetaTrader 5 installed under Wine
- A broker account (Exness, ICMarkets, Pepperstone, etc.)

### Installation

1. Copy `BridgeEA.mq5` to the MT5 `MQL5/Experts/` directory
2. Compile the EA in MetaEditor (F7)
3. In MT5, attach the EA to any chart
4. Configure the EA inputs:
   - `InpBridgeUrl`: `ws://your-server:9000` (or `wss://your-server/bridge/` behind TLS)
   - `InpTerminalId`: a unique identifier, e.g. `mt5-exness-01`
   - `InpBroker`: broker name, e.g. `Exness`
   - `InpAuthToken`: must match `BRIDGE_AUTH_TOKEN` on the backend
   - `InpSymbolsCSV`: comma-separated symbols to stream
5. Enable "Allow Algorithmic Trading" in MT5 settings
6. The EA will connect, register, and start streaming ticks

### Verifying the Connection

```bash
# Check terminal is registered
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/terminals

# Force a position sync
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/terminals/mt5-exness-01/sync-positions
```

## Backup & Restore

### Automated Backups

Add to crontab:
```cron
0 2 * * * /opt/atlas/scripts/backup_db.sh >> /var/log/atlas/backup.log 2>&1
```

Backups are stored in `/var/backups/atlas/` (configurable via `ATLAS_BACKUP_DIR`). Set `S3_BACKUP_BUCKET` to also upload to S3.

### Restore

```bash
# Interactive restore (asks for confirmation)
./scripts/restore_db.sh /var/backups/atlas/atlas_20260709_020000.sql.gz
```

### Point-in-Time Recovery

PostgreSQL WAL archiving is recommended for PITR. Configure in `postgresql.conf`:
```ini
archive_mode = on
archive_command = 'aws s3 cp %p s3://your-wal-bucket/atlas-wal/%f'
```

## Disaster Recovery

### DR Drill

Run the DR drill quarterly in production, monthly in staging:
```bash
./scripts/dr_drill.sh production
```

The drill simulates: API crash, Bridge crash, Redis failure, DB backup, kill switch engagement.

### Multi-Region Failover

For multi-region deployments:
1. PostgreSQL: asynchronous streaming replication to standby region
2. Redis: ephemeral, rebuilt on failover
3. DNS: update to point at secondary region's load balancer
4. RPO: 1-5 seconds (replication lag)
5. RTO: 5-15 minutes (DNS TTL + promotion + cache warm-up)

## Monitoring

### Grafana Dashboards

Access Grafana at `http://localhost:3000` (admin/admin). Import the dashboards from `monitoring/grafana/`.

Key dashboards:
- **System Overview**: terminals online, requests/s, error rate, p99 latency
- **Bridge**: terminal count, command latency, command success rate
- **Trading**: orders placed, fills, P&L, open positions
- **Risk**: kill switch state, risk events, daily P&L
- **Infrastructure**: DB pool, Redis ops, Celery queue depth

### Alerting

Configure Prometheus alerting rules. Critical alerts:
- `atlas_bridge_terminals_online == 0` — no terminals connected
- `atlas_risk_decisions_total{decision="rejected"} / atlas_risk_decisions_total > 0.5` — risk rejection spike
- `up{job="atlas_api"} == 0` — API down
- `atlas_db_pool_in_use / atlas_db_pool_size > 0.8` — DB pool exhausted

## Troubleshooting

### Terminal won't connect
1. Check EA logs in MT5 Experts tab
2. Verify `InpBridgeUrl` is reachable from the MT5 host
3. Verify `InpAuthToken` matches `BRIDGE_AUTH_TOKEN`
4. Check Bridge logs: `docker compose logs bridge | grep mt5-exness-01`

### Orders not executing
1. Check terminal is online: `GET /api/v1/terminals/{id}`
2. Check risk engine isn't blocking: `GET /api/v1/risk/kill-switch`
3. Check Bridge command queue: `GET /api/v1/admin/status`
4. Check Bridge logs for command dispatch: `docker compose logs bridge | grep cmd.order`

### High latency
1. Check `atlas_http_request_duration_seconds` in Prometheus
2. Check DB pool usage: `atlas_db_pool_in_use`
3. Check Redis ops/s
4. Check Celery queue depth in Flower

### Database bloat
1. Run `VACUUM ANALYZE` on hot tables
2. Check `archive_old_ticks` task is running (daily at 2am)
3. Consider migrating `ticks` table to TimescaleDB hypertable
