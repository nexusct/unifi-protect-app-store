"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'pedestrian-vehicle-conflict',
 'name': 'Pedestrian–Vehicle Conflict Review',
 'tagline': 'Flags close image-plane person and road-vehicle detections for visual review; it does '
            'not determine that a near miss occurred.',
 'category': 'People & Safety',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'distance_pixels': 'float — camera-calibrated image-plane proximity threshold '
                                      '(default 120)'}}

from detectors.near_miss import NearMissDetector
from marketplace.vendor_patterns import DetectorAdapterFunction

class Function(DetectorAdapterFunction):
    function_id = MANIFEST["id"]
    detector_cls = NearMissDetector
    detector_overrides = {}
