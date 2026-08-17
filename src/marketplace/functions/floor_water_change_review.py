"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'floor-water-change-review',
 'name': 'Floor Appearance Change Review',
 'tagline': 'Flags sustained changes in a bounded floor-zone appearance metric for inspection; it '
            'does not confirm water or a leak.',
 'category': 'Property & Liability',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'zone': 'camera zone named floor_review — normalized polygon',
                   'min_samples': 'int — local baseline samples (default 20)',
                   'change_threshold': 'float — absolute metric change (default 0.20)',
                   'hold_seconds': 'float — sustained change duration (default 5)'}}

CAMERA_ZONES = {'zone': 'floor_review'}

from marketplace.vendor_patterns import FloorAppearanceFunction

class Function(FloorAppearanceFunction):
    function_id = MANIFEST["id"]
