"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'hardhat-visibility-review',
 'name': 'Hardhat Visibility Review',
 'tagline': 'Flags person boxes where the configured PPE model did not observe a hardhat '
            'candidate; requires visual verification and does not determine compliance.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'weights': 'path — independently supplied PPE model weights',
                   'confidence': 'float — minimum model confidence (default 0.50)'}}

from detectors.ppe import PPEDetector
from marketplace.vendor_patterns import DetectorAdapterFunction

class Function(DetectorAdapterFunction):
    function_id = MANIFEST["id"]
    detector_cls = PPEDetector
    detector_overrides = {"required": ["hardhat"]}
