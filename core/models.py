from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.conf import settings
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile



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
    

class User(AbstractUser):
    ROLE_CHOICES = (
        ('CUSTOMER', 'Customer'),
        ('MERCHANT', 'Merchant'),
        ('MODERATOR', 'Moderator'),
    )
    
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    def __str__(self):
        return f"{self.username} ({self.role})"