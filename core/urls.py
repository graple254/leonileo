from django.urls import path
from .views import *

urlpatterns = [
    # Authentication
    path("signup/", signup_view, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),

    # Customer
    path("", index, name="index"),
    path("product/<int:product_id>/", product_detail, name="product_detail"),

    # Merchant URLs
    path("merchant/dashboard/", merchant_dashboard, name="merchant_dashboard"),
    path("merchant/products/", merchant_products, name="merchant_products"),
    path("merchant/create-profile/", create_merchant_profile, name="create_merchant_profile"),
    path("merchant/product/<int:product_id>/generate-link/", generate_payment_link, name="generate_payment_link"),
    path("payment/success/", payment_success, name="payment_success"),

    # Moderator
    path("moderator/dashboard/", moderator_dashboard, name="moderator_dashboard"),
]
