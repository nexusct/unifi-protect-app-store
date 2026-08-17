"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'assembly-stage-order-review',
 'name': 'Assembly Stage Order Review',
 'tagline': 'Uses independent station-specific weights to compare observed stage candidates with a '
            'configured sequence; all exceptions require operator verification.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'weights': 'path — independently supplied station-stage model weights',
                   'expected_sequence': 'list — ordered normalized stage labels, maximum 32',
                   'confidence': 'float — minimum model confidence (default 0.50)'}}

from model_paths import model_path
from marketplace.vendor_patterns import AssemblySequenceFunction

class Function(AssemblySequenceFunction):
    function_id = MANIFEST["id"]

    def __init__(self, settings):
        merged = {"weights": model_path("assembly-stages.pt")}
        merged.update(settings or {})
        super().__init__(merged)
