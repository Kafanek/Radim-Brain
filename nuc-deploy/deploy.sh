#!/bin/bash
# ╔═══════════════════════════════════════════════════════════╗
# ║  RADIM BRAIN — NUC Deploy Script                         ║
# ║  Kompletní instalace: OS → Docker → App → SSL → Test     ║
# ╚═══════════════════════════════════════════════════════════╝
#
# POSTUP:
#   1. Nainstaluj Ubuntu Server 24.04 LTS na NUC
#   2. Přihlaš se přes SSH
#   3. Naklonuj tento adresář na NUC:
#        scp -r nuc-deploy/ user@nuc-ip:~/radim/
#   4. Spusť:
#        cd ~/radim
#        chmod +x deploy.sh migrate-from-heroku.sh setup-cloudflare.sh
#        sudo ./deploy.sh
#
# ════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║    🧠 RADIM BRAIN — NUC Deploy                           ║"
echo "║    v1.0 — $(date +%Y-%m-%d)                                     ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ═════════════════════════════════════════════
# STEP 1: System Updates & Prerequisites
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [1/8] Aktualizace systému ━━━${NC}"

apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git htop nano \
    ufw fail2ban \
    ca-certificates gnupg lsb-release \
    postgresql-client

echo -e "${GREEN}✅ Systém aktualizován${NC}"

# ═════════════════════════════════════════════
# STEP 2: Install Docker
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [2/8] Instalace Docker ━━━${NC}"

if ! command -v docker >/dev/null 2>&1; then
    # Official Docker install
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
        tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add current user to docker group
    SUDO_USER_NAME="${SUDO_USER:-$(whoami)}"
    if [ "${SUDO_USER_NAME}" != "root" ]; then
        usermod -aG docker "${SUDO_USER_NAME}"
    fi

    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}✅ Docker nainstalován${NC}"
else
    echo -e "${GREEN}✅ Docker už je nainstalován: $(docker --version)${NC}"
fi

# ═════════════════════════════════════════════
# STEP 3: Firewall (UFW)
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [3/8] Firewall (UFW) ━━━${NC}"

ufw --force reset >/dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp    # HTTP (redirect to HTTPS)
ufw allow 443/tcp   # HTTPS
# Port 8000 only from localhost (Docker internal)
ufw --force enable

echo -e "${GREEN}✅ Firewall: SSH(22), HTTP(80), HTTPS(443)${NC}"

# ═════════════════════════════════════════════
# STEP 4: Fail2ban (SSH brute-force protection)
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [4/8] Fail2ban ━━━${NC}"

cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200
EOF

systemctl enable fail2ban
systemctl restart fail2ban

echo -e "${GREEN}✅ Fail2ban: SSH ochrana aktivní (3 pokusy → ban 2h)${NC}"

# ═════════════════════════════════════════════
# STEP 5: Create app directory structure
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [5/8] Adresářová struktura ━━━${NC}"

APP_DIR="/opt/radim"
mkdir -p "${APP_DIR}"/{app,certs,certbot-webroot,logs,backups}

# Copy deploy files
cp "${DEPLOY_DIR}/docker-compose.yml" "${APP_DIR}/"
cp "${DEPLOY_DIR}/Dockerfile" "${APP_DIR}/"
cp "${DEPLOY_DIR}/nginx.conf" "${APP_DIR}/"
cp "${DEPLOY_DIR}/init-db.sql" "${APP_DIR}/"
cp "${DEPLOY_DIR}/migrate-from-heroku.sh" "${APP_DIR}/"
cp "${DEPLOY_DIR}/setup-cloudflare.sh" "${APP_DIR}/"
cp "${DEPLOY_DIR}/update.sh" "${APP_DIR}/"

# .dockerignore goes into app/ (Docker build context)
if [ -f "${DEPLOY_DIR}/.dockerignore" ]; then
    cp "${DEPLOY_DIR}/.dockerignore" "${APP_DIR}/.dockerignore"
fi

chmod +x "${APP_DIR}/migrate-from-heroku.sh"
chmod +x "${APP_DIR}/setup-cloudflare.sh"
chmod +x "${APP_DIR}/update.sh"

# Copy .env if exists, otherwise create from example
if [ -f "${DEPLOY_DIR}/.env" ]; then
    cp "${DEPLOY_DIR}/.env" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    echo "  .env zkopírován"
elif [ -f "${DEPLOY_DIR}/.env.example" ]; then
    cp "${DEPLOY_DIR}/.env.example" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    echo -e "${YELLOW}  ⚠️ .env vytvořen z .env.example — VYPLŇ HODNOTY!${NC}"
fi

echo -e "${GREEN}✅ ${APP_DIR}/ připraven${NC}"

# ═════════════════════════════════════════════
# STEP 6: Clone application code
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [6/8] Stažení aplikačního kódu ━━━${NC}"

REPO_URL="https://github.com/Kafanek/radim-frontend.git"
BACKEND_BRANCH="heroku-deploy-fix"

# Clone or update backend
if [ -d "${APP_DIR}/app/.git" ]; then
    cd "${APP_DIR}/app"
    git fetch origin
    git checkout "${BACKEND_BRANCH}"
    git pull origin "${BACKEND_BRANCH}"
    echo "  Backend aktualizován"
else
    # Clone from the Heroku branch which has the backend code
    echo "  Klonuji backend (branch: ${BACKEND_BRANCH})..."
    echo -e "${YELLOW}  POZNÁMKA: Pokud backend repo je jiné, uprav REPO_URL v deploy.sh${NC}"

    # For now, we'll create a placeholder — user will copy the code
    if [ ! -f "${APP_DIR}/app/app.py" ]; then
        echo -e "${YELLOW}  ⚠️ Backend kód nenalezen v ${APP_DIR}/app/${NC}"
        echo "  Zkopíruj backend ručně:"
        echo "    scp -r /Users/kolibric/Desktop/Kolibri\\ app./*.py user@nuc:${APP_DIR}/app/"
        echo "    scp -r /Users/kolibric/Desktop/Kolibri\\ app./requirements.txt user@nuc:${APP_DIR}/app/"
        echo "    scp -r /Users/kolibric/Desktop/Kolibri\\ app./api/ user@nuc:${APP_DIR}/app/"
        echo "    scp -r /Users/kolibric/Desktop/Kolibri\\ app./core/ user@nuc:${APP_DIR}/app/"
    fi
fi

echo -e "${GREEN}✅ Aplikační kód připraven${NC}"

# ═════════════════════════════════════════════
# STEP 7: Daily backup cron
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [7/8] Automatické zálohy ━━━${NC}"

# Create backup script
cat > "${APP_DIR}/backup.sh" << 'BACKUP_EOF'
#!/bin/bash
# Radim Brain — Daily DB Backup
BACKUP_DIR="/opt/radim/backups"
KEEP_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/radim_brain_${TIMESTAMP}.sql.gz"

# Dump and compress
docker compose -f /opt/radim/docker-compose.yml exec -T db \
    pg_dump -U radim radim_brain | gzip > "${BACKUP_FILE}"

# Check success
if [ -s "${BACKUP_FILE}" ]; then
    echo "[$(date)] ✅ Backup: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"
else
    echo "[$(date)] ❌ Backup failed!"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Delete old backups
find "${BACKUP_DIR}" -name "*.sql.gz" -mtime +${KEEP_DAYS} -delete
echo "[$(date)] Cleaned backups older than ${KEEP_DAYS} days"
BACKUP_EOF

chmod +x "${APP_DIR}/backup.sh"

# Add cron job (daily at 3 AM)
CRON_LINE="0 3 * * * ${APP_DIR}/backup.sh >> ${APP_DIR}/logs/backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup.sh"; echo "${CRON_LINE}") | crontab -

echo -e "${GREEN}✅ Denní zálohy DB v 03:00 (30 dní historie)${NC}"

# ═════════════════════════════════════════════
# STEP 8: System monitoring
# ═════════════════════════════════════════════

echo -e "\n${BLUE}━━━ [8/8] Monitoring ━━━${NC}"

# Create simple health check script
cat > "${APP_DIR}/healthcheck.sh" << 'HC_EOF'
#!/bin/bash
# Radim Brain — Health Check
URL="http://localhost:8000/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "${URL}" --max-time 10 2>/dev/null)

if [ "${RESPONSE}" = "200" ]; then
    echo "[$(date)] ✅ Radim Brain: OK"
else
    echo "[$(date)] ❌ Radim Brain: DOWN (HTTP ${RESPONSE})"
    # Auto-restart
    cd /opt/radim && docker compose restart radim-brain
    echo "[$(date)] 🔄 Auto-restart triggered"

    # TODO: Sem přidej notifikaci (email, Telegram, webhook)
fi
HC_EOF

chmod +x "${APP_DIR}/healthcheck.sh"

# Health check every 5 min
HC_CRON="*/5 * * * * ${APP_DIR}/healthcheck.sh >> ${APP_DIR}/logs/healthcheck.log 2>&1"
(crontab -l 2>/dev/null | grep -v "healthcheck.sh"; echo "${HC_CRON}") | crontab -

echo -e "${GREEN}✅ Health check každých 5 min s auto-restart${NC}"

# ═════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                                                           ║${NC}"
echo -e "${CYAN}║    ${GREEN}✅ NUC PŘIPRAVEN${CYAN}                                     ║${NC}"
echo -e "${CYAN}║                                                           ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}DALŠÍ KROKY:${NC}"
echo ""
echo "  1. ${CYAN}Vyplň .env:${NC}"
echo "     cd /opt/radim"
echo "     nano .env"
echo ""
echo "  2. ${CYAN}Zkopíruj backend kód na NUC:${NC}"
echo "     scp -r '/Users/kolibric/Desktop/Kolibri app./'*.py user@NUC_IP:/opt/radim/app/"
echo "     scp '/Users/kolibric/Desktop/Kolibri app./requirements.txt' user@NUC_IP:/opt/radim/app/"
echo "     scp -r '/Users/kolibric/Desktop/Kolibri app./api' user@NUC_IP:/opt/radim/app/"
echo "     scp -r '/Users/kolibric/Desktop/Kolibri app./core' user@NUC_IP:/opt/radim/app/"
echo ""
echo "  3. ${CYAN}Migruj DB z Heroku:${NC}"
echo "     cd /opt/radim"
echo "     ./migrate-from-heroku.sh"
echo ""
echo "  4. ${CYAN}Spusť aplikaci:${NC}"
echo "     docker compose up -d"
echo "     docker compose logs -f radim-brain"
echo ""
echo "  5. ${CYAN}Nastav Cloudflare Tunnel:${NC}"
echo "     ./setup-cloudflare.sh"
echo ""
echo "  6. ${CYAN}Otestuj:${NC}"
echo "     curl http://localhost:8000/health"
echo "     curl https://brain.radimcare.cz/health"
echo ""
echo "  7. ${CYAN}Přesměruj frontend:${NC}"
echo "     V index.html změň BACKEND_URL na https://brain.radimcare.cz"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Adresář:  /opt/radim/"
echo -e "  Logy:     /opt/radim/logs/"
echo -e "  Zálohy:   /opt/radim/backups/"
echo -e "  Config:   /opt/radim/.env"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
