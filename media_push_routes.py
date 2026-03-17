# -*- coding: utf-8 -*-
"""
Media Upload & Push Notification Routes
Extracted from app.py into a standalone Blueprint.
"""

import os
import json
import base64
import logging
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from rate_limiter import rate_limit
from database import get_db_for_flask, is_postgres
from utils import generate_id, now_iso

logger = logging.getLogger(__name__)

# Flask Blueprint
media_push_bp = Blueprint('media_push', __name__)

# VAPID key from environment
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')

# Dependency injection holders
_upload_to_cloudinary = None
_send_push_notification = None


def init_media_push_routes(upload_to_cloudinary=None, send_push_notification=None):
    """Inject dependencies from app.py."""
    global _upload_to_cloudinary, _send_push_notification
    _upload_to_cloudinary = upload_to_cloudinary
    _send_push_notification = send_push_notification


def _get_upload_fn():
    if _upload_to_cloudinary is not None:
        return _upload_to_cloudinary
    import app as _app
    return _app.upload_to_cloudinary


def _get_push_fn():
    if _send_push_notification is not None:
        return _send_push_notification
    import app as _app
    return _app.send_push_notification


def get_db():
    return get_db_for_flask(g)



# ============================================================================
# MEDIA UPLOAD
# ============================================================================

@media_push_bp.route('/api/media/upload', methods=['POST'])
@rate_limit(20, 60, 'ip')
def upload_media():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        file = request.files['file']
        user_id = request.form.get('userId', 'anonymous')
        media_type = request.form.get('type', 'auto')
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        upload_to_cloudinary = _get_upload_fn()
        result = upload_to_cloudinary(file, resource_type=media_type)
        if not result:
            file_data = base64.b64encode(file.read()).decode('utf-8')
            result = {
                'url': f"data:{file.content_type};base64,{file_data}",
                'public_id': generate_id(),
                'size': len(file_data)
            }
        media_id = generate_id()
        db = get_db()
        db.execute('''
            INSERT INTO chat_media (id, user_id, type, url, public_id, filename, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (media_id, user_id, media_type, result['url'], result.get('public_id'),
              file.filename, result.get('size'), now_iso()))
        db.commit()
        return jsonify({
            'success': True,
            'media': {
                'id': media_id,
                'url': result['url'],
                'type': media_type,
                'filename': file.filename,
                'size': result.get('size')
            }
        })
    except Exception as e:
        logger.error(f"Media upload error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@media_push_bp.route('/api/media/voice', methods=['POST'])
@rate_limit(20, 60, 'ip')
def upload_voice_message():
    try:
        if 'audio' not in request.files:
            return jsonify({'success': False, 'error': 'No audio provided'}), 400
        file = request.files['audio']
        user_id = request.form.get('userId', 'anonymous')
        duration = request.form.get('duration', 0)
        upload_to_cloudinary = _get_upload_fn()
        result = upload_to_cloudinary(file, resource_type='video', folder='radim-chat/voice')
        if not result:
            file_data = base64.b64encode(file.read()).decode('utf-8')
            result = {
                'url': f"data:audio/webm;base64,{file_data}",
                'public_id': generate_id()
            }
        media_id = generate_id()
        db = get_db()
        db.execute('''
            INSERT INTO chat_media (id, user_id, type, url, public_id, duration, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (media_id, user_id, 'voice', result['url'], result.get('public_id'), duration, now_iso()))
        db.commit()
        return jsonify({
            'success': True,
            'voice': {
                'id': media_id,
                'url': result['url'],
                'duration': duration
            }
        })
    except Exception as e:
        logger.error(f"Voice upload error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================================================
# PUSH NOTIFICATIONS
# ============================================================================

@media_push_bp.route('/api/push/subscribe', methods=['POST'])
@rate_limit(10, 60, 'ip')
def subscribe_push():
    try:
        data = request.get_json() or {}
        user_id = data.get('userId')
        subscription = data.get('subscription')
        if not user_id or not subscription:
            return jsonify({'success': False, 'error': 'Chybí userId nebo subscription'}), 400
        db = get_db()
        if is_postgres():
            db.execute('''
                INSERT INTO push_subscriptions (id, user_id, endpoint, keys, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (user_id, endpoint) DO UPDATE SET
                    keys = EXCLUDED.keys, created_at = EXCLUDED.created_at
            ''', (generate_id(), user_id, subscription['endpoint'],
                  json.dumps(subscription['keys']), now_iso()))
        else:
            db.execute('''
                INSERT OR REPLACE INTO push_subscriptions (id, user_id, endpoint, keys, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (generate_id(), user_id, subscription['endpoint'],
                  json.dumps(subscription['keys']), now_iso()))
        db.commit()
        return jsonify({'success': True, 'message': 'Subscribed to push notifications'})
    except Exception as e:
        logger.error(f"Push subscribe error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@media_push_bp.route('/api/push/unsubscribe', methods=['POST'])
def unsubscribe_push():
    try:
        data = request.get_json() or {}
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'error': 'Chybí userId'}), 400
        endpoint = data.get('endpoint')
        db = get_db()
        if endpoint:
            db.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?', (user_id, endpoint))
        else:
            db.execute('DELETE FROM push_subscriptions WHERE user_id = ?', (user_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'Unsubscribed from push notifications'})
    except Exception as e:
        logger.error(f"Push unsubscribe error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@media_push_bp.route('/api/push/vapid-key', methods=['GET'])
def get_vapid_key():
    return jsonify({
        'success': True,
        'publicKey': VAPID_PUBLIC_KEY or ''
    })


@media_push_bp.route('/api/push/test', methods=['POST'])
def test_push():
    try:
        data = request.get_json() or {}
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'error': 'Chybí userId'}), 400
        send_push_notification = _get_push_fn()
        success = send_push_notification(
            user_id,
            'Test od Radima \U0001f389',
            'Toto je testovací notifikace. Pokud ji vidíte, vše funguje!',
            {'test': True}
        )
        return jsonify({'success': success})
    except Exception as e:
        logger.error(f"Push test error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500
