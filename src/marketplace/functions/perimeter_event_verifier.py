"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'perimeter-event-verifier',
 'name': 'Perimeter Event Verifier',
 'tagline': 'Correlates anonymous perimeter crossing or dwell with available Protect event context '
            'before raising a review.',
 'category': 'Security & Access',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'perimeter_zone': 'polygon — restricted perimeter area',
                   'boundary_line': 'two-point line — configured perimeter threshold',
                   'hold_seconds': 'float — in-zone dwell before verification (default 4)',
                   'protect_window_seconds': 'float — Protect event correlation window (default '
                                             '30)',
                   'require_protect_event': 'bool — require Protect metadata as well as vision',
                   'classes': 'list — COCO person and vehicle class IDs'}}

CAMERA_ZONES = {'perimeter_zone': 'perimeter_verify_zone', 'boundary_line': 'perimeter_verify_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'perimeter_verify'
    profile = {'zones': {'perimeter': 'perimeter_verify_zone', 'boundary': 'perimeter_verify_line'},
 'hold_seconds': 4,
 'protect_window_seconds': 30,
 'classes': [0, 2, 3, 5, 7]}
