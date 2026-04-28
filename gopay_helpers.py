# -*- coding: utf-8 -*-
"""
GoPay Payment Gateway — REST API helper

Centralizuje volání GoPay API pro:
  - vytvoření platby (partner platí za nabídku Radimova Odkazu)
  - kontrolu stavu platby (callback handler)
  - refund
  - access token management

Env vars (nastavit na Heroku):
  GOPAY_GO_ID            — merchant goid (např. "8123456789")
  GOPAY_CLIENT_ID        — OAuth client_id
  GOPAY_CLIENT_SECRET    — OAuth client_secret
  GOPAY_API_URL          — "https://gw.sandbox.gopay.com" (sandbox)
                            nebo "https://gate.gopay.cz" (production)
  GOPAY_DEFAULT_CURRENCY — "CZK" (default)
  GOPAY_WEBHOOK_SECRET   — sdílené tajemství pro signature ověření

Reference:
  https://doc.gopay.com/
  https://help.gopay.com/cs/
"""

import os
import time
import logging
import hashlib
import hmac
import json
import requests as http_requests

logger = logging.getLogger(__name__)

GOPAY_GO_ID = os.environ.get('GOPAY_GO_ID', '')
GOPAY_CLIENT_ID = os.environ.get('GOPAY_CLIENT_ID', '')
GOPAY_CLIENT_SECRET = os.environ.get('GOPAY_CLIENT_SECRET', '')
GOPAY_API_URL = os.environ.get('GOPAY_API_URL', 'https://gw.sandbox.gopay.com').rstrip('/')
GOPAY_DEFAULT_CURRENCY = os.environ.get('GOPAY_DEFAULT_CURRENCY', 'CZK')
GOPAY_WEBHOOK_SECRET = os.environ.get('GOPAY_WEBHOOK_SECRET', '')


# ============================================
# CONFIGURATION HEALTH CHECK
# ============================================

def is_configured():
    """Vrátí True pokud jsou všechny GoPay env vars nastavené."""
    return bool(GOPAY_GO_ID and GOPAY_CLIENT_ID and GOPAY_CLIENT_SECRET)


def health_check():
    """Pro /health endpoint — neblokující status."""
    return {
        'configured': is_configured(),
        'environment': 'sandbox' if 'sandbox' in GOPAY_API_URL else 'production',
        'goid_set': bool(GOPAY_GO_ID),
    }


# ============================================
# OAUTH ACCESS TOKEN (cache 30 min)
# ============================================

_token_cache = {'token': None, 'expires_at': 0}


def _get_access_token():
    """OAuth client_credentials flow. Token platí 30 min, cachujeme."""
    now = time.time()
    if _token_cache['token'] and _token_cache['expires_at'] > now + 60:
        return _token_cache['token']

    if not is_configured():
        logger.warning('GoPay not configured — missing GOPAY_CLIENT_ID/SECRET')
        return None

    try:
        response = http_requests.post(
            f'{GOPAY_API_URL}/api/oauth2/token',
            auth=(GOPAY_CLIENT_ID, GOPAY_CLIENT_SECRET),
            data={
                'grant_type': 'client_credentials',
                'scope': 'payment-create',
            },
            headers={'Accept': 'application/json'},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get('access_token')
        expires_in = int(data.get('expires_in', 1800))
        _token_cache['token'] = token
        _token_cache['expires_at'] = now + expires_in
        logger.info(f'GoPay access token obtained, valid for {expires_in}s')
        return token
    except Exception as e:
        logger.error(f'GoPay token error: {e}', exc_info=True)
        return None


# ============================================
# PAYMENT CREATION (partner platí za nabídku)
# ============================================

def create_payment(amount_kc, order_number, partner_email, partner_org,
                   item_name, return_url, notify_url, anonymized=True):
    """Vytvoří GoPay platbu pro partnerskou platbu za vzpomínku.

    Args:
        amount_kc:      Částka v Kč (integer)
        order_number:   Naše interní číslo objednávky (např. "RADIM-2026-001")
        partner_email:  Kontaktní email partnera (pro doklady)
        partner_org:    Název organizace partnera
        item_name:      Popis (např. "Vzpomínka: Pražské jaro 1968 — anonymní licence")
        return_url:     URL, kam se partner vrátí po platbě (success/fail)
        notify_url:     URL, kam GoPay pošle webhook po dokončení
        anonymized:     True = vzpomínka je anonymizovaná (vyšší DPH risk u dat)

    Returns:
        dict: {'id': payment_id, 'gw_url': redirect_url, ...}
              nebo None pokud selhání
    """
    token = _get_access_token()
    if not token:
        return None

    try:
        payload = {
            'payer': {
                'default_payment_instrument': 'BANK_ACCOUNT',
                'allowed_payment_instruments': [
                    'BANK_ACCOUNT',  # Online bankovní platba (preferovaná v ČR)
                    'PAYMENT_CARD',  # Karta
                    'GPAY',          # Apple/Google Pay
                ],
                'contact': {
                    'email': partner_email,
                },
            },
            'amount': amount_kc * 100,  # GoPay očekává halíře (1 Kč = 100 haléřů)
            'currency': GOPAY_DEFAULT_CURRENCY,
            'order_number': order_number,
            'order_description': f'Radimův Odkaz: {item_name[:120]}',
            'items': [{
                'type': 'ITEM',
                'name': item_name[:200],
                'amount': amount_kc * 100,
                'count': 1,
                # VAT_RATE_4 = osvobozeno (typicky pro vzdělání/výzkum)
                # VAT_RATE_3 = 21% (komerční využití)
                'vat_rate': 'VAT_RATE_3' if not anonymized else 'VAT_RATE_4',
            }],
            'callback': {
                'return_url': return_url,
                'notification_url': notify_url,
            },
            'lang': 'CS',
            'target': {
                'type': 'ACCOUNT',
                'goid': GOPAY_GO_ID,
            },
            'additional_params': [
                {'name': 'partner_org', 'value': partner_org[:100]},
                {'name': 'project', 'value': 'radim_odkaz'},
            ],
        }

        response = http_requests.post(
            f'{GOPAY_API_URL}/api/payments/payment',
            json=payload,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f'GoPay payment created: id={data.get("id")} order={order_number} amount={amount_kc} CZK')
        return data
    except http_requests.exceptions.HTTPError as e:
        body = (e.response.text or '')[:500]
        logger.error(f'GoPay create_payment HTTP error: {e.response.status_code} — {body}')
        return None
    except Exception as e:
        logger.error(f'GoPay create_payment error: {e}', exc_info=True)
        return None


# ============================================
# PAYMENT STATUS (po webhooku ověřit reálný stav)
# ============================================

def get_payment_status(payment_id):
    """Načte aktuální stav platby z GoPay.

    Returns:
        dict s polem 'state':
            CREATED     — vytvořená, čeká na úhradu
            PAYMENT_METHOD_CHOSEN — partner zvolil metodu
            PAID        — uhrazená ✓
            AUTHORIZED  — autorizovaná (např. blokace na kartě)
            CANCELED    — zrušená
            TIMEOUTED   — vypršela
            REFUNDED    — vrácená
            PARTIALLY_REFUNDED
        nebo None
    """
    token = _get_access_token()
    if not token or not payment_id:
        return None

    try:
        response = http_requests.get(
            f'{GOPAY_API_URL}/api/payments/payment/{payment_id}',
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f'GoPay get_payment_status({payment_id}) error: {e}')
        return None


# ============================================
# REFUND (refundace partnerovi, např. nesplněná specifikace)
# ============================================

def refund_payment(payment_id, amount_kc=None, reason='customer_request'):
    """Refundace platby. Pokud amount=None, refunduje plnou částku.

    Returns:
        dict s 'id' refund operace nebo None
    """
    token = _get_access_token()
    if not token or not payment_id:
        return None

    try:
        payload = {}
        if amount_kc is not None:
            payload['amount'] = amount_kc * 100  # haléře
        payload['note'] = reason[:200]

        response = http_requests.post(
            f'{GOPAY_API_URL}/api/payments/payment/{payment_id}/refund',
            json=payload,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f'GoPay refund created: payment={payment_id} amount={amount_kc} reason={reason}')
        return data
    except Exception as e:
        logger.error(f'GoPay refund error: {e}', exc_info=True)
        return None


# ============================================
# WEBHOOK SIGNATURE VERIFICATION
# ============================================

def verify_webhook_signature(raw_body, signature_header):
    """Ověří HMAC SHA256 signaturu od GoPay webhook.

    GoPay v notification_url POST sends body + custom header
    'X-GoPay-Signature' (or similar). Ověříme HMAC s naším shared secret.
    """
    if not GOPAY_WEBHOOK_SECRET:
        logger.warning('GOPAY_WEBHOOK_SECRET not set — skipping signature check (DEV ONLY)')
        return True
    if not signature_header:
        return False

    expected = hmac.new(
        GOPAY_WEBHOOK_SECRET.encode('utf-8'),
        raw_body if isinstance(raw_body, bytes) else raw_body.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ============================================
# REVENUE SHARE CALCULATION
# ============================================

PLATFORM_PERCENT = 20  # KOLIBRI 20% provize
SENIOR_PERCENT = 80    # senior 80% netto


def calculate_split(gross_kc):
    """Vrátí (senior_net_kc, platform_net_kc, platform_vat_kc).

    Příklad: gross=1500
        senior gets:    1200 Kč (80%)
        KOLIBRI gross:   300 Kč (20%)
        z toho DPH 21%:   52 Kč  (300 / 1.21 × 0.21)
        KOLIBRI netto:   248 Kč
    """
    senior_net = int(round(gross_kc * SENIOR_PERCENT / 100.0))
    platform_gross = gross_kc - senior_net
    # DPH 21% z platformového gross (provize je s DPH zatížená)
    platform_vat = int(round(platform_gross * 0.21 / 1.21))
    platform_net = platform_gross - platform_vat
    return {
        'gross_kc': gross_kc,
        'senior_net_kc': senior_net,
        'platform_gross_kc': platform_gross,
        'platform_vat_kc': platform_vat,
        'platform_net_kc': platform_net,
    }
