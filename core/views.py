from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from .models import *
from django.db import transaction
from .decorators import role_required
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
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

###########################################################################
# Merchant Products and Time slots Management
############################################################################
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from django.shortcuts import get_object_or_404

@login_required 
@role_required("MERCHANT")
def merchant_products(request):
    merchant_profile = request.user.merchant_profile

    # ----------------------
    # POST Actions
    # ----------------------
    if request.method == "POST":
        action = request.POST.get("action")

        # 1️⃣ Add Product
        if action == "add_product":
            try:
                with transaction.atomic():
                    product = Product.objects.create(
                        merchant=merchant_profile,
                        category_id=int(request.POST.get("category")) if request.POST.get("category") else None,
                        name=request.POST.get("name"),
                        description=request.POST.get("description"),
                        original_price=Decimal(request.POST.get("original_price")) if request.POST.get("original_price") else None,
                        discounted_price=Decimal(request.POST.get("discounted_price")) if request.POST.get("discounted_price") else None,
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

        # 2️⃣ Assign Multiple Products to TimeSlot
        elif action == "assign_timeslot":
            try:
                timeslot_id = request.POST.get("timeslot_id")
                timeslot = get_object_or_404(TimeSlot, id=timeslot_id)

                # ✅ Only allow assigning into waiting slots
                if timeslot.status != "waiting":
                    messages.error(request, "This timeslot is not open for listing.")
                    return redirect("merchant_products")

                product_ids = request.POST.getlist("product_ids")
                if not product_ids:
                    messages.error(request, "No products selected.")
                    return redirect("merchant_products")

                with transaction.atomic():
                    # ✅ Get already assigned products for this timeslot
                    existing_ids = set(
                        ProductTimeSlot.objects.filter(timeslot=timeslot, product_id__in=product_ids)
                        .values_list("product_id", flat=True)
                    )

                    created_count = 0
                    skipped_count = 0

                    for pid in product_ids:
                        if pid in existing_ids:
                            skipped_count += 1
                            continue  # skip already listed

                        product = get_object_or_404(Product, id=pid, merchant=merchant_profile)

                        ProductTimeSlot.objects.create(
                            product=product,
                            timeslot=timeslot,
                            status="pending"
                        )
                        created_count += 1

                # ✅ Give feedback summary
                msg = f"{created_count} products submitted."
                if skipped_count:
                    msg += f" {skipped_count} already listed and skipped."

                messages.success(request, msg)

            except Exception as e:
                messages.error(request, f"Error assigning products: {e}")

            return redirect("merchant_products")


        # 3️⃣ Remove product from a timeslot
        elif action == "remove_from_timeslot":
            pts_id = request.POST.get("pts_id")
            pts = get_object_or_404(ProductTimeSlot, id=pts_id, product__merchant=merchant_profile)
            pts.delete()
            messages.success(request, "Product withdrawn from timeslot.")
            return redirect("merchant_products")

        # 4️⃣ Delete Product (full delete) - kept but deletes images and related pts
        elif action in ("delete_product", "remove_product"):
            try:
                with transaction.atomic():
                    product = get_object_or_404(Product, id=request.POST.get("product_id"), merchant=merchant_profile)
                    # delete image files safely
                    for img in product.images.all():
                        try:
                            img.image.delete(save=False)
                        except Exception:
                            pass
                        img.delete()
                    # mark related product-timeslots removed to preserve history instead of hard delete
                    ProductTimeSlot.objects.filter(product=product).update(status="removed", moderator_comment="Product deleted by merchant")
                    product.delete()
                    messages.success(request, "Product deleted successfully.")
            except Exception as e:
                messages.error(request, f"Error deleting product: {e}")
            return redirect("merchant_products")

    # ----------------------
    # GET: Dashboard Data
    # ----------------------

    # make sure timeslot statuses are up-to-date
    try:
        TimeSlot.objects.auto_refresh_statuses()
    except Exception:
        # don't block UI if manager method fails for some reason
        pass

    now = timezone.now()

    # 1️⃣ All waiting (open) slots → where merchants can list
    # show waiting slots that start in future (open for listing)
    available_slots = TimeSlot.objects.filter(
        status="waiting"
    ).order_by("start_time")

    # 2️⃣ Upcoming (waiting) slots merchant joined but not yet live
    upcoming_slots = TimeSlot.objects.filter(
        products__product__merchant=merchant_profile,
        status="waiting"
    ).distinct().order_by("start_time")

    # 3️⃣ Live slots merchant is part of
    live_slots = TimeSlot.objects.filter(
        products__product__merchant=merchant_profile,
        status="live"
    ).distinct().order_by("start_time")

    # 4️⃣ Ended slots merchant participated in (status ended or end_time < now)
    ended_slots = TimeSlot.objects.filter(
        Q(status="ended") | Q(end_time__lt=now),
        products__product__merchant=merchant_profile
    ).distinct().order_by("-end_time")

    # 5️⃣ Merchant Products (Paginated)
    products_qs = merchant_profile.products.all().prefetch_related("images", "timeslots").order_by('-created_at')
    paginator = Paginator(products_qs, 10)
    page_number = request.GET.get("page")
    products_page = paginator.get_page(page_number)

    # 6️⃣ Logs
    logs_qs = AuditLog.objects.filter(
        product_timeslot__product__merchant=merchant_profile
    ).select_related("product_timeslot")
    logs_paginator = Paginator(logs_qs.order_by("-timestamp"), 5)
    logs_page = logs_paginator.get_page(request.GET.get("log_page"))

    # 7️⃣ Categories
    categories = Category.objects.all().order_by("name")

    context = {
        "merchant": merchant_profile,
        "products_page": products_page,
        "categories": categories,
        "logs_page": logs_page,

        # Matching your 4 goals exactly:
        "available_slots": available_slots,   # 1️⃣ all open (waiting) slots – merchant can list
        "upcoming_slots": upcoming_slots,     # 2️⃣ merchant joined but not yet live
        "live_slots": live_slots,             # 3️⃣ currently live slots merchant is in
        "ended_slots": ended_slots,           # 4️⃣ ended slots merchant participated in
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


# MODERATOR VIEWS ##################################################################################################@login_required
@role_required("MODERATOR")
def moderator_dashboard(request):
    moderator = request.user

    # ✅ Categories assigned to this moderator
    categories = Category.objects.filter(
        id__in=ModeratorCategory.objects.filter(moderator=moderator).values("category_id")
    )

    # ✅ Products waiting moderation in slots (only in categories assigned to this mod)
    pending_pts = ProductTimeSlot.objects.filter(
        product__category__in=categories,
        status="pending"
    ).select_related("product", "timeslot", "product__merchant").prefetch_related("product__images")

    # ✅ Allow creating slots only if moderator has TSM category
    can_create_slot = categories.filter(name__iexact="TSM").exists()

    # ✅ Audit log for this moderator
    logs = AuditLog.objects.filter(moderator=moderator).order_by("-timestamp")

    # ----------------------
    # Pagination setup
    # ----------------------
    pending_page = request.GET.get("pending_page", 1)
    logs_page = request.GET.get("logs_page", 1)

    # ✅ Paginate pending reviews (10 per page)
    pending_paginator = Paginator(pending_pts, 10)
    try:
        pending_pts_page = pending_paginator.page(pending_page)
    except PageNotAnInteger:
        pending_pts_page = pending_paginator.page(1)
    except EmptyPage:
        pending_pts_page = pending_paginator.page(pending_paginator.num_pages)

    # ✅ Paginate logs (15 per page)
    logs_paginator = Paginator(logs, 15)
    try:
        logs_page_obj = logs_paginator.page(logs_page)
    except PageNotAnInteger:
        logs_page_obj = logs_paginator.page(1)
    except EmptyPage:
        logs_page_obj = logs_paginator.page(logs_paginator.num_pages)

    # ----------------------
    # POST actions
    # ----------------------
    if request.method == "POST":
        action = request.POST.get("action")

        if action in ["approve", "reject", "remove"]:
            pts_id = request.POST.get("pts_id")
            comment = request.POST.get("comment", "")
            pts = get_object_or_404(ProductTimeSlot, id=pts_id)

            # ✅ Only allow moderators of that category to moderate
            if pts.product.category not in categories:
                messages.error(request, "You are not allowed to moderate this category.")
                return redirect("moderator_dashboard")

            if action == "approve":
                pts.approve(moderator)
                messages.success(request, f"{pts.product.name} approved for {pts.timeslot.name}")
            elif action == "reject":
                pts.reject(moderator, comment or "Rejected by moderator.")
                messages.warning(request, f"{pts.product.name} rejected")
            elif action == "remove":
                pts.remove(moderator, comment or "Removed by moderator.")
                messages.error(request, f"{pts.product.name} removed")

        elif action == "create_slot" and can_create_slot:
            try:
                name = request.POST.get("name")
                start_time = request.POST.get("start_time")
                end_time = request.POST.get("end_time")

                ts = TimeSlot.objects.create(
                    name=name,
                    start_time=start_time,
                    end_time=end_time,
                    created_by=moderator,
                    status="waiting"
                )
                messages.success(request, f"TimeSlot '{ts.name}' created successfully!")
            except Exception as e:
                messages.error(request, f"Error creating timeslot: {e}")

        return redirect("moderator_dashboard")

    # ----------------------
    # Context for template
    # ----------------------
    context = {
        "categories": categories,
        "pending_pts": pending_pts_page,
        "can_create_slot": can_create_slot,
        "logs": logs_page_obj,
    }
    return render(request, "files/moderator/office.html", context)
