from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from .models import *

from .decorators import role_required

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

@login_required
@role_required("MERCHANT")
def merchant_dashboard(request):
    """Merchant dashboard. Redirect to profile creation if missing."""
    try:
        profile = request.user.merchant_profile
    except MerchantProfile.DoesNotExist:
        return redirect("create_merchant_profile")

    return render(request, "files/merchant/dashboard.html", {"profile": profile})


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
