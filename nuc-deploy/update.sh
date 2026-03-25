#!/bin/bash
# ============================================
# RADIM BRAIN — Quick Update (nový kód → rebuild)
# ============================================
# Spustit po scp nových souborů:
#   ./update.sh
# ============================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

APP_DIR="/opt/radim"
cd "${APP_DIR}"

echo -e "${BLUE}🔄 Radim Brain — Update${NC}"

# 1. Backup DB before update
echo -e "${YELLOW}[1/4] Záloha DB...${NC}"
./backup.sh

# 2. Rebuild container
echo -e "${YELLOW}[2/4] Rebuild...${NC}"
docker compose build radim-brain --no-cache

# 3. Restart (kratky vypadek ~5-10s)
echo -e "${YELLOW}[3/4] Restart...${NC}"
docker compose up -d radim-brain

# 4. Health check
echo -e "${YELLOW}[4/4] Health check...${NC}"
sleep 5

for i in {1..10}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health --max-time 5 2>/dev/null || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo -e "${GREEN}✅ Update dokončen — Radim Brain běží${NC}"

        # Show version info
        curl -s http://localhost:8000/health 2>/dev/null | python3 -m json.tool 2>/dev/null | head -10
        exit 0
    fi
    echo "  Čekám na start... (${i}/10)"
    sleep 3
done

echo -e "${YELLOW}⚠️ Health check timeout — kontroluj logy:${NC}"
echo "  docker compose logs --tail 50 radim-brain"
