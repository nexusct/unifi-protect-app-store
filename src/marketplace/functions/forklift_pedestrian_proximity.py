"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'forklift-pedestrian-proximity',
 'name': 'Forklift–Pedestrian Proximity Review',
 'tagline': 'Uses independent domain weights to flag close person and forklift tracks in image '
            'space for human safety review.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'weights': 'path — independently supplied person/forklift model weights',
                   'confidence': 'float — minimum model confidence (default 0.50)',
                   'distance_ratio': 'float — normalized image-plane distance threshold (default '
                                     '0.12)',
                   'cooldown_seconds': 'int — pair repeat suppression (default 30)'}}

from model_paths import model_path
from marketplace.vendor_patterns import ForkliftProximityFunction

class Function(ForkliftProximityFunction):
    function_id = MANIFEST["id"]

    def __init__(self, settings):
        merged = {"weights": model_path("forklift.pt")}
        merged.update(settings or {})
        super().__init__(merged)
