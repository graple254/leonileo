from lipana import Lipana
from django.conf import settings


def get_lipana():
    return Lipana(
        api_key=settings.LIPANA_SECRET_KEY,
        environment='production'
    )


def create_payment_link(product, request=None, amount=None):
    """
    Create a Lipana payment link for a product.
    - amount: optional override (e.g. price + delivery fees)
    - request: Django request object, used to build success redirect URL dynamically
    """
    lipana = get_lipana()

    charge = amount or product.discounted_price or product.original_price
    if not charge:
        raise ValueError("Product has no price set. Cannot generate payment link.")

    # Build success redirect URL dynamically
    if request is not None:
        base_url = request.build_absolute_uri('/').rstrip('/')
    else:
        base_url = getattr(settings, 'SITE_BASE_URL', 'https://victorokoth.pythonanywhere.com')

    success_url = f"{base_url}/payment/success/"

    payment_link = lipana.payment_links.create(
        title=product.name,
        description=product.description[:255] if product.description else product.name,
        amount=int(charge),
        currency='KES',
        allow_custom_amount=False,
        success_redirect_url=success_url
    )

    # Lipana returns a slug, not a url key — build the shareable link from it
    return f"https://lipana.dev/pay/{payment_link['slug']}"