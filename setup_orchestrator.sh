#!/bin/bash
# ============================================
# 🎭 RADIM ORCHESTRATOR - SETUP & BUILD
# ============================================
# Spusť: chmod +x setup_orchestrator.sh && ./setup_orchestrator.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP_DIR="$SCRIPT_DIR/mcp-server"
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

echo "╔═══════════════════════════════════════════════════╗"
echo "║  🎭 RADIM ORCHESTRATOR SETUP v2.0                ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ============================================
# 1. BUILD MCP SERVER
# ============================================
echo "📦 [1/4] Building MCP Server..."
cd "$MCP_DIR"

if [ ! -d "node_modules" ]; then
    echo "   Installing dependencies..."
    npm install 2>&1 | tail -1
fi

echo "   Compiling TypeScript..."
npm run build 2>&1 | tail -3

if [ -f "build/index.js" ]; then
    echo "   ✅ MCP Server built: $MCP_DIR/build/index.js"
else
    echo "   ❌ Build failed!"
    exit 1
fi

# ============================================
# 2. CONFIGURE CLAUDE DESKTOP
# ============================================
echo ""
echo "⚙️  [2/4] Configuring Claude Desktop..."

MCP_PATH="$MCP_DIR/build/index.js"

# Vytvoř config pokud neexistuje
if [ ! -f "$CLAUDE_CONFIG" ]; then
    mkdir -p "$(dirname "$CLAUDE_CONFIG")"
    echo '{}' > "$CLAUDE_CONFIG"
    echo "   Created new config file"
fi

# Zkontroluj jestli už je radim-orchestrator v configu
if grep -q "radim-orchestrator" "$CLAUDE_CONFIG" 2>/dev/null; then
    echo "   ⚠️  radim-orchestrator already in config - updating..."
fi

# Vytvoř nový config s orchestrátorem
python3 -c "
import json, sys

config_path = '$CLAUDE_CONFIG'
mcp_path = '$MCP_PATH'

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except:
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['radim-orchestrator'] = {
    'command': 'node',
    'args': [mcp_path],
    'env': {
        'RADIM_BRAIN_URL': 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com'
    }
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f'   ✅ Config updated: {len(config[\"mcpServers\"])} MCP servers')
for name in config['mcpServers']:
    print(f'      • {name}')
"

# ============================================
# 3. TEST HEROKU BACKEND
# ============================================
echo ""
echo "🔍 [3/4] Testing Heroku backend..."

HEROKU_URL="https://radim-brain-2025-be1cd52b04dc.herokuapp.com"

# Health check
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEROKU_URL/health" --max-time 10)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "   ✅ Heroku backend: healthy (HTTP $HTTP_STATUS)"
else
    echo "   ⚠️  Heroku backend: HTTP $HTTP_STATUS"
fi

# Orchestrator check
ORCH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEROKU_URL/api/orchestrator/health" --max-time 10)
if [ "$ORCH_STATUS" = "200" ]; then
    echo "   ✅ Orchestrator endpoint: available"
else
    echo "   ❌ Orchestrator endpoint: HTTP $ORCH_STATUS (needs deploy!)"
    echo ""
    echo "   ⚠️  Orchestrator routes nejsou na Heroku."
    echo "   Spusť deploy:"
    echo "   cd $SCRIPT_DIR && git add . && git commit -m 'feat: orchestrator v2.0' && git push heroku main"
fi

# ============================================
# 4. SUMMARY
# ============================================
echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  📋 SETUP COMPLETE                               ║"
echo "╠═══════════════════════════════════════════════════╣"
echo "║                                                   ║"
echo "║  MCP Server: $MCP_DIR/build/index.js"
echo "║  Claude Config: $CLAUDE_CONFIG"
echo "║                                                   ║"
echo "║  NEXT STEPS:                                      ║"
echo "║  1. Restart Claude Desktop                        ║"
echo "║  2. Deploy to Heroku (if orchestrator 404)        ║"
echo "║  3. Test: 'Orchestrate health_all'                ║"
echo "║                                                   ║"
echo "╚═══════════════════════════════════════════════════╝"

echo ""
echo "🎯 Deploy na Heroku:"
echo "   cd $SCRIPT_DIR"
echo "   git add orchestrator_blueprint.py app.py mcp-server/"
echo "   git commit -m 'feat: add orchestrator v2.0 with MCP integration'"
echo "   git push heroku main"
echo ""
