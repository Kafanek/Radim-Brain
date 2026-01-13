#!/bin/bash
# ============================================
# RADIM BRAIN - SET ENVIRONMENT VARIABLES
# ============================================
# Spusť: chmod +x setup_env.sh && ./setup_env.sh

APP_NAME="radim-brain-2025"

echo "⚙️  Nastavení Environment Variables pro Radim Brain v3.0"
echo "=========================================================="
echo ""

# Funkce pro bezpečné zadání hodnoty
set_var() {
    VAR_NAME=$1
    DESCRIPTION=$2
    CURRENT=$(heroku config:get $VAR_NAME -a $APP_NAME 2>/dev/null || echo "")
    
    echo ""
    echo "📝 $VAR_NAME"
    echo "   $DESCRIPTION"
    
    if [ -n "$CURRENT" ]; then
        echo "   Aktuální: ${CURRENT:0:20}..."
        read -p "   Přepsat? (y/N): " OVERWRITE
        if [ "$OVERWRITE" != "y" ] && [ "$OVERWRITE" != "Y" ]; then
            echo "   ⏭️  Přeskočeno"
            return
        fi
    fi
    
    read -p "   Nová hodnota (nebo Enter pro přeskočení): " VALUE
    
    if [ -n "$VALUE" ]; then
        heroku config:set $VAR_NAME="$VALUE" -a $APP_NAME
        echo "   ✅ Nastaveno"
    else
        echo "   ⏭️  Přeskočeno"
    fi
}

echo "=== POVINNÉ ==="

set_var "AZURE_SPEECH_KEY" "Azure Speech Services API klíč (pro TTS/STT)"
set_var "AZURE_SPEECH_REGION" "Azure region (default: westeurope)"

echo ""
echo "=== RADIM AI (pro automatické odpovědi) ==="

set_var "GEMINI_API_KEY" "Google Gemini API klíč (primární AI)"
set_var "ANTHROPIC_API_KEY" "Claude API klíč (fallback AI)"

echo ""
echo "=== MEDIA UPLOAD (Cloudinary) ==="

set_var "CLOUDINARY_CLOUD_NAME" "Cloudinary cloud name"
set_var "CLOUDINARY_API_KEY" "Cloudinary API key"
set_var "CLOUDINARY_API_SECRET" "Cloudinary API secret"

echo ""
echo "=== WORDPRESS INTEGRACE ==="

set_var "WP_URL" "WordPress URL (např. https://dev.kafanek.com)"
set_var "WP_USER" "WordPress admin username"
set_var "WP_APP_PASSWORD" "WordPress Application Password"

echo ""
echo "=== PUSH NOTIFIKACE (VAPID) ==="
echo "   Generuj klíče: npx web-push generate-vapid-keys"

set_var "VAPID_PUBLIC_KEY" "VAPID public key"
set_var "VAPID_PRIVATE_KEY" "VAPID private key"
set_var "VAPID_EMAIL" "Kontaktní email (mailto:...)"

echo ""
echo "=========================================================="
echo "✅ Hotovo!"
echo ""
echo "Aktuální konfigurace:"
heroku config -a $APP_NAME
echo ""
echo "Restartuj aplikaci: heroku restart -a $APP_NAME"
