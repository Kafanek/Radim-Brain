"""
🧬 NEURON LEARNING — Routes v1.0.0 (Sprint AA)
===========================================================
Backend persistence for Kafánek Neurons (frontend learning layer).

Previously each neuron stored its threshold/rhythm/feedback only in the
browser's localStorage, so cookie clears or device changes wiped all
adaptability. This blueprint mirrors the JS NeuronLearning blob into
postgres so neurons stay personalized across devices and sessions.

Routes:
  GET  /api/neurons/<user_id>                  — bulk fetch (all neurons)
  GET  /api/neurons/<user_id>/<neuron_id>      — single neuron
  PUT  /api/neurons/<user_id>/<neuron_id>      — upsert single neuron
  POST /api/neurons/<user_id>/sync             — bulk upsert (debounced)
  DELETE /api/neurons/<user_id>                — wipe (GDPR)

Schema: see database_schema.py → neuron_learning table.
"""

import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

neuron_bp = Blueprint('neuron', __name__, url_prefix='/api/neurons')

try:
    from database import is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("neuron_routes: database module unavailable — endpoints will 503")


# Cap payload size — a single neuron blob should be <50KB even after many
# activations (history capped at 20, modeHistory at 20). 64KB ceiling
# prevents abuse.
MAX_NEURON_BYTES = 64 * 1024
# Cap per user — guards against unbounded neuron_id sprawl.
MAX_NEURONS_PER_USER = 64


def _upsert_neuron(user_id, neuron_id, data):
    """INSERT-or-UPDATE one (user_id, neuron_id) row. Caller handles tx."""
    payload = json.dumps(data, ensure_ascii=False)
    if len(payload.encode('utf-8')) > MAX_NEURON_BYTES:
        raise ValueError(f"neuron blob exceeds {MAX_NEURON_BYTES} bytes")

    with db_context(commit=True) as db:
        if is_postgres():
            db.execute(
                "INSERT INTO neuron_learning (user_id, neuron_id, data, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (user_id, neuron_id) DO UPDATE SET "
                "data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
                (user_id, neuron_id, payload, datetime.utcnow())
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO neuron_learning "
                "(user_id, neuron_id, data, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, neuron_id, payload, datetime.utcnow().isoformat())
            )


@neuron_bp.route('/<user_id>', methods=['GET'])
def list_neurons(user_id):
    """Return all neurons learned for this user as { neuron_id: data }."""
    if not _DB_AVAILABLE:
        return jsonify({'error': 'db_unavailable'}), 503
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT neuron_id, data, updated_at FROM neuron_learning "
                "WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
            rows = cur.fetchall()

        neurons = {}
        for row in rows:
            try:
                # Row may be tuple, sqlite Row, or dict-like depending on driver
                nid = row[0] if not isinstance(row, dict) else row['neuron_id']
                raw = row[1] if not isinstance(row, dict) else row['data']
                neurons[nid] = json.loads(raw) if isinstance(raw, str) else raw
            except (KeyError, json.JSONDecodeError, IndexError):
                continue
        return jsonify({'success': True, 'user_id': user_id, 'neurons': neurons})
    except Exception as e:
        logger.warning(f"list_neurons({user_id}) error: {e}")
        return jsonify({'error': str(e)[:120]}), 500


@neuron_bp.route('/<user_id>/<neuron_id>', methods=['GET'])
def get_neuron(user_id, neuron_id):
    """Fetch one neuron's learning state."""
    if not _DB_AVAILABLE:
        return jsonify({'error': 'db_unavailable'}), 503
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT data FROM neuron_learning WHERE user_id = ? AND neuron_id = ?",
                (user_id, neuron_id)
            )
            row = cur.fetchone()
        if not row:
            return jsonify({'success': True, 'data': None}), 404
        raw = row[0] if not isinstance(row, dict) else row['data']
        data = json.loads(raw) if isinstance(raw, str) else raw
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.warning(f"get_neuron({user_id},{neuron_id}) error: {e}")
        return jsonify({'error': str(e)[:120]}), 500


@neuron_bp.route('/<user_id>/<neuron_id>', methods=['PUT'])
def put_neuron(user_id, neuron_id):
    """Upsert one neuron's learning state. Body: raw NeuronLearning blob."""
    if not _DB_AVAILABLE:
        return jsonify({'error': 'db_unavailable'}), 503
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({'error': 'json body required'}), 400
    try:
        _upsert_neuron(user_id, neuron_id, body)
        return jsonify({'success': True})
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 413
    except Exception as e:
        logger.warning(f"put_neuron({user_id},{neuron_id}) error: {e}")
        return jsonify({'error': str(e)[:120]}), 500


@neuron_bp.route('/<user_id>/sync', methods=['POST'])
def bulk_sync(user_id):
    """Bulk upsert. Body: { neurons: { neuron_id: data, ... } }.

    Frontend debounces feedback events into one round-trip every ~5s.
    """
    if not _DB_AVAILABLE:
        return jsonify({'error': 'db_unavailable'}), 503
    body = request.get_json(silent=True) or {}
    neurons = body.get('neurons') or {}
    if not isinstance(neurons, dict):
        return jsonify({'error': 'neurons must be an object'}), 400
    if len(neurons) > MAX_NEURONS_PER_USER:
        return jsonify({
            'error': f'too many neurons (max {MAX_NEURONS_PER_USER})'
        }), 413

    saved, skipped = 0, []
    for nid, data in neurons.items():
        if not isinstance(nid, str) or not nid or len(nid) > 64:
            skipped.append({'id': str(nid)[:32], 'reason': 'bad_id'})
            continue
        try:
            _upsert_neuron(user_id, nid, data)
            saved += 1
        except ValueError as ve:
            skipped.append({'id': nid, 'reason': str(ve)})
        except Exception as e:
            logger.warning(f"bulk_sync upsert {user_id}/{nid}: {e}")
            skipped.append({'id': nid, 'reason': 'db_error'})

    return jsonify({'success': True, 'saved': saved, 'skipped': skipped})


@neuron_bp.route('/<user_id>', methods=['DELETE'])
def wipe_neurons(user_id):
    """Delete all neuron learning for this user (GDPR / device reset)."""
    if not _DB_AVAILABLE:
        return jsonify({'error': 'db_unavailable'}), 503
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM neuron_learning WHERE user_id = ?", (user_id,))
        return jsonify({'success': True})
    except Exception as e:
        logger.warning(f"wipe_neurons({user_id}) error: {e}")
        return jsonify({'error': str(e)[:120]}), 500
