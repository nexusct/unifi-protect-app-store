"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'vehicle-wrong-way',
 'name': 'Vehicle Wrong-Way Crossing Review',
 'tagline': 'Flags vehicle-class tracks crossing a configured line opposite its allowed direction; '
            'physical speed is not inferred.',
 'category': 'Automotive & Parking',
 'tier': 'starter',
 'requires_gpu': True,
 'config_schema': {'line': 'camera zone named vehicle_direction_line — two-point line in normalized coordinates',
                   'allowed_direction': 'int — allowed crossing sign, 1 or -1 (default 1)',
                   'cooldown_seconds': 'int — repeat suppression per track (default 30)'}}

CAMERA_ZONES = {'line': 'vehicle_direction_line'}

from marketplace.vendor_patterns import VehicleWrongWayFunction

class Function(VehicleWrongWayFunction):
    function_id = MANIFEST["id"]
