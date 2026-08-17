"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'unusual-dwell-baseline',
 'name': 'Unusual Dwell Baseline Review',
 'tagline': 'Learns completed anonymous dwell times locally and flags a current track materially '
            'above the rolling median after sufficient samples.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'zone': 'camera zone named dwell_baseline — normalized polygon',
                   'min_samples': 'int — completed dwell samples before evaluation (default 20)',
                   'minimum_seconds': 'int — absolute minimum dwell before review (default 60)',
                   'anomaly_factor': 'float — multiplier over rolling median (default 3)'}}

CAMERA_ZONES = {'zone': 'dwell_baseline'}

from marketplace.vendor_patterns import UnusualDwellBaselineFunction

class Function(UnusualDwellBaselineFunction):
    function_id = MANIFEST["id"]
    zone_key = "dwell_baseline"
