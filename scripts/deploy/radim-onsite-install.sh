#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
# 🏠 radim-onsite-install.sh
# ════════════════════════════════════════════════════════════════════
# Provisions a senior's NUC (already running HAOS) with everything
# needed for Radim integration:
#
#   1. Verify HA is reachable on this machine
#   2. Install cloudflared + create per-senior named tunnel
#   3. Wire tunnel to systemd, enable on boot
#   4. Copy custom_components/radim/ into HA config
#   5. Restart HA (so the custom component loads)
#   6. Generate long-lived access token via HA REST
#   7. POST {ha_url, ha_token, label} to Radim backend → user_ha_homes
#   8. Smoke test: hit /api/ha/status, verify 200
#
# Run on the senior's NUC (or via SSH from technician's laptop).
# Requires: bash 4+, curl, jq, sudo, internet access.
#
# Usage:
#   ./radim-onsite-install.sh \
#     --senior-uuid abc123 \
#     --senior-label "Babiččin byt — Brno" \
#     --radim-base https://radim-brain-2025-be1cd52b04dc.herokuapp.com \
#     --radim-token <admin-or-senior-jwt> \
#     --cf-account <cloudflare-account-id> \
#     --cf-zone radimcare.cz
#
# Idempotent: safe to re-run (skip steps that already done).
# Logs: /var/log/radim-install-<timestamp>.log
# ════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── 0. Constants & arg parsing ─────────────────────────────────────

SCRIPT_VERSION="1.0.0"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/radim-install-${TIMESTAMP}.log"
HA_CONFIG_DIR="${HA_CONFIG_DIR:-/usr/share/hassio/homeassistant}"
HA_LOCAL_URL="${HA_LOCAL_URL:-http://localhost:8123}"
RADIM_REPO_DIR="${RADIM_REPO_DIR:-/opt/radim}"

# Color output (only if terminal supports it)
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; RESET=""
fi

log()    { echo "${BLUE}[$(date '+%H:%M:%S')]${RESET} $*" | tee -a "$LOG_FILE"; }
ok()     { echo "${GREEN}✓${RESET} $*" | tee -a "$LOG_FILE"; }
warn()   { echo "${YELLOW}⚠${RESET} $*" | tee -a "$LOG_FILE"; }
fail()   { echo "${RED}✗ $*${RESET}" | tee -a "$LOG_FILE" >&2; exit 1; }

usage() {
    cat <<EOF
${BOLD}radim-onsite-install.sh v${SCRIPT_VERSION}${RESET}

Usage:
  $0 --senior-uuid <uuid> \\
      --senior-label "<readable name>" \\
      --radim-base <url> \\
      --radim-token <jwt> \\
      [--cf-account <id>] [--cf-zone <domain>] \\
      [--ha-config-dir <path>] [--skip-tunnel] [--dry-run]

Required:
  --senior-uuid    Senior's user_id in Radim DB (UUID)
  --senior-label   Friendly name for the home (shown in Radim UI)
  --radim-base     Radim backend base URL (https://...)
  --radim-token    JWT for the senior account (or admin token with senior context)

Optional:
  --cf-account     Cloudflare Account ID (for tunnel creation)
  --cf-zone        Cloudflare zone (e.g. radimcare.cz)
  --ha-config-dir  HA config dir (default: $HA_CONFIG_DIR)
  --skip-tunnel    Skip Cloudflare Tunnel setup (LAN-only deploy)
  --dry-run        Show what would happen, don't change anything

Logs: $LOG_FILE
EOF
    exit 1
}

# Parse args
SENIOR_UUID=""; SENIOR_LABEL=""; RADIM_BASE=""; RADIM_TOKEN=""
CF_ACCOUNT=""; CF_ZONE=""; SKIP_TUNNEL=0; DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --senior-uuid)   SENIOR_UUID="$2"; shift 2 ;;
        --senior-label)  SENIOR_LABEL="$2"; shift 2 ;;
        --radim-base)    RADIM_BASE="$2"; shift 2 ;;
        --radim-token)   RADIM_TOKEN="$2"; shift 2 ;;
        --cf-account)    CF_ACCOUNT="$2"; shift 2 ;;
        --cf-zone)       CF_ZONE="$2"; shift 2 ;;
        --ha-config-dir) HA_CONFIG_DIR="$2"; shift 2 ;;
        --skip-tunnel)   SKIP_TUNNEL=1; shift ;;
        --dry-run)       DRY_RUN=1; shift ;;
        -h|--help)       usage ;;
        *)               warn "Unknown arg: $1"; usage ;;
    esac
done

[[ -z "$SENIOR_UUID" ]] && fail "--senior-uuid required"
[[ -z "$SENIOR_LABEL" ]] && fail "--senior-label required"
[[ -z "$RADIM_BASE" ]] && fail "--radim-base required"
[[ -z "$RADIM_TOKEN" ]] && fail "--radim-token required"

# Slugify label for tunnel name (e.g. "Babiččin byt — Brno" → "babiccin-byt-brno")
SENIOR_SLUG=$(echo "$SENIOR_LABEL" \
    | iconv -f utf-8 -t ascii//TRANSLIT 2>/dev/null \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9]\+/-/g; s/^-\|-$//g' \
    | cut -c1-32)
TUNNEL_NAME="radim-ha-${SENIOR_SLUG}"
TUNNEL_HOSTNAME="${TUNNEL_NAME}.${CF_ZONE:-radim.cf-tunnel.local}"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$HOME/radim-install-${TIMESTAMP}.log"

log "${BOLD}═══════════════════════════════════════════════════════════${RESET}"
log "${BOLD}🏠 Radim onsite install — v${SCRIPT_VERSION}${RESET}"
log "${BOLD}═══════════════════════════════════════════════════════════${RESET}"
log "Senior:        $SENIOR_LABEL  ($SENIOR_UUID)"
log "Tunnel name:   $TUNNEL_NAME"
log "Tunnel host:   $TUNNEL_HOSTNAME"
log "Radim base:    $RADIM_BASE"
log "HA config dir: $HA_CONFIG_DIR"
log "Dry run:       $([[ $DRY_RUN -eq 1 ]] && echo yes || echo no)"
log "Skip tunnel:   $([[ $SKIP_TUNNEL -eq 1 ]] && echo yes || echo no)"
log ""

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        log "[dry-run] $*"
    else
        eval "$@"
    fi
}

# ─── 1. Verify HA is reachable ──────────────────────────────────────

log "${BOLD}1/8${RESET} Checking Home Assistant on $HA_LOCAL_URL…"
if curl -sf -o /dev/null --max-time 5 "$HA_LOCAL_URL"; then
    ok "HA UI reachable"
else
    fail "HA not reachable on $HA_LOCAL_URL — is it running?"
fi

# ─── 2. Install cloudflared (skipped if --skip-tunnel) ──────────────

if [[ $SKIP_TUNNEL -eq 0 ]]; then
    log "${BOLD}2/8${RESET} Installing cloudflared…"
    if ! command -v cloudflared >/dev/null 2>&1; then
        run "curl -fsSL https://pkg.cloudflare.com/install.sh | sudo bash"
        run "sudo apt-get update -y && sudo apt-get install -y cloudflared"
        ok "cloudflared installed: $(cloudflared --version 2>&1 | head -1)"
    else
        ok "cloudflared already installed: $(cloudflared --version 2>&1 | head -1)"
    fi
else
    warn "Skipping cloudflared install (--skip-tunnel)"
fi

# ─── 3. Cloudflare Tunnel: login + create + route ──────────────────

if [[ $SKIP_TUNNEL -eq 0 ]]; then
    log "${BOLD}3/8${RESET} Setting up Cloudflare Tunnel '$TUNNEL_NAME'…"
    if [[ ! -f /root/.cloudflared/cert.pem && ! -f "$HOME/.cloudflared/cert.pem" ]]; then
        warn "cloudflared not yet logged in — opening browser for auth…"
        run "cloudflared tunnel login"
    fi

    # Check if tunnel exists
    EXISTING=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$2 == n {print $1}' | head -1 || echo "")
    if [[ -n "$EXISTING" ]]; then
        ok "Tunnel '$TUNNEL_NAME' already exists (id: $EXISTING)"
        TUNNEL_UUID="$EXISTING"
    else
        log "Creating tunnel '$TUNNEL_NAME'…"
        run "cloudflared tunnel create $TUNNEL_NAME"
        TUNNEL_UUID=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$2 == n {print $1}' | head -1)
        ok "Tunnel created: $TUNNEL_UUID"
    fi

    # Route DNS (CNAME → tunnel)
    if [[ -n "$CF_ZONE" ]]; then
        log "Routing DNS: $TUNNEL_HOSTNAME → tunnel"
        run "cloudflared tunnel route dns $TUNNEL_NAME $TUNNEL_HOSTNAME || true"
    fi

    # Write config.yml
    CFG_DIR="/etc/cloudflared"
    run "sudo mkdir -p $CFG_DIR"
    run "sudo tee $CFG_DIR/config.yml > /dev/null <<EOF
# Radim per-senior tunnel — auto-generated by radim-onsite-install.sh
# Senior: $SENIOR_LABEL
tunnel: $TUNNEL_UUID
credentials-file: $CFG_DIR/${TUNNEL_UUID}.json

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://localhost:8123
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF"

    # Move credentials file (cloudflared puts it in ~/.cloudflared/)
    if [[ -f "$HOME/.cloudflared/${TUNNEL_UUID}.json" ]]; then
        run "sudo cp $HOME/.cloudflared/${TUNNEL_UUID}.json $CFG_DIR/"
    fi

    # Install systemd service
    run "sudo cloudflared service install || true"
    run "sudo systemctl enable cloudflared"
    run "sudo systemctl restart cloudflared"
    sleep 3
    if systemctl is-active --quiet cloudflared; then
        ok "cloudflared service running, tunnel up"
    else
        warn "cloudflared service not active — check: journalctl -u cloudflared"
    fi

    HA_PUBLIC_URL="https://$TUNNEL_HOSTNAME"
else
    HA_PUBLIC_URL="$HA_LOCAL_URL"
    warn "Using LAN URL (not exposed): $HA_PUBLIC_URL"
fi

# ─── 4. Copy custom_components/radim into HA ────────────────────────

log "${BOLD}4/8${RESET} Installing custom_components/radim…"
RADIM_CC_SRC=""
for candidate in \
    "$RADIM_REPO_DIR/custom_components/radim" \
    "$(dirname "$0")/../../custom_components/radim" \
    "$HOME/Desktop/001-TEST/HomeAssistant/config/custom_components/radim"; do
    if [[ -d "$candidate" ]]; then
        RADIM_CC_SRC="$candidate"
        break
    fi
done

if [[ -z "$RADIM_CC_SRC" ]]; then
    warn "custom_components/radim source not found — skipping (clone Radim repo into $RADIM_REPO_DIR first)"
else
    DEST="$HA_CONFIG_DIR/custom_components/radim"
    run "mkdir -p $HA_CONFIG_DIR/custom_components"
    run "rsync -a --delete $RADIM_CC_SRC/ $DEST/"
    ok "Copied $RADIM_CC_SRC → $DEST"
fi

# ─── 5. Restart HA so custom component loads ────────────────────────

log "${BOLD}5/8${RESET} Restarting Home Assistant (so radim component loads)…"
if command -v ha >/dev/null 2>&1; then
    run "ha core restart"
elif systemctl list-units --type=service --quiet | grep -q home-assistant; then
    run "sudo systemctl restart home-assistant@homeassistant"
else
    warn "Don't know how to restart HA on this system. Restart manually."
fi
log "Waiting 30s for HA to come back up…"
sleep 30

# Wait for /api/ to be 200
for i in 1 2 3 4 5 6 7 8 9 10; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$HA_LOCAL_URL/api/" || echo "000")
    if [[ "$code" == "401" || "$code" == "200" ]]; then
        ok "HA back online (HTTP $code on /api/)"
        break
    fi
    log "  retry $i/10 (HTTP $code)…"
    sleep 5
done

# ─── 6. Generate long-lived access token ────────────────────────────

log "${BOLD}6/8${RESET} Generating HA long-lived access token…"
warn "HA's REST API doesn't expose token creation programmatically (security)."
warn "Open in browser: $HA_LOCAL_URL/profile/security"
warn "Click: 'Create Token' → name: 'Radim-${SENIOR_SLUG}' → copy"
read -rp "Paste long-lived token here: " HA_TOKEN
[[ -z "$HA_TOKEN" ]] && fail "No token provided — aborting"

# Verify token works
log "Verifying token against HA…"
HA_VERSION=$(curl -sf -H "Authorization: Bearer $HA_TOKEN" "$HA_LOCAL_URL/api/config" \
    | jq -r '.version' 2>/dev/null || echo "")
if [[ -z "$HA_VERSION" || "$HA_VERSION" == "null" ]]; then
    fail "Token rejected by HA — check that you copied the full string"
fi
ok "Token valid; HA version: $HA_VERSION"

# ─── 7. Register the home in Radim backend ──────────────────────────

log "${BOLD}7/8${RESET} Registering home in Radim backend…"
PAYLOAD=$(jq -nc \
    --arg label "$SENIOR_LABEL" \
    --arg url "$HA_PUBLIC_URL" \
    --arg token "$HA_TOKEN" \
    '{label: $label, ha_url: $url, ha_token: $token, is_default: true, test: true}')

REGISTER_RESPONSE=$(curl -sf -X POST "$RADIM_BASE/api/ha/config" \
    -H "Authorization: Bearer $RADIM_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" 2>&1 || echo "ERR")

if [[ "$REGISTER_RESPONSE" == "ERR" || -z "$REGISTER_RESPONSE" ]]; then
    fail "Failed to POST /api/ha/config — check RADIM_TOKEN + RADIM_BASE"
fi

HOME_ID=$(echo "$REGISTER_RESPONSE" | jq -r '.home.home_id' 2>/dev/null || echo "")
WEBHOOK_SECRET=$(echo "$REGISTER_RESPONSE" | jq -r '.home.ha_webhook_secret' 2>/dev/null || echo "")

if [[ -z "$HOME_ID" || "$HOME_ID" == "null" ]]; then
    fail "Backend response malformed: $REGISTER_RESPONSE"
fi
ok "Home registered: home_id=$HOME_ID"
ok "Webhook secret: ${WEBHOOK_SECRET:0:8}…  (full secret saved in $LOG_FILE)"

# ─── 8. Smoke test: hit /api/ha/status as the senior ────────────────

log "${BOLD}8/8${RESET} Smoke test /api/ha/status as the senior…"
STATUS=$(curl -sf "$RADIM_BASE/api/ha/status" \
    -H "Authorization: Bearer $RADIM_TOKEN" 2>/dev/null || echo "{}")
CONNECTED=$(echo "$STATUS" | jq -r '.connected' 2>/dev/null || echo "false")
if [[ "$CONNECTED" == "true" ]]; then
    ok "Radim → HA pipeline alive end-to-end ✅"
else
    warn "Status: $STATUS"
    warn "Backend can't reach HA via the registered URL. Check tunnel."
fi

# ─── Done ───────────────────────────────────────────────────────────

log ""
log "${BOLD}═══════════════════════════════════════════════════════════${RESET}"
ok "${BOLD}DONE — Radim install complete for $SENIOR_LABEL${RESET}"
log "${BOLD}═══════════════════════════════════════════════════════════${RESET}"
log ""
log "Next steps:"
log "  1. Tell the senior to open Radim app → Settings → Domácnost"
log "  2. They (or you) walk through ➕ Přidat zařízení wizard"
log "  3. Pair Tapo Hub first, then sub-devices, then bulb, then BT speaker"
log "  4. For Tapo HA dashboard: $HA_PUBLIC_URL"
log "  5. Logs: $LOG_FILE"
log ""
log "${BOLD}Webhook URL${RESET} (for HA-side automations):"
log "  POST $RADIM_BASE/api/ha/webhook/$HOME_ID"
log "  Header: X-HA-Secret: $WEBHOOK_SECRET"
log ""
