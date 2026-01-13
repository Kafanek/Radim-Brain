#!/bin/bash
# ============================================
# RADIM BRAIN v3.0 - FULL DEPLOY SCRIPT
# ============================================

set -e

APP_NAME="radim-brain-2025"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "🚀 Deploying Radim Brain v3.0 to Heroku"
echo "=========================================="
echo ""

cd "$SCRIPT_DIR"

# Remove deprecated runtime.txt if exists
rm -f runtime.txt 2>/dev/null || true

# Git commit
echo "📦 Committing changes..."
git add -A
git commit -m "Radim Brain v3.0 - Full features (AI, Push, Media, WP, Admin)" 2>/dev/null || echo "   No new changes"

# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "📌 Branch: $CURRENT_BRANCH"

# Push to Heroku
echo "🚀 Pushing to Heroku..."
git push heroku ${CURRENT_BRANCH}:main --force

# Set environment variables (pokud ještě nejsou)
echo ""
echo "⚙️  Checking environment variables..."

# Check and prompt for missing vars
check_var() {
    VAR_NAME=$1
    CURRENT=$(heroku config:get $VAR_NAME -a $APP_NAME 2>/dev/null || echo "")
    if [ -z "$CURRENT" ]; then
        echo "   ⚠️  $VAR_NAME is not set"
        return 1
    else
        echo "   ✅ $VAR_NAME is set"
        return 0
    fi
}

echo ""
echo "Required variables:"
check_var "AZURE_SPEECH_KEY" || true
check_var "AZURE_SPEECH_REGION" || true

echo ""
echo "Optional variables (for full features):"
check_var "GEMINI_API_KEY" || true
check_var "CLOUDINARY_URL" || true
check_var "WP_URL" || true
check_var "WP_USER" || true
check_var "WP_APP_PASSWORD" || true
check_var "VAPID_PUBLIC_KEY" || true
check_var "VAPID_PRIVATE_KEY" || true

# Restart app
echo ""
echo "🔄 Restarting app..."
heroku restart -a $APP_NAME

# Wait and check health
echo ""
echo "⏳ Waiting for app to start..."
sleep 10

echo ""
echo "🏥 Health check..."
curl -s "https://${APP_NAME}.herokuapp.com/health" | python3 -m json.tool 2>/dev/null || echo "Health check failed"

echo ""
echo "=============================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=============================================="
echo ""
echo "🌐 URLs:"
echo "   API:       https://${APP_NAME}.herokuapp.com/api"
echo "   Health:    https://${APP_NAME}.herokuapp.com/health"
echo "   Admin:     https://${APP_NAME}.herokuapp.com/api/admin/stats"
echo ""
echo "📋 To set missing environment variables:"
echo "   heroku config:set GEMINI_API_KEY=your_key -a $APP_NAME"
echo "   heroku config:set CLOUDINARY_URL=cloudinary://... -a $APP_NAME"
echo ""
echo "📋 Commands:"
echo "   Logs:      heroku logs --tail -a $APP_NAME"
echo "   Restart:   heroku restart -a $APP_NAME"
echo "   Config:    heroku config -a $APP_NAME"
echo ""
