"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'smoke-flame-visual-review',
 'name': 'Smoke & Flame Visual Review',
 'tagline': 'Routes persistent smoke/flame model candidates or a tuned warm-region heuristic for '
            'human review; supplemental only and never a replacement for life-safety sensors.',
 'category': 'People & Safety',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'weights': 'path — independently supplied smoke/flame weights; heuristic is '
                              'used when absent',
                   'confidence': 'float — minimum model confidence (default 0.50)'}}

from detectors.smoke_flame import SmokeFlameDetector
from marketplace.vendor_patterns import DetectorAdapterFunction

class Function(DetectorAdapterFunction):
    function_id = MANIFEST["id"]
    detector_cls = SmokeFlameDetector
    detector_overrides = {}
