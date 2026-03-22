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
from django.db.models import Q, Count
from django.db.models import Prefetch
from urllib.parse import quote_plus


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


# Payment Success View (after Lipana redirects back) ###################################################################################################

def payment_success(request):
    return render(request, "files/payment/success.html")


###########################################################################
# Merchant Products and Time slots Management
############################################################################


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

                    # Auto-generate payment link
# Auto-generate payment link after product creation
                    try:
                        from .lipana_service import create_payment_link
                        product.payment_link = create_payment_link(product, request=request)
                        product.save(update_fields=["payment_link"])
                    except Exception as e:
                        messages.warning(request, f"Product saved, but payment link failed: {e}")

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

        # 5️⃣ Edit Product
        elif action == "edit_product":
            try:
                with transaction.atomic():
                    product = get_object_or_404(Product, id=request.POST.get("product_id"), merchant=merchant_profile)
                    product.name = request.POST.get("name")
                    product.description = request.POST.get("description")
                    product.category_id = int(request.POST.get("category")) if request.POST.get("category") else None
                    product.original_price = Decimal(request.POST.get("original_price")) if request.POST.get("original_price") else None
                    product.discounted_price = Decimal(request.POST.get("discounted_price")) if request.POST.get("discounted_price") else None
                    product.stock_quantity = int(request.POST.get("stock_quantity") or 0)
                    product.save()

                    # Regenerate payment link with new discounted price
                    try:
                        from .lipana_service import create_payment_link
                        product.payment_link = create_payment_link(product, request=request)
                        product.save(update_fields=["payment_link"])
                    except Exception as e:
                        messages.warning(request, f"Product updated but payment link failed: {e}")

                    messages.success(request, f"'{product.name}' updated successfully!")
            except Exception as e:
                messages.error(request, f"Error updating product: {e}")
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
def generate_payment_link(request, product_id):
    """
    Regenerate a payment link for a product.
    Allows merchant to override the amount (e.g. to include delivery fees).
    """
    merchant_profile = request.user.merchant_profile
    product = get_object_or_404(Product, id=product_id, merchant=merchant_profile)

    if request.method == "POST":
        from .lipana_service import create_payment_link
        custom_amount = request.POST.get("custom_amount")

        try:
            amount = Decimal(custom_amount) if custom_amount else None
            product.payment_link = create_payment_link(product, request=request, amount=amount)
            product.save(update_fields=["payment_link"])
            messages.success(request, f"Payment link regenerated successfully!")
        except Exception as e:
            messages.error(request, f"Failed to generate payment link: {e}")

    return redirect("merchant_products")



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
    moderator = request.user

    # ✅ Categories this moderator handles
    categories = Category.objects.filter(
        id__in=ModeratorCategory.objects.filter(moderator=moderator).values("category_id")
    )

    # ✅ Products awaiting moderation (pending)
    pending_pts = (
        ProductTimeSlot.objects.filter(
            product__category__in=categories,
            status="pending"
        )
        .select_related("product", "timeslot", "product__merchant")
        .prefetch_related("product__images")
    )

    # ✅ All timeslots created by this moderator
    timeslots = (
        TimeSlot.objects.filter(created_by=moderator)
        .prefetch_related("products__product__images", "products__product__merchant")
        .order_by("-start_time")
    )

    # ✅ All product-timeslot relationships (for showing total moderated products)
    moderated_pts = (
        ProductTimeSlot.objects.filter(
            timeslot__created_by=moderator
        )
        .select_related("product", "timeslot")
        .order_by("-updated_at")
    )

    # ✅ Audit logs (what actions this moderator took)
    logs = AuditLog.objects.filter(moderator=moderator).order_by("-timestamp")

    # ✅ Allow slot creation only if TSM category
    can_create_slot = categories.filter(name__iexact="TSM").exists()

    # ----------------------
    # Pagination setup
    # ----------------------
    pending_page = request.GET.get("pending_page", 1)
    logs_page = request.GET.get("logs_page", 1)
    timeslot_page = request.GET.get("timeslot_page", 1)

    paginator_pending = Paginator(pending_pts, 5)
    paginator_logs = Paginator(logs, 5)
    paginator_timeslots = Paginator(timeslots, 5)

    try:
        pending_pts_page = paginator_pending.page(pending_page)
    except (PageNotAnInteger, EmptyPage):
        pending_pts_page = paginator_pending.page(1)

    try:
        logs_page_obj = paginator_logs.page(logs_page)
    except (PageNotAnInteger, EmptyPage):
        logs_page_obj = paginator_logs.page(1)

    try:
        timeslot_page_obj = paginator_timeslots.page(timeslot_page)
    except (PageNotAnInteger, EmptyPage):
        timeslot_page_obj = paginator_timeslots.page(1)

    # ----------------------
    # POST actions
    # ----------------------
    if request.method == "POST":
        action = request.POST.get("action")

        # Approve / Reject / Remove
        if action in ["approve", "reject", "remove"]:
            pts_id = request.POST.get("pts_id")
            comment = request.POST.get("comment", "")
            pts = get_object_or_404(ProductTimeSlot, id=pts_id)

            # Authorization check
            if pts.product.category not in categories:
                messages.error(request, "You are not allowed to moderate this category.")
                return redirect("moderator_dashboard")

            if action == "approve":
                pts.approve(moderator)
                messages.success(request, f"{pts.product.name} approved for {pts.timeslot.name}")
            elif action == "reject":
                pts.reject(moderator, comment or "Rejected by moderator.")
                messages.warning(request, f"{pts.product.name} rejected.")
            elif action == "remove":
                pts.remove(moderator, comment or "Removed by moderator.")
                messages.error(request, f"{pts.product.name} removed.")

        # Create new TimeSlot
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
    # Dashboard summary metrics
    # ----------------------
    total_slots = timeslots.count()
    live_slots = timeslots.filter(status="live").count()
    ended_slots = timeslots.filter(status="ended").count()
    total_products_moderated = moderated_pts.exclude(status="pending").count()

    # ----------------------
    # Context for template
    # ----------------------
    context = {
        "categories": categories,
        "pending_pts": pending_pts_page,
        "can_create_slot": can_create_slot,
        "logs": logs_page_obj,
        "timeslots": timeslot_page_obj,
        "total_slots": total_slots,
        "live_slots": live_slots,
        "ended_slots": ended_slots,
        "total_products_moderated": total_products_moderated,
    }
    return render(request, "files/moderator/office.html", context)




# Actual Marketplace View (for Customers to browse live products)#########################################################


# CUSTOMER VIEWS ###################################################################################################

def index(request):
    now = timezone.now()

    # ensure statuses are fresh
    try:
        TimeSlot.objects.auto_refresh_statuses()
    except Exception:
        pass

    # Live ProductTimeSlots (approved products in live timeslots)
    live_pts = ProductTimeSlot.objects.filter(
        timeslot__status="live",
        status="approved",
        timeslot__start_time__lte=now,
        timeslot__end_time__gte=now,
    ).select_related("product__merchant", "timeslot").prefetch_related("product__images")

    # Build queryset of distinct products for pagination
    live_product_ids = live_pts.values_list("product_id", flat=True).distinct()
    live_products_qs = Product.objects.filter(id__in=live_product_ids).prefetch_related("images", "merchant")

    paginator = Paginator(live_products_qs.order_by("-created_at"), 12)
    page_number = request.GET.get("page")
    products_page = paginator.get_page(page_number)

    # Upcoming slots that have at least one approved product (teaser)
    upcoming_slots = (
        TimeSlot.objects.filter(status="waiting", start_time__gt=now)
        .annotate(approved_count=Count("products", filter=Q(products__status="approved")))
        .filter(approved_count__gt=0)
        .order_by("start_time")
        .prefetch_related(
            Prefetch(
                "products",
                queryset=ProductTimeSlot.objects.filter(status="approved").select_related("product").prefetch_related("product__images"),
                to_attr="approved_products"
            )
        )
    )

    context = {
        "products_page": products_page,
        "upcoming_slots": upcoming_slots,
        "now": now,
    }
    return render(request, "files/customer/index.html", context)


def product_detail(request, product_id):
    product = Product.objects.prefetch_related("images").select_related("merchant").get(id=product_id)

    now = timezone.now()

    # Is this product approved in any live timeslot?
    live_pts = product.timeslots.filter(
        status="approved",
        timeslot__status="live",
        timeslot__start_time__lte=now,
        timeslot__end_time__gte=now,
    ).select_related("timeslot").first()

    # Preview slot (approved + waiting) if any (no contact)
    upcoming_pts = product.timeslots.filter(
        status="approved",
        timeslot__status="waiting",
        timeslot__start_time__gt=now
    ).select_related("timeslot").first()

    live_contact = False
    whatsapp_url = None
    if live_pts:
        live_contact = True
        timeslot = live_pts.timeslot
        # Normalize WH number and prefill message
        raw = product.merchant.whatsapp_number or ""
        normalized = raw.strip().lstrip("+").replace(" ", "")
        msg = f"Hi, I'm interested in '{product.name}' from the '{timeslot.name}' clearance. Is it still available?"
        whatsapp_url = f"https://wa.me/{normalized}?text={quote_plus(msg)}"

    context = {
        "product": product,
        "images": product.images.all(),
        "live_contact": live_contact,
        "whatsapp_url": whatsapp_url,
        "upcoming_preview": upcoming_pts,  # may be None
    }
    return render(request, "files/customer/product_detail.html", context)

