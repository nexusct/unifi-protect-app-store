"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'package-room-chain-review',
 'name': 'Package-Room Chain Review',
 'tagline': 'Correlates customer-model package-count changes with nearby door events to review '
            'deposit and pickup chains.',
 'category': 'Security & Access',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'package_zone': 'polygon — package observation area',
                   'weights': 'path — customer-supplied package model weights',
                   'labels': 'list — package labels to count',
                   'confidence': 'float — minimum custom-model confidence (default 0.45)',
                   'door_id': 'string — optional UniFi Access door ID',
                   'access_window_seconds': 'float — access correlation window (default 45)',
                   'require_access_event': 'bool — require a nearby door event (default true)'}}

CAMERA_ZONES = {'package_zone': 'package_room_zone'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'package_chain'
    profile = {'zones': {'package': 'package_room_zone'},
 'labels': ['package', 'parcel', 'box'],
 'access_window_seconds': 45,
 'require_access_event': True}
