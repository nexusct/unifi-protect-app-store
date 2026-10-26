"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'occupancy-flow-anomaly',
 'name': 'Occupancy Flow Anomaly Review',
 'tagline': 'Compares anonymous person counts with a local rolling median and flags material high '
            'or low deviations after sufficient samples.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'zone': 'camera zone named occupancy — normalized polygon',
                   'min_samples': 'int — baseline observations before evaluation (default 20)',
                   'anomaly_factor': 'float — deviation multiplier (default 2)'}}

CAMERA_ZONES = {'zone': 'occupancy'}

from marketplace.vendor_patterns import RollingCountAnomalyFunction

class Function(RollingCountAnomalyFunction):
    function_id = MANIFEST["id"]
    zone_key = "occupancy"
