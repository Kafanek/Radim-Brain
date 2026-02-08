# ============================================
# 🎭 RADIM ORCHESTRATOR BLUEPRINT (Flask)
# ============================================
# Version: 2.0.0
# Orchestrace celého Radim Brain systému
# Integrace do app.py jako Flask Blueprint

from flask import Blueprint, request, jsonify
import requests
import json
import os
from datetime import datetime
import time
import concurrent.futures

orchestrator_bp = Blueprint('orchestrator', __name__)

# ============================================
# KONFIGURACE
# ============================================
HEROKU_URL = os.environ.get('HEROKU_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def safe_get(url, timeout=10):
    """Bezpečný GET request"""
    try:
        resp = requests.get(url, timeout=timeout)
        return {"status": resp.status_code, "data": resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text}
    except requests.exceptions.Timeout:
        return {"status": 0, "error": "timeout"}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def safe_post(url, data=None, timeout=15):
    """Bezpečný POST request"""
    try:
        resp = requests.post(url, json=data, headers={"Content-Type": "application/json"}, timeout=timeout)
        return {"status": resp.status_code, "data": resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text}
    except requests.exceptions.Timeout:
        return {"status": 0, "error": "timeout"}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def check_all_systems():
    """Paralelní kontrola všech systémů"""
    checks = {}
    
    targets = {
        "heroku_health": f"{HEROKU_URL}/health",
        "heroku_ready": f"{HEROKU_URL}/health/ready",
        "heroku_ai_settings": f"{HEROKU_URL}/api/ai/settings",
        "heroku_radim_health": f"{HEROKU_URL}/api/radim/health",
    }
    
    # WordPress check
    if WP_URL:
        targets["wordpress_health"] = f"{WP_URL}/wp-json/kafanek-brain/v1/brain/health"
        targets["wordpress_api"] = f"{WP_URL}/wp-json/wp/v2/posts?per_page=1"
    
    # Paralelní requesty
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(safe_get, url, 10): name for name, url in targets.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                checks[name] = {
                    "status": "ok" if result.get("status") == 200 else "error",
                    "http_status": result.get("status"),
                    "data": result.get("data") if result.get("status") == 200 else None,
                    "error": result.get("error")
                }
            except Exception as e:
                checks[name] = {"status": "error", "error": str(e)}
    
    # Summary
    ok_count = sum(1 for v in checks.values() if v["status"] == "ok")
    total = len(checks)
    
    return {
        "systems": checks,
        "summary": {
            "total": total,
            "healthy": ok_count,
            "failed": total - ok_count,
            "overall": "healthy" if ok_count == total else "degraded" if ok_count > 0 else "critical"
        },
        "timestamp": now_iso()
    }


def analyze_with_gemini(context, question):
    """AI analýza pomocí Gemini"""
    if not GEMINI_API_KEY:
        return "AI analýza nedostupná (chybí GEMINI_API_KEY)"
    
    prompt = f"""Jsi Radim Brain orchestrátor. Analyzuj data a odpověz stručně česky.

Kontext:
{context[:3000]}

Otázka: {question}

Odpověz strukturovaně:
1. Stav systému
2. Nalezené problémy  
3. Doporučené akce (konkrétní kroky)
"""
    
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600}
            },
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"]
        
        return f"Gemini error: {resp.status_code}"
    except Exception as e:
        return f"Gemini error: {e}"


# ============================================
# ENDPOINTS
# ============================================

@orchestrator_bp.route('/api/orchestrator/orchestrate', methods=['POST', 'OPTIONS'])
def orchestrate():
    """🎭 Hlavní orchestrační endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    start_time = time.time()
    
    try:
        data = request.json or {}
        action = data.get('action', 'health_all')
        target = data.get('target', 'all')
        params = data.get('params', {})
        user_id = data.get('user_id', 'claude-desktop')
        
        result = {}
        thinking = {}
        next_actions = []
        
        # ============================
        # HEALTH_ALL
        # ============================
        if action == 'health_all':
            health_data = check_all_systems()
            thinking = {"approach": "Paralelní kontrola všech komponent", "checked": list(health_data["systems"].keys())}
            result = health_data
            next_actions = ["analyze", "fix"] if health_data["summary"]["failed"] > 0 else ["monitor"]
        
        # ============================
        # ANALYZE
        # ============================
        elif action == 'analyze':
            health_data = check_all_systems()
            question = params.get("question", f"Analyzuj stav systému {target}")
            analysis = analyze_with_gemini(json.dumps(health_data, indent=2, default=str), question)
            
            thinking = {"approach": "Health check → AI analýza", "target": target}
            result = {"health": health_data["summary"], "analysis": analysis, "target": target}
            next_actions = ["fix", "monitor"]
        
        # ============================
        # MONITOR
        # ============================
        elif action == 'monitor':
            health_data = check_all_systems()
            
            thinking = {"approach": "Agregace metrik"}
            result = {
                "health": health_data["summary"],
                "systems": health_data["systems"],
                "timestamp": now_iso()
            }
            next_actions = ["analyze", "health_all"]
        
        # ============================
        # CHAT
        # ============================
        elif action == 'chat':
            message = params.get('message', '')
            mode = params.get('mode', 'senior')
            
            if not message:
                return jsonify({'success': False, 'error': 'Parametr message je povinný'}), 400
            
            chat_result = safe_post(
                f"{HEROKU_URL}/api/radim/chat",
                data={"message": message, "user_id": user_id, "mode": mode}
            )
            
            thinking = {"approach": f"Radim chat (mode: {mode})"}
            result = chat_result.get("data", {"error": chat_result.get("error", "Chat failed")})
            next_actions = ["chat"]
        
        # ============================
        # FIX
        # ============================
        elif action == 'fix':
            problem = params.get('problem', '')
            health_data = check_all_systems()
            fix_analysis = analyze_with_gemini(
                json.dumps({"health": health_data, "problem": problem}, indent=2, default=str),
                f"Navrhni konkrétní opravu: {problem or 'všechny problémy'}"
            )
            
            thinking = {"approach": "Diagnóza → AI analýza → návrh opravy", "target": target}
            result = {"health": health_data["summary"], "fix_suggestion": fix_analysis}
            next_actions = ["health_all"]
        
        # ============================
        # WP_CHECK - WordPress specifická kontrola
        # ============================
        elif action == 'wp_check':
            wp_results = {}
            
            # REST API
            wp_api = safe_get(f"{WP_URL}/wp-json/wp/v2/posts?per_page=1")
            wp_results["rest_api"] = {"status": "ok" if wp_api.get("status") == 200 else "error"}
            
            # Kafánek Brain plugin
            wp_brain = safe_get(f"{WP_URL}/wp-json/kafanek-brain/v1/brain/health")
            wp_results["kafanek_brain"] = {
                "status": "ok" if wp_brain.get("status") == 200 else "error",
                "data": wp_brain.get("data")
            }
            
            # Brain status endpoint
            wp_status = safe_get(f"{WP_URL}/wp-json/kafanek-brain/v1/brain/status")
            wp_results["brain_status"] = {
                "status": "ok" if wp_status.get("status") == 200 else "error",
                "data": wp_status.get("data") if wp_status.get("status") == 200 else None,
                "error": wp_status.get("error")
            }
            
            # Intelligence scores
            wp_intel = safe_get(f"{WP_URL}/wp-json/kafanek-brain/v1/brain/intelligence/scores")
            wp_results["intelligence"] = {
                "status": "ok" if wp_intel.get("status") == 200 else "error",
                "error": wp_intel.get("error")
            }
            
            thinking = {"approach": "WordPress plugin endpointy kontrola"}
            result = {"wordpress": wp_results, "url": WP_URL}
            
            missing = [k for k, v in wp_results.items() if v["status"] != "ok"]
            next_actions = ["fix"] if missing else ["monitor"]
        
        # ============================
        # UNKNOWN
        # ============================
        else:
            return jsonify({
                'success': False, 
                'error': f'Neznámá akce: {action}',
                'supported': ['health_all', 'analyze', 'monitor', 'chat', 'fix', 'wp_check']
            }), 400
        
        processing_ms = round((time.time() - start_time) * 1000, 2)
        
        return jsonify({
            'success': True,
            'action': action,
            'result': result,
            'thinking': thinking,
            'next_actions': next_actions,
            'processing_time_ms': processing_ms,
            'timestamp': now_iso()
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'action': data.get('action', 'unknown')}), 500


@orchestrator_bp.route('/api/orchestrator/health', methods=['GET'])
def orchestrator_health():
    """Quick orchestrator health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'Radim Orchestrator',
        'version': '2.0.0',
        'capabilities': ['health_all', 'analyze', 'monitor', 'chat', 'fix', 'wp_check'],
        'heroku_url': HEROKU_URL,
        'wordpress_url': WP_URL,
        'ai_available': bool(GEMINI_API_KEY),
        'claude_available': bool(ANTHROPIC_API_KEY),
        'timestamp': now_iso()
    })


@orchestrator_bp.route('/api/orchestrator/systems', methods=['GET'])
def systems_status():
    """Rychlý přehled všech systémů"""
    return jsonify(check_all_systems())
