"""Independently implemented marketplace plugin; vendor-pattern provenance is documented in docs/research/vendor-inspired-plugins.md."""

MANIFEST = {'id': 'perimeter-climb-review',
 'name': 'Perimeter Climbing-Pose Review',
 'tagline': 'Flags a sustained pose heuristic near a configured perimeter boundary for '
            'verification; it does not identify intent.',
 'category': 'Security & Access',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'boundary': 'camera zone named perimeter_boundary — two-point line in normalized coordinates',
                   'hold_seconds': 'float — sustained pose duration (default 2)',
                   'boundary_margin': 'float — normalized center-to-boundary margin (default '
                                      '0.15)'}}

CAMERA_ZONES = {'boundary': 'perimeter_boundary'}

from marketplace.vendor_patterns import PerimeterClimbFunction

class Function(PerimeterClimbFunction):
    function_id = MANIFEST["id"]
