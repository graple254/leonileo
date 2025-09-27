from django.core.exceptions import PermissionDenied
from functools import wraps

def role_required(role):
    """
    Restrict a view to users with a specific role.

    Usage:
        @role_required("MERCHANT")
        def merchant_dashboard(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("You must be logged in to access this page.")

            # Normalize roles for comparison
            expected_role = role.strip().upper()
            user_role = getattr(request.user, "role", None)
            current_role = user_role.strip().upper() if user_role else None

            if current_role != expected_role:
                raise PermissionDenied("You are not authorized to access this page.")

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
