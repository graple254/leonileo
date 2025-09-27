import requests
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.utils.timezone import now
from .models import Visitor

class VisitorTrackingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        ip_address = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        referrer = request.META.get('HTTP_REFERER', '')
        path = request.path
        method = request.method

        # NEW: Only cache by IP address to avoid logging same IP repeatedly
        cache_key = f"visitor-ip-{ip_address}"
        if cache.get(cache_key):
            return

        location = self.get_location(ip_address)

        Visitor.objects.create(
            ip_address=ip_address,
            location=location,
            user_agent=user_agent,
            url_path=path,
            method=method,
            referrer=referrer,
            visit_date=now()
        )

        # Prevent duplicate tracking by IP for 30 minutes
        cache.set(cache_key, True, timeout=1800)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')

    def get_location(self, ip_address):
        try:
            cache_key = f"ip-location-{ip_address}"
            location = cache.get(cache_key)
            if location:
                return location

            response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=5)
            data = response.json()

            if data.get('status') == 'fail':
                return 'Unknown'

            location = f"{data.get('city')}, {data.get('country')}"
            cache.set(cache_key, location, timeout=86400)  # Cache for 24 hrs
            return location
        except requests.RequestException:
            return 'Unknown'
