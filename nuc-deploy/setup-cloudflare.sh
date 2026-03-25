#!/bin/bash
# ============================================
# RADIM BRAIN - Cloudflare Tunnel Setup
# ============================================
# Bezpečnější než port forwarding:
# - Žádný otevřený port na routeru
# - DDoS ochrana zdarma
# - Automatický SSL
# ============================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TUNNEL_NAME="radim-brain"
DOMAIN="brain.radimcare.cz"

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}  RADIM BRAIN — Cloudflare Tunnel${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"

# ─── 1. Install cloudflared ───
echo -e "\n${YELLOW}[1/5] Instalace cloudflared...${NC}"

if ! command -v cloudflared >/dev/null 2>&1; then
    # Detect architecture
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    elif [ "$ARCH" = "aarch64" ]; then
        CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
    else
        echo -e "${RED}❌ Nepodporovaná architektura: $ARCH${NC}"
        exit 1
    fi

    wget -q "${CLOUDFLARED_URL}" -O /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
fi

echo -e "${GREEN}✅ cloudflared $(cloudflared --version | head -1)${NC}"

# ─── 2. Login to Cloudflare ───
echo -e "\n${YELLOW}[2/5] Přihlášení do Cloudflare...${NC}"
echo "Otevře se prohlížeč — přihlaš se a vyber doménu radimcare.cz"

cloudflared tunnel login

echo -e "${GREEN}✅ Přihlášen${NC}"

# ─── 3. Create tunnel ───
echo -e "\n${YELLOW}[3/5] Vytvářím tunnel '${TUNNEL_NAME}'...${NC}"

# Check if tunnel already exists
if cloudflared tunnel list | grep -q "${TUNNEL_NAME}"; then
    echo "  Tunnel '${TUNNEL_NAME}' už existuje"
    TUNNEL_ID=$(cloudflared tunnel list | grep "${TUNNEL_NAME}" | awk '{print $1}')
else
    cloudflared tunnel create "${TUNNEL_NAME}"
    TUNNEL_ID=$(cloudflared tunnel list | grep "${TUNNEL_NAME}" | awk '{print $1}')
fi

echo -e "${GREEN}✅ Tunnel ID: ${TUNNEL_ID}${NC}"

# ─── 4. Configure DNS ───
echo -e "\n${YELLOW}[4/5] Nastavuji DNS (${DOMAIN} → tunnel)...${NC}"

cloudflared tunnel route dns "${TUNNEL_NAME}" "${DOMAIN}" 2>/dev/null || echo "  DNS záznam už existuje"

echo -e "${GREEN}✅ ${DOMAIN} → Cloudflare Tunnel${NC}"

# ─── 5. Create config and systemd service ───
echo -e "\n${YELLOW}[5/5] Vytvářím konfiguraci a systemd service...${NC}"

# Config file
sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml > /dev/null << CFEOF
tunnel: ${TUNNEL_ID}
credentials-file: /root/.cloudflared/${TUNNEL_ID}.json

ingress:
  # Radim Brain API
  - hostname: ${DOMAIN}
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false

  # Catch-all (required by cloudflared)
  - service: http_status:404
CFEOF

echo "  Config: /etc/cloudflared/config.yml"

# Install as systemd service
sudo cloudflared service install 2>/dev/null || echo "  Service už nainstalován"
sudo systemctl enable cloudflared
sudo systemctl restart cloudflared

# Verify
sleep 3
if sudo systemctl is-active cloudflared >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Cloudflare Tunnel běží jako systemd service${NC}"
else
    echo -e "${RED}⚠️ Tunnel se nespustil — zkontroluj: sudo journalctl -u cloudflared -n 20${NC}"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CLOUDFLARE TUNNEL NASTAVEN${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "  URL:    https://${DOMAIN}"
echo "  Status: sudo systemctl status cloudflared"
echo "  Logy:   sudo journalctl -u cloudflared -f"
echo ""
echo "  Test:   curl https://${DOMAIN}/health"
echo ""
echo -e "${YELLOW}POZNÁMKA: S Cloudflare Tunnel nepotřebuješ Nginx!${NC}"
echo "  Můžeš vypnout nginx container v docker-compose.yml"
echo "  (Cloudflare řeší SSL, DDoS ochranu i rate limiting)"
