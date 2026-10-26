"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'shipping-label-presence-review',
 'name': 'Shipping Label Presence Review',
 'tagline': 'Uses independent package/label weights to flag a sustained package box without an '
            'associated label center for verification.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'weights': 'path — independently supplied package-and-label model weights',
                   'confidence': 'float — minimum model confidence (default 0.50)',
                   'hold_seconds': 'float — sustained missing-label duration (default 2)'}}

from model_paths import model_path
from marketplace.vendor_patterns import PackageLabelFunction

class Function(PackageLabelFunction):
    function_id = MANIFEST["id"]

    def __init__(self, settings):
        merged = {"weights": model_path("shipping-label.pt")}
        merged.update(settings or {})
        super().__init__(merged)
