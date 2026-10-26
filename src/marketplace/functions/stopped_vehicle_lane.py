"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'stopped-vehicle-lane',
 'name': 'Stopped Vehicle Lane Review',
 'tagline': 'Flags a vehicle-class track with sustained low image-plane movement inside a '
            'configured lane; it does not measure physical speed.',
 'category': 'Automotive & Parking',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'zone': 'camera zone named traffic_lane — normalized polygon',
                   'hold_seconds': 'int — low-motion duration before review (default 20)',
                   'movement_threshold': 'float — normalized inter-frame movement threshold '
                                         '(default 0.01)'}}

CAMERA_ZONES = {'zone': 'traffic_lane'}

from marketplace.vendor_patterns import StationaryVehicleFunction

class Function(StationaryVehicleFunction):
    function_id = MANIFEST["id"]
    zone_key = "traffic_lane"
