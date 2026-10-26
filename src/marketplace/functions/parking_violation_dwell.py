"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'parking-violation-dwell',
 'name': 'Restricted Parking Dwell Review',
 'tagline': 'Flags a sustained vehicle-class track in a configured restricted-parking zone; policy '
            'or violation status remains an operator decision.',
 'category': 'Automotive & Parking',
 'tier': 'starter',
 'requires_gpu': True,
 'config_schema': {'zone': 'camera zone named restricted_parking — normalized polygon',
                   'hold_seconds': 'int — sustained dwell before review (default 120)'}}

CAMERA_ZONES = {'zone': 'restricted_parking'}

from marketplace.vendor_patterns import VehicleZoneDwellFunction

class Function(VehicleZoneDwellFunction):
    function_id = MANIFEST["id"]
    zone_key = "restricted_parking"
