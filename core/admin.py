# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Visitor


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom admin panel for the User model.
    Extends Django's default UserAdmin but adapts to use our custom User model with 'role'.
    """

    # Fields to display in the admin list view
    list_display = ("username", "email", "role", "is_active", "is_staff", "is_superuser")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")

    # Fields used for searching users in the admin
    search_fields = ("username", "email")

    # Default ordering
    ordering = ("username",)

    # Fieldsets for the detail view of a user
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Roles & Permissions", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Fieldsets for the add user form
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "role"),
        }),
    )


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    """
    Admin panel for tracking visitor logs.
    """
    list_display = ("ip_address", "url_path", "method", "visit_date")
    list_filter = ("method", "visit_date")
    search_fields = ("ip_address", "url_path", "referrer")
    ordering = ("-visit_date",)
