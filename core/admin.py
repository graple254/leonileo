from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.contrib import messages
from django.urls import path
from .models import *


# --------------------------
# Inline Admins
# --------------------------
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


# --------------------------
# Visitor Admin
# --------------------------
@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "url_path", "method", "visit_date")
    search_fields = ("ip_address", "url_path", "user_agent")
    list_filter = ("method", "visit_date")


# --------------------------
# User & Merchant Admin
# --------------------------
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "email")


@admin.register(MerchantProfile)
class MerchantProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "location", "whatsapp_number", "created_at")
    search_fields = ("business_name", "location", "whatsapp_number")
    list_filter = ("created_at",)


# --------------------------
# Category & Moderator Admin
# --------------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(ModeratorCategory)
class ModeratorCategoryAdmin(admin.ModelAdmin):
    list_display = ("moderator", "category")
    list_filter = ("category", "moderator")


# --------------------------
# TimeSlot Admin
# --------------------------
@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "start_time", "end_time", "created_by")
    list_filter = ("status", "start_time", "end_time")
    search_fields = ("name",)
    ordering = ("-start_time",)


# --------------------------
# Product Admin
# --------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "merchant", "category", "price", "stock_quantity", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("name", "merchant__business_name")
    inlines = [ProductImageInline]


# --------------------------
# ProductTimeSlot Admin (customized with buttons + bulk actions)
# --------------------------
@admin.register(ProductTimeSlot)
class ProductTimeSlotAdmin(admin.ModelAdmin):
    list_display = ("product", "timeslot", "status", "updated_at", "moderator_actions")
    list_filter = ("status", "timeslot", "updated_at")
    search_fields = ("product__name", "timeslot__name")

    # --------------------------
    # Action buttons (inline)
    # --------------------------
    def moderator_actions(self, obj):
        if obj.status in ["approved", "rejected", "removed"]:
            return f"✅ {obj.status.capitalize()}"
        return format_html(
            '<a class="button" href="{}">✅ Approve</a>&nbsp;'
            '<a class="button" href="{}">❌ Reject</a>&nbsp;'
            '<a class="button" href="{}">🗑️ Remove</a>',
            f"approve/{obj.id}",
            f"reject/{obj.id}",
            f"remove/{obj.id}",
        )
    moderator_actions.short_description = "Actions"

    # --------------------------
    # Bulk actions
    # --------------------------
    actions = ["approve_selected", "reject_selected", "remove_selected"]

    def approve_selected(self, request, queryset):
        for pts in queryset:
            pts.approve(request.user)
        self.message_user(request, f"✅ Approved {queryset.count()} products.", messages.SUCCESS)
    approve_selected.short_description = "✅ Approve selected products"

    def reject_selected(self, request, queryset):
        for pts in queryset:
            pts.reject(request.user, comment="Rejected via bulk action.")
        self.message_user(request, f"❌ Rejected {queryset.count()} products.", messages.WARNING)
    reject_selected.short_description = "❌ Reject selected products"

    def remove_selected(self, request, queryset):
        for pts in queryset:
            pts.remove(request.user, comment="Removed via bulk action.")
        self.message_user(request, f"🗑️ Removed {queryset.count()} products.", messages.ERROR)
    remove_selected.short_description = "🗑️ Remove selected products"

    # --------------------------
    # Custom URLs for buttons
    # --------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("approve/<int:pk>", self.admin_site.admin_view(self.approve_view), name="pts-approve"),
            path("reject/<int:pk>", self.admin_site.admin_view(self.reject_view), name="pts-reject"),
            path("remove/<int:pk>", self.admin_site.admin_view(self.remove_view), name="pts-remove"),
        ]
        return custom_urls + urls

    def approve_view(self, request, pk):
        obj = ProductTimeSlot.objects.get(pk=pk)
        obj.approve(request.user)
        self.message_user(request, f"✅ Approved {obj.product.name} in {obj.timeslot.name}", messages.SUCCESS)
        return self.response_post_save_change(request, obj)

    def reject_view(self, request, pk):
        obj = ProductTimeSlot.objects.get(pk=pk)
        obj.reject(request.user, comment="Rejected via button.")
        self.message_user(request, f"❌ Rejected {obj.product.name} in {obj.timeslot.name}", messages.WARNING)
        return self.response_post_save_change(request, obj)

    def remove_view(self, request, pk):
        obj = ProductTimeSlot.objects.get(pk=pk)
        obj.remove(request.user, comment="Removed via button.")
        self.message_user(request, f"🗑️ Removed {obj.product.name} in {obj.timeslot.name}", messages.ERROR)
        return self.response_post_save_change(request, obj)


# --------------------------
# ProductImage Admin
# --------------------------
@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "uploaded_at")
    search_fields = ("product__name",)


# --------------------------
# AuditLog Admin
# --------------------------
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("moderator", "product_timeslot", "action", "comment", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("moderator__username", "product_timeslot__product__name")
    ordering = ("-timestamp",)
