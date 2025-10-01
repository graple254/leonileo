from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from .models import *
from django.db import transaction
from .decorators import role_required
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation


User = get_user_model()


# AUTHENTICATION ###################################################################################################
def signup_view(request):
    """
    Handle user registration.
    """
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        role = request.POST.get("role", "CUSTOMER")  # Default role = CUSTOMER

        # Basic validation
        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect("signup")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return redirect("signup")

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
        )
        messages.success(request, "Account created successfully! Please log in.")
        return redirect("login")

    return render(request, "files/auth/signup.html")


def login_view(request):
    """
    Handle user login.
    """
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user:
            if user.is_active:
                login(request, user)
                messages.success(request, f"Welcome back {user.username}!")

                # Redirect based on role
                if user.role == "MERCHANT":
                    return redirect("merchant_dashboard")
                elif user.role == "MODERATOR":
                    return redirect("moderator_dashboard")
                else:
                    return redirect("index")
            else:
                messages.error(request, "Your account is inactive. Contact support.")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "files/auth/login.html")


@login_required
def logout_view(request):
    """
    Handle user logout.
    """
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("login")


# CUSTOMER VIEWS ###################################################################################################
def index(request):
    return render(request, "files/customer/index.html")


# MERCHANT VIEWS ###################################################################################################

# ==========================================================================================
# INSTRUCTIONS FOR COPILOT:
# ==========================================================================================
# Context:
# - We only want 3 merchant views:
#   1. merchant_dashboard(request)   
#       * Show analytics + performance (basic counts, views, sales)
#       * If profile missing -> redirect to create_merchant_profile
#       * Allow editing of merchant profile (through a modal form in dashboard template)
#   2. create_merchant_profile(request) 
#       * Setup merchant profile if missing
#   3. merchant_products(request) 
#       * Handle ALL product-related operations
#
# Models already in codebase:
# - User (role-based: CUSTOMER, MERCHANT, MODERATOR)
# - MerchantProfile (business_name, location, whatsapp_number)
# - Product (merchant FK, category FK, name, description, original_price, discounted_price,
#            percentage_discount [auto-calculated], stock_quantity, created_at)
# - Category, TimeSlot, ProductStatus, AuditLog, etc. (already defined above in models.py)
#
# Requirements:
# ------------------------------------------------------------------------------------------
# merchant_dashboard:
# - Show profile details, analytics (e.g. product count, approved vs rejected products).
# - Include ability to EDIT profile inline using a modal form (update merchant_profile).
#
# merchant_products:
# - This SINGLE view should handle:
#   a) Adding new products (POST request)
#   b) Listing all merchant products (GET request)
#   c) Assigning/removing products to/from time slots
#   d) Viewing feedback from moderators (status + comments from ProductStatus)
#   e) Viewing history & performance (use ProductStatus + AuditLog + query counts)
#
# Constraints:
# - KEEP IT LEAN: don’t create multiple views for each small action.
# - Use conditionals inside merchant_products to differentiate operations (GET/POST).
# - Use Django messages framework for feedback.
# - Redirect back to merchant_products after every action.
# - Validate ownership: merchants should only manage their own products.
#
# Example flow:
# - GET: render "files/merchant/products.html" with:
#       * merchant’s product list
#       * available time slots (status=waiting or live)
#       * product statuses + feedback
# - POST:
#       * If "add_product" in request.POST -> create product
#       * If "assign_timeslot" in request.POST -> assign product to slot
#       * If "remove_timeslot" in request.POST -> remove product from slot
#       * If "edit_profile" in request.POST -> update MerchantProfile from dashboard modal
#
# DO NOT invent new models or views. Extend from what’s already written.
# ==========================================================================================


@login_required
@role_required("MERCHANT")
def merchant_dashboard(request):
    if request.user.role != "MERCHANT":
        messages.error(request, "Unauthorized access.")
        return redirect("index")

    try:
        merchant_profile = request.user.merchant_profile
    except MerchantProfile.DoesNotExist:
        messages.info(request, "Please complete your merchant profile first.")
        return redirect("create_merchant_profile")

    # ----------------------
    # Profile Editing
    # ----------------------
    if request.method == "POST" and request.POST.get("action") == "edit_profile":
        merchant_profile.business_name = request.POST.get("business_name")
        merchant_profile.location = request.POST.get("location")
        merchant_profile.whatsapp_number = request.POST.get("whatsapp_number")
        merchant_profile.save()
        messages.success(request, "Profile updated successfully!")
        return redirect("merchant_dashboard")

    # ----------------------
    # Dashboard Analytics
    # ----------------------
    products = merchant_profile.products.all()
    products_count = products.count()
    slots_count = ProductTimeSlot.objects.filter(product__merchant=merchant_profile).count()

    # Status breakdown
    approved_count = ProductTimeSlot.objects.filter(
        product__merchant=merchant_profile, status="approved"
    ).count()
    rejected_count = ProductTimeSlot.objects.filter(
        product__merchant=merchant_profile, status="rejected"
    ).count()
    pending_count = ProductTimeSlot.objects.filter(
        product__merchant=merchant_profile, status="pending"
    ).count()
    removed_count = ProductTimeSlot.objects.filter(
        product__merchant=merchant_profile, status="removed"
    ).count()

    # ----------------------
    # Latest activity
    # ----------------------
    latest_products = products.order_by("-created_at")[:5]
    logs_qs = AuditLog.objects.filter(product_timeslot__product__merchant=merchant_profile).order_by("-timestamp")

    paginator = Paginator(logs_qs, 5)  # paginate logs
    page_number = request.GET.get("page")
    logs_page = paginator.get_page(page_number)

    context = {
        "merchant": merchant_profile,
        "products_count": products_count,
        "slots_count": slots_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "pending_count": pending_count,
        "removed_count": removed_count,
        "latest_products": latest_products,
        "logs_page": logs_page,
    }
    return render(request, "files/merchant/dashboard.html", context)




# ------------------------------
# Merchant Products
# ------------------------------

from django.utils import timezone

@login_required 
@role_required("MERCHANT")
def merchant_products(request):
    if request.user.role != "MERCHANT":
        messages.error(request, "Unauthorized access.")
        return redirect("index")

    merchant_profile = request.user.merchant_profile

    # ----------------------
    # POST actions
    # ----------------------
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_product":
            try:
                with transaction.atomic():
                    product = Product.objects.create(
                        merchant=merchant_profile,
                        category_id=int(request.POST.get("category")),
                        name=request.POST.get("name"),
                        description=request.POST.get("description"),
                        original_price=Decimal(request.POST.get("original_price")),
                        discounted_price=Decimal(request.POST.get("discounted_price")),
                        stock_quantity=int(request.POST.get("stock_quantity") or 0),
                    )

                    images = request.FILES.getlist("images")
                    if len(images) < 5:
                        raise ValueError("You must upload at least 5 images per product.")

                    for img in images:
                        ProductImage.objects.create(product=product, image=img)

                    messages.success(request, "Product added successfully!")
            except Exception as e:
                messages.error(request, f"Error adding product: {e}")
            return redirect("merchant_products")

        elif action == "edit_product":
            try:
                product = get_object_or_404(
                    Product, id=request.POST.get("product_id"), merchant=merchant_profile
                )

                # Basic fields
                name = request.POST.get("name")
                description = request.POST.get("description")
                category_id = request.POST.get("category")
                original_price = request.POST.get("original_price")
                discounted_price = request.POST.get("discounted_price")
                stock_quantity = request.POST.get("stock_quantity")

                if name is not None:
                    product.name = name.strip()
                if description is not None:
                    product.description = description

                if category_id:
                    product.category_id = int(category_id)

                if original_price not in (None, ""):
                    product.original_price = Decimal(original_price)
                if discounted_price not in (None, ""):
                    product.discounted_price = Decimal(discounted_price)

                if (
                    product.original_price is not None
                    and product.discounted_price is not None
                    and product.discounted_price > product.original_price
                ):
                    raise ValueError("Discounted price cannot be greater than original price.")

                if stock_quantity not in (None, ""):
                    sq = int(stock_quantity)
                    if sq < 0:
                        raise ValueError("Stock quantity cannot be negative.")
                    product.stock_quantity = sq

                product.save()
                messages.success(request, "Product updated successfully!")
            except (InvalidOperation, ValueError) as e:
                messages.error(request, f"Error updating product: {e}")
            except Exception as e:
                messages.error(request, f"Unexpected error: {e}")
            return redirect("merchant_products")

        elif action == "assign_timeslot":
            try:
                product = get_object_or_404(
                    Product, id=request.POST.get("product_id"), merchant=merchant_profile
                )
                timeslot_id = request.POST.get("timeslot_id")
                timeslot = get_object_or_404(TimeSlot, id=timeslot_id)

                # ✅ Validation: block assignment if slot has started or status is ready
                if timeslot.start_time <= timezone.now():
                    messages.error(request, "You cannot assign products to a slot that has already started.")
                    return redirect("merchant_products")

                if timeslot.status == "ready":
                    messages.error(request, "You cannot assign products to a slot marked as ready.")
                    return redirect("merchant_products")

                if ProductTimeSlot.objects.filter(product=product, timeslot=timeslot).exists():
                    messages.info(request, "This product is already submitted for that timeslot.")
                else:
                    ProductTimeSlot.objects.create(
                        product=product,
                        timeslot=timeslot,
                        status="pending",
                    )
                    messages.success(request, "Product submitted for moderation!")
            except Exception as e:
                messages.error(request, f"Error: {e}")
            return redirect("merchant_products")

        elif action == "remove_from_timeslot":
            pts_id = request.POST.get("pts_id")
            pts = get_object_or_404(ProductTimeSlot, id=pts_id, product__merchant=merchant_profile)
            pts.delete()
            messages.success(request, "Product withdrawn from timeslot.")
            return redirect("merchant_products")

        elif action in ("delete_product", "remove_product"):
            try:
                with transaction.atomic():
                    product = get_object_or_404(
                        Product, id=request.POST.get("product_id"), merchant=merchant_profile
                    )
                    for img in product.images.all():
                        try:
                            img.image.delete(save=False)
                        except Exception:
                            pass
                        img.delete()
                    ProductTimeSlot.objects.filter(product=product).delete()
                    product.delete()
                    messages.success(request, "Product deleted successfully.")
            except Exception as e:
                messages.error(request, f"Error deleting product: {e}")
            return redirect("merchant_products")

    # ----------------------
    # GET requests
    # ----------------------
    products_qs = merchant_profile.products.all().prefetch_related("images", "timeslots")
    paginator = Paginator(products_qs, 10)
    page_number = request.GET.get("page")
    products_page = paginator.get_page(page_number)

    current_slots = (
        TimeSlot.objects.filter(products__product__merchant=merchant_profile)
        .exclude(end_time__lt=timezone.now())
        .distinct()
        .order_by("start_time")
    )




    # ✅ Past slots (already ended)
    history_slots = (
        TimeSlot.objects.filter(products__product__merchant=merchant_profile)
        .filter(end_time__lt=timezone.now())
        .distinct()
        .order_by("-start_time")
    )

    # ✅ Upcoming slots (future + not ready)
    upcoming_slots = (
        TimeSlot.objects.filter(start_time__gt=timezone.now())
        .exclude(status="ready")
        .order_by("start_time")
    )

    categories = Category.objects.all().order_by("name")

    logs_qs = AuditLog.objects.filter(
        product_timeslot__product__merchant=merchant_profile
    ).select_related("product_timeslot")
    logs_paginator = Paginator(logs_qs.order_by("-timestamp"), 5)
    logs_page = logs_paginator.get_page(request.GET.get("log_page"))

    context = {
        "merchant": merchant_profile,
        "products_page": products_page,
        "categories": categories,
        "logs_page": logs_page,
        "history_slots": history_slots,
        "upcoming_slots": upcoming_slots,
        "current_slots": current_slots,
    }
    return render(request, "files/merchant/products.html", context)




@login_required
@role_required("MERCHANT")
def create_merchant_profile(request):
    """Create merchant profile if it doesn't exist."""
    if hasattr(request.user, "merchant_profile"):
        messages.info(request, "You already have a profile.")
        return redirect("merchant_dashboard")

    if request.method == "POST":
        business_name = request.POST.get("business_name")
        location = request.POST.get("location")
        whatsapp_number = request.POST.get("whatsapp_number")

        if not business_name or not location or not whatsapp_number:
            messages.error(request, "All fields are required.")
            return redirect("create_merchant_profile")

        MerchantProfile.objects.create(
            user=request.user,
            business_name=business_name,
            location=location,
            whatsapp_number=whatsapp_number
        )
        messages.success(request, "Profile created successfully!")
        return redirect("merchant_dashboard")

    return render(request, "files/merchant/create_profile.html")


# MODERATOR VIEWS ##################################################################################################
@login_required
@role_required("MODERATOR")
def moderator_dashboard(request):
    """
    Moderator dashboard restricted to MODERATOR users only.
    """
    return render(request, "files/moderator/office.html")
