# -*- coding: utf-8 -*-
"""
RADIM IDENTITY ROUTES v1.0

Veřejné read-only endpointy pro zobrazení Radimovy identity v aplikaci.
Žádné skryté názory — vše je transparentní a auditovatelné.

Endpointy:
  GET /api/radim/identity         — celá identita (cached)
  GET /api/radim/identity/random  — n náhodných „věcí o sobě" pro home widget
"""

from flask import Blueprint, jsonify, request
import logging

from radim_identity import (
    get_identity_dict,
    pick_random_facets,
    IDENTITY_VERSION,
)

logger = logging.getLogger(__name__)
identity_bp = Blueprint('identity', __name__, url_prefix='/api/radim/identity')


@identity_bp.route('', methods=['GET'])
@identity_bp.route('/', methods=['GET'])
def get_identity():
    """Vrátí kompletní identitu Radima.

    Response: {
      version, author, notes,
      loves: [...], dislikes: [...], curious_about: [...],
      quirks: [...], beliefs: [...],
      counts: {...}
    }

    Veřejné — bez auth. Identita je sdílený obsah.
    Cache-friendly: response je deterministický pro danou IDENTITY_VERSION.
    """
    payload = get_identity_dict()
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'public, max-age=3600'  # 1 h cache
    response.headers['ETag'] = f'"radim-identity-{IDENTITY_VERSION}"'
    return response, 200


@identity_bp.route('/random', methods=['GET'])
def get_random_facets():
    """Vrátí n náhodných facet pro rotující widget na Domů.

    Query params:
      n (int, default 2, max 6) — kolik facet vrátit

    Response: { facets: [{ category, item }, ...] }
    """
    try:
        n = int(request.args.get('n', '2'))
        n = max(1, min(n, 6))
    except (ValueError, TypeError):
        n = 2

    facets = pick_random_facets(n=n)
    response = jsonify({'facets': facets, 'n': n})
    # Krátké cache — random by měl rotovat. 30 s.
    response.headers['Cache-Control'] = 'public, max-age=30'
    return response, 200


# Aliasy pro starší frontend (žádný neexistuje, ale pro budoucnost)
@identity_bp.route('/about', methods=['GET'])
def get_about_alias():
    """Alias pro GET /api/radim/identity (vhodný název pro budoucí UI)."""
    return get_identity()
