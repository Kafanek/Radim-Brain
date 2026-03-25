#!/bin/bash
# ============================================
# RADIM BRAIN - Migrate DB from Heroku → NUC
# ============================================
# Spustit na NUC po instalaci Dockeru:
#   chmod +x migrate-from-heroku.sh
#   ./migrate-from-heroku.sh
# ============================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}  RADIM BRAIN — Migrace Heroku → NUC${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"

# ─── 1. Check prerequisites ───
echo -e "\n${YELLOW}[1/6] Kontrola předpokladů...${NC}"

command -v heroku >/dev/null 2>&1 || { echo -e "${RED}❌ Heroku CLI není nainstalováno. Nainstaluj: curl https://cli-assets.heroku.com/install.sh | sh${NC}"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo -e "${RED}❌ Docker není nainstalován.${NC}"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo -e "${RED}❌ Docker Compose není nainstalován.${NC}"; exit 1; }

echo -e "${GREEN}✅ Heroku CLI, Docker, Docker Compose OK${NC}"

# ─── 2. Check .env exists ───
echo -e "\n${YELLOW}[2/6] Kontrola .env souboru...${NC}"

if [ ! -f .env ]; then
    echo -e "${RED}❌ Soubor .env neexistuje! Zkopíruj z .env.example a vyplň:${NC}"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

source .env

if [ "${DB_PASSWORD}" = "CHANGE_ME_silne_heslo_min_20_znaku" ] || [ -z "${DB_PASSWORD}" ]; then
    echo -e "${RED}❌ Změň DB_PASSWORD v .env souboru!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ .env OK${NC}"

# ─── 3. Start PostgreSQL container ───
echo -e "\n${YELLOW}[3/6] Spouštím PostgreSQL...${NC}"

docker compose up -d db
echo "Čekám na PostgreSQL..."
sleep 5

# Wait for healthy
for i in {1..30}; do
    if docker compose exec db pg_isready -U radim -d radim_brain >/dev/null 2>&1; then
        echo -e "${GREEN}✅ PostgreSQL běží${NC}"
        break
    fi
    echo "  Čekám... ($i/30)"
    sleep 2
done

# ─── 4. Export from Heroku ───
echo -e "\n${YELLOW}[4/6] Exportuji data z Heroku...${NC}"

HEROKU_APP="radim-brain-2025"
DUMP_FILE="heroku_dump_$(date +%Y%m%d_%H%M%S).sql"

echo "  App: ${HEROKU_APP}"
echo "  Soubor: ${DUMP_FILE}"

# Get Heroku DATABASE_URL
HEROKU_DB_URL=$(heroku config:get DATABASE_URL -a ${HEROKU_APP})

if [ -z "${HEROKU_DB_URL}" ]; then
    echo -e "${RED}❌ Nelze získat DATABASE_URL z Heroku. Jsi přihlášen? (heroku login)${NC}"
    exit 1
fi

echo "  Stahuji dump..."
# Use pg_dump with Heroku URL (--data-only: keep init-db.sql schema + triggers)
pg_dump "${HEROKU_DB_URL}" \
    --no-owner \
    --no-privileges \
    --no-acl \
    --data-only \
    --format=plain \
    > "${DUMP_FILE}"

DUMP_SIZE=$(du -h "${DUMP_FILE}" | cut -f1)
echo -e "${GREEN}✅ Dump hotov: ${DUMP_FILE} (${DUMP_SIZE})${NC}"

# ─── 5. Import to NUC PostgreSQL ───
echo -e "\n${YELLOW}[5/6] Importuji do NUC PostgreSQL...${NC}"

# Copy dump into container and import
docker cp "${DUMP_FILE}" radim-db:/tmp/heroku_dump.sql
docker compose exec -T db psql -U radim -d radim_brain -f /tmp/heroku_dump.sql 2>&1 | tail -10

# Re-apply init-db.sql triggers (in case migration overwrote them)
echo "  Re-applying triggers from init-db.sql..."
docker compose exec -T db psql -U radim -d radim_brain -f /docker-entrypoint-initdb.d/01-init.sql 2>&1 | tail -5

echo -e "${GREEN}✅ Import dokončen${NC}"

# ─── 6. Verify ───
echo -e "\n${YELLOW}[6/6] Verifikace...${NC}"

echo "  Tabulky:"
docker compose exec db psql -U radim -d radim_brain -c "\dt" 2>/dev/null | grep -E "public|rows"

echo ""
echo "  Počty řádků:"
for table in memory_profiles memory_history memory_learning education_progress users; do
    COUNT=$(docker compose exec db psql -U radim -d radim_brain -t -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null | tr -d ' ' || echo "N/A")
    echo "    ${table}: ${COUNT} řádků"
done

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ MIGRACE DOKONČENA${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "Další kroky:"
echo "  1. docker compose up -d          # Spustí celý stack"
echo "  2. curl http://localhost:8000/health  # Test"
echo "  3. ./setup-cloudflare.sh          # Cloudflare Tunnel"
echo ""
echo "Dump zálohován: ${DUMP_FILE}"
