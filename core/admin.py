from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active', 'is_staff', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)

    # Add 'role' field to the user creation/edit forms
    fieldsets = UserAdmin.fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )

@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'url_path', 'method', 'visit_date', 'location')
    list_filter = ('method', 'visit_date')
    search_fields = ('ip_address', 'url_path', 'location', 'user_agent')
    date_hierarchy = 'visit_date'
    readonly_fields = ('visit_date',)
    ordering = ('-visit_date',)

    def has_add_permission(self, request):
        # Visitors should only be created by the system, not manually
        return False

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'product_count')
    search_fields = ('name', 'description')
    ordering = ('name',)

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Number of Products'

@admin.register(MerchantProfile)
class MerchantProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'user', 'location', 'whatsapp_number', 'product_count', 'created_at')
    list_filter = ('created_at', 'location')
    search_fields = ('business_name', 'location', 'whatsapp_number', 'user__username')
    ordering = ('-created_at',)
    raw_id_fields = ('user',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(role='MERCHANT')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Total Products'

    def get_queryset(self, request):
        # Optimize the queryset to avoid multiple DB queries
        return super().get_queryset(request).select_related('user')

@admin.register(ModeratorProfile)
class ModeratorProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_categories', 'action_count', 'created_at')
    list_filter = ('created_at', 'categories')
    search_fields = ('user__username', 'categories__name')
    filter_horizontal = ('categories',)  # Better interface for managing many-to-many
    raw_id_fields = ('user',)
    ordering = ('-created_at',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(role='MODERATOR')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_categories(self, obj):
        return ", ".join(cat.name for cat in obj.categories.all())
    get_categories.short_description = 'Assigned Categories'

    def action_count(self, obj):
        return obj.moderationlog_set.count()
    action_count.short_description = 'Moderation Actions'

    def get_queryset(self, request):
        # Optimize queries
        return super().get_queryset(request).prefetch_related('categories').select_related('user')

@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('get_slot_period', 'intensity', 'premium', 'status', 'product_count')
    list_filter = ('intensity', 'premium', 'waiting', 'ready', 'created_at')
    search_fields = ('intensity',)
    ordering = ('-start_time',)

    fieldsets = (
        ('Timing', {
            'fields': ('start_time', 'end_time')
        }),
        ('Slot Details', {
            'fields': ('intensity', 'premium')
        }),
        ('Status', {
            'fields': ('waiting', 'ready')
        })
    )

    def get_slot_period(self, obj):
        return f"{obj.start_time.strftime('%Y-%m-%d %H:%M')} - {obj.end_time.strftime('%H:%M')}"
    get_slot_period.short_description = 'Time Period'

    def status(self, obj):
        if obj.is_expired():
            return 'Expired'
        if obj.is_live():
            return 'Live'
        if obj.ready:
            return 'Ready'
        return 'Waiting'
    status.short_description = 'Current Status'

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Products'

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image', 'uploaded_at')
    readonly_fields = ('uploaded_at',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'merchant', 'category', 'original_price', 'clearance_price', 
                   'slot_status', 'approved', 'created_at')
    list_filter = ('approved', 'category', 'slot__intensity', 'created_at')
    search_fields = ('name', 'description', 'merchant__business_name')
    raw_id_fields = ('merchant', 'category', 'slot')
    ordering = ('-created_at',)
    inlines = [ProductImageInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description')
        }),
        ('Business Details', {
            'fields': ('merchant', 'category', 'original_price', 'clearance_price', 'whatsapp_link')
        }),
        ('Time Slot', {
            'fields': ('slot',)
        }),
        ('Moderation', {
            'fields': ('approved',)
        })
    )

    def slot_status(self, obj):
        if obj.slot.is_expired():
            return 'Expired'
        if obj.slot.is_live():
            return 'Live'
        if obj.slot.ready:
            return 'Ready'
        return 'Waiting'
    slot_status.short_description = 'Slot Status'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('merchant', 'category', 'slot')

@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display = ('moderator', 'product', 'action', 'timestamp')
    list_filter = ('action', 'timestamp', 'moderator')
    search_fields = ('product__name', 'moderator__user__username', 'reason')
    raw_id_fields = ('moderator', 'product')
    readonly_fields = ('timestamp',)
    ordering = ('-timestamp',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'moderator__user',
            'product'
        )
