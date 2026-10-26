"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'unusual-motion-baseline',
 'name': 'Unusual Motion Baseline Review',
 'tagline': 'Learns local frame-to-frame motion energy and flags sustained increases above the '
            'rolling median for visual review.',
 'category': 'Security & Access',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'min_samples': 'int — local baseline samples (default 20)',
                   'anomaly_factor': 'float — multiplier over median motion energy (default 3)',
                   'hold_seconds': 'float — sustained anomaly duration (default 5)'}}

from marketplace.vendor_patterns import MotionBaselineFunction

class Function(MotionBaselineFunction):
    function_id = MANIFEST["id"]
