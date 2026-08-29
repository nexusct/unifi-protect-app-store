"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'anonymous-zone-funnel',
 'name': 'Anonymous Zone Funnel',
 'tagline': 'Builds an anonymous entrance-to-display-to-product-to-checkout progression ledger '
            'without demographic inference.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'entrance_zone': 'polygon — funnel entrance stage',
                   'display_zone': 'polygon — display-engagement stage',
                   'product_zone': 'polygon — product-area stage',
                   'checkout_zone': 'polygon — checkout stage',
                   'digest_seconds': 'int — digest interval (default 300)'}}

CAMERA_ZONES = {'entrance_zone': 'funnel_entrance',
 'display_zone': 'funnel_display',
 'product_zone': 'funnel_product',
 'checkout_zone': 'funnel_checkout'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'zone_funnel'
    profile = {'zones': {'entrance': 'funnel_entrance',
           'display': 'funnel_display',
           'product': 'funnel_product',
           'checkout': 'funnel_checkout'},
 'digest_seconds': 300}
