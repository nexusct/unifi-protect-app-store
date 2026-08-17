"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'queue-abandonment-review',
 'name': 'Queue Abandonment Review',
 'tagline': 'Flags an anonymous track that leaves a configured queue after sustained waiting '
            'without entering the service zone.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'queue_zone': 'camera zone named queue — normalized polygon',
                   'service_zone': 'camera zone named service — normalized polygon',
                   'minimum_wait_seconds': 'int — wait required before review (default 60)',
                   'missing_grace_seconds': 'float — track disappearance grace period (default 3)'}}

CAMERA_ZONES = {'queue_zone': 'queue', 'service_zone': 'service'}

from marketplace.vendor_patterns import QueueAbandonmentFunction

class Function(QueueAbandonmentFunction):
    function_id = MANIFEST["id"]
