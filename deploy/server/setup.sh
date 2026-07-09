#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  ATLAS — Production Server Setup
#  Run ONCE as root on a fresh Ubuntu 22.04 / 24.04 server.
#  After this script finishes, all future deploys are fully automated via
#  GitHub Actions — you never need to SSH in again for routine deployments.
#
#  Usage:
#    sudo bash setup.sh
#
#  Optional env vars:
#    SSH_PUBKEY   — Your GitHub Actions SSH public key (paste it or set as env)
#    DOMAIN       — Your domain name (enables Certbot TLS setup)
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
APP_PORT=2847                          # External port for the ATLAS API
DEPLOY_USER="deploy"                   # Dedicated low-privilege deploy user
DEPLOY_DIR="/opt/atlas"                # Where compose files and .env live
SSH_PUBKEY="${SSH_PUBKEY:-}"           # GitHub Actions public key (set or prompted)
DOMAIN="${DOMAIN:-}"                   # Optional: your domain for TLS

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $*${NC}"; }
fail()  { echo -e "${RED}  ✗ $*${NC}"; exit 1; }

[[ "${EUID}" -eq 0 ]] || fail "Run as root: sudo bash setup.sh"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 1 — System Update"
# ══════════════════════════════════════════════════════════════════════════════
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  curl wget git ca-certificates gnupg \
  ufw fail2ban unzip net-tools
ok "System packages updated"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 2 — Docker Engine"
# ══════════════════════════════════════════════════════════════════════════════
if command -v docker &>/dev/null; then
  ok "Docker already installed: $(docker --version)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  ok "Docker installed: $(docker --version)"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "Step 3 — Deploy User"
# ══════════════════════════════════════════════════════════════════════════════
if id "${DEPLOY_USER}" &>/dev/null; then
  ok "User '${DEPLOY_USER}' already exists"
else
  useradd -r -m -s /bin/bash -d "/home/${DEPLOY_USER}" "${DEPLOY_USER}"
  ok "User '${DEPLOY_USER}' created"
fi
usermod -aG docker "${DEPLOY_USER}"
ok "User '${DEPLOY_USER}' added to docker group (no sudo needed to run docker)"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 4 — Deploy Directory"
# ══════════════════════════════════════════════════════════════════════════════
mkdir -p "${DEPLOY_DIR}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_DIR}"
chmod 750 "${DEPLOY_DIR}"
ok "Deploy directory: ${DEPLOY_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 5 — .env File (secrets template)"
# ══════════════════════════════════════════════════════════════════════════════
ENV_FILE="${DEPLOY_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  ok ".env already exists — NOT overwriting (your secrets are safe)"
else
  cat > "${ENV_FILE}" <<'ENVEOF'
# ─── ATLAS Production Environment ─────────────────────────────────────────────
# Fill in every CHANGE_ME value before the first deploy.
# Permissions: chmod 600 /opt/atlas/.env

# Injected automatically by GitHub Actions on each deploy — do not change
IMAGE_TAG=latest
REGISTRY=ghcr.io
GITHUB_REPOSITORY=your-org/trading-platform

# App
APP_NAME=atlas
ENV=production
LOG_LEVEL=INFO
SECRET_KEY=CHANGE_ME_AT_LEAST_32_RANDOM_CHARS

# API
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=https://app.atlas.example.com

# MT5 Bridge
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=9000
BRIDGE_AUTH_TOKEN=CHANGE_ME_BRIDGE_TOKEN
BRIDGE_HEARTBEAT_TIMEOUT_SECONDS=30

# Database
POSTGRES_USER=atlas
POSTGRES_PASSWORD=CHANGE_ME_STRONG_DB_PASSWORD
POSTGRES_DB=atlas
DATABASE_URL=postgresql+asyncpg://atlas:CHANGE_ME_STRONG_DB_PASSWORD@postgres:5432/atlas

# Redis
REDIS_PASSWORD=
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# AI / LLM (optional)
LLM_PROVIDER=none
# LLM_API_KEY=

# Observability
PROMETHEUS_METRICS_PORT=9090
GRAFANA_PASSWORD=CHANGE_ME_GRAFANA_PASSWORD

# Notifications (optional)
# TELEGRAM_BOT_TOKEN=
# DISCORD_WEBHOOK_URL=
ENVEOF
  chown "${DEPLOY_USER}:${DEPLOY_USER}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  ok ".env template created at ${ENV_FILE}"
  warn "ACTION REQUIRED: Fill in all CHANGE_ME values in ${ENV_FILE}"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "Step 6 — SSH Security Hardening (keeping port 22)"
# ══════════════════════════════════════════════════════════════════════════════
SSHD_CONFIG="/etc/ssh/sshd_config"
cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak.$(date +%Y%m%d)" 2>/dev/null || true

# Security hardening — SSH stays on port 22
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "${SSHD_CONFIG}"
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' "${SSHD_CONFIG}"
sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 5/' "${SSHD_CONFIG}"

sshd -t && systemctl restart ssh
ok "SSH staying on port 22, pubkey auth enforced"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 7 — SSH Authorized Key for GitHub Actions"
# ══════════════════════════════════════════════════════════════════════════════
SSH_DIR="/home/${DEPLOY_USER}/.ssh"
AUTH_KEYS="${SSH_DIR}/authorized_keys"
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"
touch "${AUTH_KEYS}"
chmod 600 "${AUTH_KEYS}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${SSH_DIR}"

if [[ -n "${SSH_PUBKEY}" ]]; then
  if grep -qF "${SSH_PUBKEY}" "${AUTH_KEYS}" 2>/dev/null; then
    ok "SSH public key already present in authorized_keys"
  else
    echo "${SSH_PUBKEY}" >> "${AUTH_KEYS}"
    ok "SSH public key added to ${AUTH_KEYS}"
  fi
else
  warn "SSH_PUBKEY not set. Add your GitHub Actions public key after setup:"
  warn "  ssh-keygen -t ed25519 -C 'github-actions-atlas' -f ~/.ssh/atlas_deploy"
  warn "  ssh-copy-id -i ~/.ssh/atlas_deploy.pub deploy@<server-ip>"
  warn "  Then paste the private key as SSH_PRIVATE_KEY in GitHub Secrets."
fi

# ══════════════════════════════════════════════════════════════════════════════
step "Step 8 — Firewall (UFW)"
# ══════════════════════════════════════════════════════════════════════════════
apt-get install -y -qq ufw
ufw --force reset > /dev/null
ufw default deny incoming
ufw default allow outgoing

ufw allow 22/tcp             comment "SSH"
ufw allow 80/tcp             comment "HTTP"
ufw allow 443/tcp            comment "HTTPS"
ufw allow "${APP_PORT}/tcp" comment "ATLAS API"

ufw --force enable
ok "Firewall enabled:"
ok "  - Port 22/tcp        (SSH)"
ok "  - Port 80/tcp        (HTTP)"
ok "  - Port 443/tcp       (HTTPS)"
ok "  - Port ${APP_PORT}/tcp  (ATLAS API)"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 9 — Fail2Ban (brute-force protection)"
# ══════════════════════════════════════════════════════════════════════════════
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled  = true
port     = 22
logpath  = /var/log/auth.log
maxretry = 3
EOF
systemctl enable --now fail2ban
ok "Fail2Ban configured (SSH port 22, ban after 3 failed attempts)"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 10 — Docker Log Rotation"
# ══════════════════════════════════════════════════════════════════════════════
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
EOF
systemctl reload docker 2>/dev/null || systemctl restart docker
ok "Docker log rotation configured (50MB × 5 files per container)"

# ══════════════════════════════════════════════════════════════════════════════
step "Step 11 — Certbot / Let's Encrypt (optional)"
# ══════════════════════════════════════════════════════════════════════════════
if [[ -n "${DOMAIN}" ]]; then
  snap install --classic certbot 2>/dev/null || true
  ln -sf /snap/bin/certbot /usr/bin/certbot 2>/dev/null || true
  ok "Certbot installed. Run after DNS is pointed here:"
  ok "  certbot certonly --standalone -d ${DOMAIN}"
else
  warn "DOMAIN not set — skipping Certbot. To set up TLS later:"
  warn "  sudo DOMAIN=api.example.com bash setup.sh"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ── Summary ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
SERVER_IP=$(curl -4s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         ATLAS Server Setup Complete!                      ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Server IP   : ${CYAN}${SERVER_IP}${NC}"
echo -e "  SSH port    : ${CYAN}22${NC}  (standard)"
echo -e "  App port    : ${CYAN}${APP_PORT}${NC}  (ATLAS API external port)"
echo -e "  Deploy dir  : ${CYAN}${DEPLOY_DIR}${NC}"
echo -e "  Deploy user : ${CYAN}${DEPLOY_USER}${NC}"
echo ""
echo -e "${YELLOW}════ NEXT STEPS ════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}1. Fill in your secrets${NC} in ${DEPLOY_DIR}/.env:"
echo "   nano ${DEPLOY_DIR}/.env"
echo ""
echo -e "${YELLOW}2. Generate an SSH key pair${NC} on your LOCAL machine:"
echo "   ssh-keygen -t ed25519 -C 'github-actions-atlas' -f ~/.ssh/atlas_deploy"
echo "   ssh-copy-id -i ~/.ssh/atlas_deploy.pub deploy@${SERVER_IP}"
echo ""
echo -e "${YELLOW}3. Add these secrets${NC} in GitHub → Settings → Secrets → Actions:"
echo "   SSH_HOST          = ${SERVER_IP}"
echo "   SSH_USER          = ${DEPLOY_USER}"
echo "   SSH_PORT          = 22"
echo "   SSH_PRIVATE_KEY   = <contents of ~/.ssh/atlas_deploy>"
echo "   GHCR_TOKEN        = <GitHub PAT with read:packages>"
echo "   PRODUCTION_URL    = http://${SERVER_IP}:${APP_PORT}"
echo "   HEALTH_URL        = http://${SERVER_IP}:${APP_PORT}/health/live"
echo ""
echo -e "${YELLOW}4. Create a GitHub Environment${NC} named 'production':"
echo "   GitHub → Settings → Environments → New environment → production"
echo ""
echo -e "${YELLOW}5. Test your SSH connection${NC}:"
echo "   ssh deploy@${SERVER_IP}"
echo ""
echo -e "${YELLOW}6. Push to main${NC} to trigger your first deploy!"
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
