from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone

###################################################################################################
# Visitor Model
# -----------------------------------------------------------------------------------------------
# - Purpose:
#     * Lightweight request-level tracking model to capture anonymous visits to pages.
#     * Useful for analytics, debugging, abuse detection, and measuring traffic to product pages.
# - Typical usage:
#     * Created by a middleware, view decorator, or async task whenever a page is requested.
#     * Not intended as a replacement for full analytics platforms, but for simple, app-native insights.
# - Field notes:
#     * ip_address    → GenericIPAddressField supports IPv4 and IPv6; consider hashing for privacy.
#     * location      → Best-effort (e.g., geoip lookup); avoid storing precise home addresses.
#     * user_agent    → TextField to accommodate long UA strings.
#     * url_path      → Stores the requested path (max_length=500 to support long query strings if needed).
#     * method        → HTTP method (GET/POST/etc.); consider limiting choices for consistency.
#     * referrer      → URLField for the referer header (may be empty or manipulated).
#     * visit_date    → Defaults to timezone.now for accurate event time; indexed queries recommended.
# - Privacy & compliance:
#     * Treat ip_address and user_agent as potentially personal data in some jurisdictions.
#     * Consider anonymization (e.g., truncation or hashing) and a data retention/purge policy.
#     * Document retention period and provide tooling to delete old records (GDPR/CCPA concerns).
# - Performance & scaling:
#     * High-traffic sites should write visits asynchronously (Celery, Kafka) and avoid synchronous DB writes.
#     * Add DB indexes on visit_date, ip_address, and url_path if querying/filtering frequently.
#     * Consider sampling (store a subset) or aggregating counts to limit table growth.
# - Future improvements:
#     * Add a nullable ForeignKey to settings.AUTH_USER_MODEL to link authenticated users.
#     * Add a "source" or "event_type" field to distinguish bot traffic, pageviews, clicks, API calls.
#     * Enforce method choices or normalize stored values for easier querying.
###################################################################################################

class Visitor(models.Model):
      ip_address = models.GenericIPAddressField(blank=True, null=True)
      location = models.CharField(max_length=255, blank=True, null=True)
      user_agent = models.TextField(blank=True, null=True)
      url_path = models.CharField(max_length=500, blank=True, null=True)
      method = models.CharField(max_length=10, blank=True, null=True)
      referrer = models.URLField(blank=True, null=True)
      visit_date = models.DateTimeField(default=timezone.now, blank=True, null=True)

      def __str__(self):
            return f"{self.ip_address} visited {self.url_path} on {self.visit_date}"


###################################################################################################
# Custom User Model
# -----------------------------------------------------------------------------------------------
# - We extend Django's AbstractUser instead of using the default User model.
# - Reason: gives us flexibility to add new fields (like role) without breaking authentication.
# - Roles differentiate the type of users in our platform:
#     * MERCHANT   → owns a business, uploads products, manages clearance sales
#     * CUSTOMER   → only browses products and clicks WhatsApp links to purchase directly
#     * MODERATOR  → oversees categories, approves/rejects products, ensures quality and trust
# - Keeping role as a single field avoids messy profile hacks and simplifies role-based access.
###################################################################################################

class User(AbstractUser):
    ROLE_CHOICES = (
        ('MERCHANT', 'Merchant'),
        ('CUSTOMER', 'Customer'),
        ('MODERATOR', 'Moderator'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    
    # Override groups field with a unique related_name
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_name='core_user_groups',
        related_query_name='core_user',
    )
    
    # Override user_permissions field with a unique related_name
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='core_user_permissions',
        related_query_name='core_user',
    )

    def __str__(self):
        return f"{self.username} ({self.role})"


###################################################################################################
# Category Model
# -----------------------------------------------------------------------------------------------
# - Categories are the backbone of product organization (e.g., Electronics, Fashion, Home Goods).
# - Every product MUST belong to one category.
# - Moderators are assigned categories so they can focus on their area of expertise.
# - Categories can be freely added/removed from the Django admin panel (no hardcoding).
# - This ensures scalability: as new industries or niches appear, admins can add them instantly.
###################################################################################################

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


###################################################################################################
# Merchant Profile
# -----------------------------------------------------------------------------------------------
# - Extends the User model for MERCHANTS only.
# - Stores business-related information (customers and moderators don’t need these fields).
# - One-to-one relationship: every merchant user has exactly one MerchantProfile.
# - Fields included:
#     * business_name    → public-facing brand name of the merchant
#     * location         → physical shop or pickup location
#     * whatsapp_number  → key contact channel (direct selling without cart/checkout system)
# - This design allows easy expansion in the future: e.g. add tax IDs, bank info, verification status.
###################################################################################################

class MerchantProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merchant_profile",
        limit_choices_to={'role': 'MERCHANT'}
    )
    business_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, help_text="Physical location or pickup point")
    whatsapp_number = models.CharField(max_length=20, help_text="Merchant's WhatsApp contact")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Merchant: {self.business_name}"


###################################################################################################
# Moderator Profile
# -----------------------------------------------------------------------------------------------
# - Extends the User model for MODERATORS only.
# - Each moderator is assigned specific categories to manage (Many-to-Many relationship).
# - This ensures workload distribution and specialization:
#     * Example: Moderator A handles Electronics, Moderator B handles Fashion.
# - Moderators’ key responsibilities:
#     * Approve or reject products
#     * Remove inappropriate or duplicate listings
#     * Communicate reasons for actions via ModerationLog
###################################################################################################

class ModeratorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="moderator_profile",
        limit_choices_to={'role': 'MODERATOR'},
    )
    categories = models.ManyToManyField(
        Category,
        related_name="moderators",
        blank=True,
        help_text="Product categories this moderator is responsible for"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Moderator: {self.user.username}"


###################################################################################################
# TimeSlot
# -------------------------------------------------------------------------------------------------
# Represents a "flash sale" window during which merchants can sell their clearance products.
#
# Lifecycle:
# - waiting: Visible only to merchants, they can submit products into this slot.
# - ready: Visible to customers once enough products are approved by moderators.
# - live: Automatically inferred when start_time <= now <= end_time (handled in views/services).
# - expired: After end_time, slot and products go offline (can still be kept for history).
#
# Moderators responsible for creating/managing TimeSlots are simply those assigned
# to the hidden category "TS" (TimeSlot Manager).
###################################################################################################

class TimeSlot(models.Model):
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    intensity = models.CharField(
        max_length=20,
        choices=[
            ("LOW", "Low"),
            ("MEDIUM", "Medium"),
            ("HIGH", "High"),
            ("EXTREME", "Extreme")
        ],
        help_text="Represents how juicy the deals are (e.g., 10% vs 50% off)."
    )

    premium = models.BooleanField(
        default=False,
        help_text="Future use: merchants may pay extra to access premium slots."
    )

    # Lifecycle booleans
    waiting = models.BooleanField(
        default=True,
        help_text="Slot open for merchants to list products, not yet visible to customers."
    )
    ready = models.BooleanField(
        default=False,
        help_text="Slot has enough approved products and is visible as upcoming to customers."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Slot {self.start_time} - {self.end_time} ({self.intensity})"

    ######################################################################
    # Business logic helper methods (future use in views/services)
    ######################################################################
    def is_live(self):
        """Check if slot is currently live based on time."""
        from django.utils import timezone
        now = timezone.now()
        return self.ready and self.start_time <= now <= self.end_time

    def is_expired(self):
        """Check if slot has ended."""
        from django.utils import timezone
        return timezone.now() > self.end_time



###################################################################################################
# Product
# -----------------------------------------------------------------------------------------------
# - Core model representing items merchants want to clear.
# - Each product belongs to:
#     * One merchant (who owns the product)
#     * One category (for organization and moderation)
#     * One timeslot (to enforce time-bound sales)
# - Prices:
#     * original_price   → the normal value of the item
#     * clearance_price  → discounted price for flash sale
# - approved: moderators must approve before products go live.
# - whatsapp_link: direct chat between customer and merchant (avoids need for cart/checkout).
###################################################################################################

class Product(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="products"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name="products"
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    clearance_price = models.DecimalField(max_digits=10, decimal_places=2)

    slot = models.ForeignKey(
        TimeSlot,
        on_delete=models.CASCADE,
        related_name="products"
    )

    whatsapp_link = models.URLField(help_text="Direct WhatsApp chat link for customers")

    approved = models.BooleanField(default=False, help_text="Moderators must approve products")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.clearance_price}"


###################################################################################################
# Product Images
# -----------------------------------------------------------------------------------------------
# - Each product can have multiple images to improve trust and transparency.
# - Implemented as a separate model for flexibility:
#     * Easier to add/remove images dynamically.
#     * Avoids bloating Product model with static image fields.
# - We recommend limiting to 5 images in forms/views (logic layer), but the DB itself is unlimited.
###################################################################################################

class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images"
    )
    image = models.ImageField(upload_to="product_images/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.name}"


###################################################################################################
# Moderation Log
# -----------------------------------------------------------------------------------------------
# - Tracks all decisions made by moderators on specific products.
# - Purpose:
#     * Transparency for merchants (why was my product rejected?)
#     * Accountability for moderators (history of actions taken).
# - Fields:
#     * action → Approved, Rejected, Removed
#     * reason → explanation provided to merchant
# - This is crucial for building trust and maintaining platform integrity.
###################################################################################################

class ModerationLog(models.Model):
    moderator = models.ForeignKey(
        ModeratorProfile,
        on_delete=models.SET_NULL,
        null=True
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    action = models.CharField(
        max_length=20,
        choices=[("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("REMOVED", "Removed")]
    )

    reason = models.TextField(
        blank=True, null=True,
        help_text="Feedback for the merchant explaining moderator decision"
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.moderator} - {self.action} - {self.product.name}"
