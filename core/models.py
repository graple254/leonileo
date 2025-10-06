from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import RegexValidator
from django.db.models.signals import post_save
from django.dispatch import receiver



# ------------------------------
# Track site visitors
# ------------------------------
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


# ------------------------------
# Custom user with roles
# ------------------------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('CUSTOMER', 'Customer'),
        ('MERCHANT', 'Merchant'),
        ('MODERATOR', 'Moderator'),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    def __str__(self):
        return f"{self.username} ({self.role})"


# ------------------------------
# Merchant profile
# ------------------------------
class MerchantProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merchant_profile"
    )
    business_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    whatsapp_number = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message="Enter a valid WhatsApp number (e.g. +254700000000)"
            )
        ]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Merchant Profile"
        verbose_name_plural = "Merchant Profiles"

    def __str__(self):
        return f"{self.business_name} ({self.user.username})"


# ------------------------------
# Categories (for products + moderators)
# ------------------------------
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


# ------------------------------
# Moderator assignments
# ------------------------------
class ModeratorCategory(models.Model):
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "MODERATOR"},
        related_name="moderated_categories"
    )
    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("moderator", "category")

    def __str__(self):
        return f"{self.moderator.username} moderates {self.category.name}"


# ------------------------------
# TimeSlots for clearance sales
# ------------------------------



class TimeSlotManager(models.Manager):
    def auto_refresh_statuses(self):
        """Bulk update all timeslot statuses."""
        updated = 0
        for slot in self.all():
            old_status = slot.status
            slot.update_status()
            if slot.status != old_status:
                updated += 1
        return updated


class TimeSlot(models.Model):
    STATUS_CHOICES = [
        ("waiting", "Waiting"),
        ("live", "Live"),
        ("ended", "Ended"),
    ]

    name = models.CharField(max_length=100, unique=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="waiting")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": "MODERATOR"},
        related_name="created_timeslots"
    )

    objects = TimeSlotManager()

    def __str__(self):
        return f"{self.name} ({self.status})"

    # -------------------------
    # Clean lifecycle logic
    # -------------------------
    def update_status(self):
        now = timezone.now()
        approved_count = self.products.filter(status="approved").count()
        new_status = self.status  # start with current status

        # CASE 1️⃣: Slot already ended
        if now >= self.end_time:
            new_status = "ended"

        # CASE 2️⃣: Slot should go live (start_time reached and enough products)
        elif self.status == "waiting" and now >= self.start_time and approved_count >= 4:
            new_status = "live"

        # CASE 3️⃣: Slot missed its start (not enough products)
        elif self.status == "waiting" and now >= self.start_time and approved_count < 4:
            new_status = "ended"

        # CASE 4️⃣: Live slot that should end
        elif self.status == "live" and now >= self.end_time:
            new_status = "ended"

        # Save only if changed
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])

        return self.status


# ------------------------------
# Products
# ------------------------------
class Product(models.Model):
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField()
    original_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discounted_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    percentage_discount = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    stock_quantity = models.PositiveIntegerField(default=0)  # how many items available
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_percentage_discount(self):
        if self.discounted_price and self.original_price > 0:
            discount = ((self.original_price - self.discounted_price) / self.original_price) * 100
            return round(discount, 2)
        return 0

    def save(self, *args, **kwargs):
        # Auto-update percentage_discount before saving
        self.percentage_discount = self.calculate_percentage_discount()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.percentage_discount}% off)"


    def __str__(self):
        return f"{self.name} ({self.merchant.business_name})"


# ------------------------------
# Product Images
# ------------------------------
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="product_images/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.name}"


from django.core.exceptions import ValidationError

# ------------------------------
# Product-TimeSlot Relationship
# ------------------------------
class ProductTimeSlot(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("removed", "Removed"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="timeslots")
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name="products")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    moderator_comment = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "timeslot")

    def __str__(self):
        return f"{self.product.name} in {self.timeslot.name} ({self.status})"

    # --------------------------
    # Validation rules
    # --------------------------
    def clean(self):
        """Ensure only 'waiting' timeslots can accept new products."""
        if self.timeslot.status not in ["waiting"]:
            raise ValidationError("You can only add or modify products in 'waiting' timeslots.")

    def save(self, *args, **kwargs):
        # Enforce clean() validation every time it’s saved
        self.full_clean()
        super().save(*args, **kwargs)

    # --------------------------
    # Moderator actions
    # --------------------------
    def approve(self, moderator):
        """Approve product for this timeslot"""
        self.status = "approved"
        self.moderator_comment = "Approved automatically."
        self.save()
        AuditLog.objects.create(
            moderator=moderator,
            product_timeslot=self,
            action="approve",
            comment="Approved automatically."
        )

    def reject(self, moderator, comment):
        """Reject product with moderator's comment"""
        self.status = "rejected"
        self.moderator_comment = comment
        self.save()
        AuditLog.objects.create(
            moderator=moderator,
            product_timeslot=self,
            action="reject",
            comment=comment
        )

    def remove(self, moderator, comment):
        """Remove product from this timeslot with comment"""
        self.status = "removed"
        self.moderator_comment = comment
        self.save()
        AuditLog.objects.create(
            moderator=moderator,
            product_timeslot=self,
            action="remove",
            comment=comment
        )


# ------------------------------
# Audit Logs
# ------------------------------
class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("approve", "Approved Product"),
        ("reject", "Rejected Product"),
        ("remove", "Removed Product"),
        ("create_slot", "Created TimeSlot"),
    ]

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    product_timeslot = models.ForeignKey(
        ProductTimeSlot,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        null=True,
        blank=True
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.product_timeslot:
            return f"{self.moderator} {self.action} {self.product_timeslot}"
        return f"{self.moderator} {self.action}"

    # --------------------------
    # History helpers
    # --------------------------
    @classmethod
    def history_for_product(cls, product_id):
        """Return all logs across timeslots for a product"""
        return cls.objects.filter(product_timeslot__product_id=product_id).order_by("-timestamp")

    @classmethod
    def history_for_timeslot(cls, timeslot_id):
        """Return all logs for a specific timeslot"""
        return cls.objects.filter(product_timeslot__timeslot_id=timeslot_id).order_by("-timestamp")




# ------------------------------
# Signals for automatic audit logging
# ------------------------------

@receiver(post_save, sender=TimeSlot)
def log_timeslot_creation(sender, instance, created, **kwargs):
    """Log creation of new timeslots by moderators."""
    if created and instance.created_by:
        AuditLog.objects.create(
            moderator=instance.created_by,
            action="create_slot",
            comment=f"Created timeslot '{instance.name}' from {instance.start_time} to {instance.end_time}"
        )


@receiver(post_save, sender=ProductTimeSlot)
def log_status_change(sender, instance, created, **kwargs):
    """
    Ensure *every* status change on ProductTimeSlot is logged,
    even if it's not triggered via .approve()/.reject()/.remove()
    """
    if created:
        # First time linking product to a slot
        AuditLog.objects.create(
            moderator=None,  # none, since merchant initiated
            product_timeslot=instance,
            action="pending",
            comment="Product submitted and waiting moderation."
        )
    else:
        # If moderator_comment is present and status is not pending
        if instance.status in ["approved", "rejected", "removed"]:
            AuditLog.objects.create(
                moderator=None,  # If you want the actual moderator, use signals differently
                product_timeslot=instance,
                action=instance.status,
                comment=instance.moderator_comment or f"Status set to {instance.status}"
            )


# ------------------------------
# Auto-activate or end timeslots dynamically
# ------------------------------
@receiver(post_save, sender=ProductTimeSlot)
def auto_activate_timeslot(sender, instance, **kwargs):
    """Update timeslot status automatically when product status changes."""
    instance.timeslot.update_status()


# WE need to have original and sale price for products
