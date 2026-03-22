import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
import requests

from .decorators import role_required
from .middleware import VisitorTrackingMiddleware
from .models import (
	AuditLog,
	Category,
	MerchantProfile,
	ModeratorCategory,
	Product,
	ProductImage,
	ProductTimeSlot,
	TimeSlot,
	Visitor,
)


User = get_user_model()
MIDDLEWARE_NO_VISITOR = [
	mw for mw in settings.MIDDLEWARE
	if mw != "core.middleware.VisitorTrackingMiddleware"
]


def sample_image(name="test.gif"):
	# Minimal valid GIF bytes for ImageField uploads.
	return SimpleUploadedFile(
		name,
		b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
		content_type="image/gif",
	)


class BaseCoreTestCase(TestCase):
	def setUp(self):
		self.customer = User.objects.create_user(
			username="customer", email="c@example.com", password="pass12345", role="CUSTOMER"
		)
		self.merchant_user = User.objects.create_user(
			username="merchant", email="m@example.com", password="pass12345", role="MERCHANT"
		)
		self.merchant_profile = MerchantProfile.objects.create(
			user=self.merchant_user,
			business_name="M Shop",
			location="Nairobi",
			whatsapp_number="+254700000001",
		)
		self.moderator = User.objects.create_user(
			username="moderator", email="mod@example.com", password="pass12345", role="MODERATOR"
		)
		self.category = Category.objects.create(name="TSM", description="Time slot management")
		ModeratorCategory.objects.create(moderator=self.moderator, category=self.category)


class ModelBehaviorTests(BaseCoreTestCase):
	def test_product_percentage_discount_is_computed_on_save(self):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Phone",
			description="Great phone",
			original_price=Decimal("1000.00"),
			discounted_price=Decimal("700.00"),
			stock_quantity=5,
		)
		self.assertEqual(product.percentage_discount, Decimal("30.00"))

	def test_product_percentage_discount_returns_zero_when_missing_prices(self):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			name="No Discount",
			description="No prices",
			stock_quantity=1,
		)
		self.assertEqual(product.percentage_discount, 0)

	def test_product_timeslot_clean_rejects_non_waiting_timeslot(self):
		slot = TimeSlot.objects.create(
			name="Live Slot",
			start_time=timezone.now() - timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=1),
			status="live",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="P1",
			description="d",
			original_price=10,
			discounted_price=5,
			stock_quantity=1,
		)

		with self.assertRaises(ValidationError):
			ProductTimeSlot.objects.create(product=product, timeslot=slot, status="pending")

	def test_timeslot_update_status_moves_to_live_with_four_approved_products(self):
		slot = TimeSlot.objects.create(
			name="Ready Slot",
			start_time=timezone.now() + timedelta(minutes=10),
			end_time=timezone.now() + timedelta(hours=1),
			status="waiting",
			created_by=self.moderator,
		)
		for i in range(4):
			product = Product.objects.create(
				merchant=self.merchant_profile,
				category=self.category,
				name=f"P{i}",
				description="d",
				original_price=100,
				discounted_price=90,
				stock_quantity=1,
			)
			ProductTimeSlot.objects.create(product=product, timeslot=slot, status="approved")

		# Move start_time into the past after all approvals exist, then evaluate transition.
		slot.start_time = timezone.now() - timedelta(minutes=1)
		slot.save(update_fields=["start_time"])

		self.assertEqual(slot.update_status(), "live")

	def test_timeslot_update_status_auto_rejects_pending_when_under_threshold(self):
		slot = TimeSlot.objects.create(
			name="Not Enough",
			start_time=timezone.now() - timedelta(minutes=1),
			end_time=timezone.now() + timedelta(minutes=20),
			status="waiting",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Pending Product",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		pts = ProductTimeSlot.objects.create(product=product, timeslot=slot, status="pending")

		new_status = slot.update_status()
		pts.refresh_from_db()
		self.assertEqual(new_status, "ended")
		self.assertEqual(pts.status, "rejected")
		self.assertIn("Auto-rejected", pts.moderator_comment)
		self.assertTrue(
			AuditLog.objects.filter(product_timeslot=pts, action="reject").exists()
		)

	def test_timeslot_manager_auto_refresh_statuses_returns_count(self):
		ended_slot = TimeSlot.objects.create(
			name="Past Slot",
			start_time=timezone.now() - timedelta(hours=2),
			end_time=timezone.now() - timedelta(hours=1),
			status="waiting",
			created_by=self.moderator,
		)
		active_slot = TimeSlot.objects.create(
			name="Future Slot",
			start_time=timezone.now() + timedelta(hours=2),
			end_time=timezone.now() + timedelta(hours=4),
			status="waiting",
			created_by=self.moderator,
		)

		updated = TimeSlot.objects.auto_refresh_statuses()
		ended_slot.refresh_from_db()
		active_slot.refresh_from_db()

		self.assertEqual(updated, 1)
		self.assertEqual(ended_slot.status, "ended")
		self.assertEqual(active_slot.status, "waiting")

	def test_auditlog_history_helpers(self):
		slot = TimeSlot.objects.create(
			name="History Slot",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			status="waiting",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="History Product",
			description="d",
			original_price=50,
			discounted_price=45,
			stock_quantity=1,
		)
		pts = ProductTimeSlot.objects.create(product=product, timeslot=slot, status="pending")
		pts.approve(self.moderator)

		self.assertGreaterEqual(AuditLog.history_for_product(product.id).count(), 1)
		self.assertGreaterEqual(AuditLog.history_for_timeslot(slot.id).count(), 1)

	def test_timeslot_creation_signal_logs_create_slot(self):
		slot = TimeSlot.objects.create(
			name="Signal Slot",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			created_by=self.moderator,
			status="waiting",
		)
		self.assertTrue(
			AuditLog.objects.filter(action="create_slot", comment__contains=slot.name).exists()
		)

	def test_product_timeslot_creation_signal_logs_pending(self):
		slot = TimeSlot.objects.create(
			name="Pending Signal",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			created_by=self.moderator,
			status="waiting",
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Signal Product",
			description="d",
			original_price=100,
			discounted_price=80,
			stock_quantity=1,
		)
		pts = ProductTimeSlot.objects.create(product=product, timeslot=slot, status="pending")

		self.assertTrue(
			AuditLog.objects.filter(
				product_timeslot=pts,
				action="pending",
				comment__contains="awaiting moderation",
			).exists()
		)


class DecoratorTests(BaseCoreTestCase):
	def setUp(self):
		super().setUp()
		self.factory = RequestFactory()

	def test_role_required_allows_matching_role(self):
		@role_required("MERCHANT")
		def dummy_view(request):
			return "ok"

		request = self.factory.get("/")
		request.user = self.merchant_user
		self.assertEqual(dummy_view(request), "ok")

	def test_role_required_raises_for_wrong_role(self):
		@role_required("MERCHANT")
		def dummy_view(request):
			return "ok"

		request = self.factory.get("/")
		request.user = self.customer
		with self.assertRaises(PermissionDenied):
			dummy_view(request)


class MiddlewareTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.middleware = VisitorTrackingMiddleware(get_response=lambda r: None)
		cache.clear()

	@patch("core.middleware.requests.get")
	def test_visitor_tracking_creates_record_once_per_ip_cache_window(self, mock_get):
		mock_response = Mock()
		mock_response.json.return_value = {
			"status": "success",
			"city": "Nairobi",
			"country": "Kenya",
		}
		mock_get.return_value = mock_response

		request = self.factory.get("/", HTTP_USER_AGENT="agent", REMOTE_ADDR="1.2.3.4")
		self.middleware.process_request(request)
		self.middleware.process_request(request)

		self.assertEqual(Visitor.objects.count(), 1)
		visitor = Visitor.objects.first()
		self.assertEqual(visitor.location, "Nairobi, Kenya")

	@patch("core.middleware.requests.get")
	def test_get_location_fallbacks_to_unknown_on_failure(self, mock_get):
		mock_response = Mock()
		mock_response.json.return_value = {"status": "fail"}
		mock_get.return_value = mock_response

		request = self.factory.get("/", REMOTE_ADDR="5.6.7.8")
		self.middleware.process_request(request)
		self.assertEqual(Visitor.objects.first().location, "Unknown")


@override_settings(MIDDLEWARE=MIDDLEWARE_NO_VISITOR)
class AuthAndBasicViewTests(BaseCoreTestCase):
	def test_signup_creates_user_and_redirects(self):
		resp = self.client.post(
			reverse("signup"),
			{
				"username": "newuser",
				"email": "n@example.com",
				"password": "newpass123",
				"role": "CUSTOMER",
			},
		)
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(User.objects.filter(username="newuser").exists())

	def test_signup_rejects_duplicate_username(self):
		resp = self.client.post(
			reverse("signup"),
			{
				"username": self.customer.username,
				"email": "dup@example.com",
				"password": "newpass123",
			},
		)
		self.assertEqual(resp.status_code, 302)

	def test_login_redirects_by_role(self):
		merchant_resp = self.client.post(
			reverse("login"),
			{"username": self.merchant_user.username, "password": "pass12345"},
		)
		self.assertRedirects(merchant_resp, reverse("merchant_dashboard"))

		self.client.logout()
		moderator_resp = self.client.post(
			reverse("login"),
			{"username": self.moderator.username, "password": "pass12345"},
		)
		self.assertRedirects(moderator_resp, reverse("moderator_dashboard"))

	def test_logout_redirects_to_login(self):
		self.client.login(username=self.customer.username, password="pass12345")
		resp = self.client.get(reverse("logout"))
		self.assertRedirects(resp, reverse("login"))

	def test_payment_success_page_renders(self):
		resp = self.client.get(reverse("payment_success"))
		self.assertEqual(resp.status_code, 200)


@override_settings(MIDDLEWARE=MIDDLEWARE_NO_VISITOR)
class MerchantViewTests(BaseCoreTestCase):
	def setUp(self):
		super().setUp()
		self.tmp_media = tempfile.mkdtemp()
		self.client.login(username=self.merchant_user.username, password="pass12345")

	def tearDown(self):
		shutil.rmtree(self.tmp_media, ignore_errors=True)
		super().tearDown()

	@override_settings(MEDIA_ROOT=tempfile.gettempdir())
	def test_merchant_dashboard_renders_for_merchant(self):
		resp = self.client.get(reverse("merchant_dashboard"))
		self.assertEqual(resp.status_code, 200)

	def test_create_merchant_profile_redirects_if_already_exists(self):
		resp = self.client.get(reverse("create_merchant_profile"))
		self.assertRedirects(resp, reverse("merchant_dashboard"))

	def test_create_merchant_profile_validates_required_fields(self):
		user = User.objects.create_user(
			username="m2", email="m2@example.com", password="pass12345", role="MERCHANT"
		)
		self.client.login(username="m2", password="pass12345")
		resp = self.client.post(reverse("create_merchant_profile"), {"business_name": "Only Name"})
		self.assertRedirects(resp, reverse("create_merchant_profile"))

	@override_settings(MEDIA_ROOT=tempfile.gettempdir())
	@patch("core.lipana_service.create_payment_link", return_value="https://lipana.dev/pay/slug")
	def test_merchant_add_product_with_images(self, _mock_link):
		post_data = {
			"action": "add_product",
			"category": str(self.category.id),
			"name": "Laptop",
			"description": "Gaming laptop",
			"original_price": "1500",
			"discounted_price": "1200",
			"stock_quantity": "4",
		}
		files = [sample_image(f"img{i}.gif") for i in range(5)]
		resp = self.client.post(reverse("merchant_products"), data={**post_data, "images": files})

		self.assertRedirects(resp, reverse("merchant_products"))
		product = Product.objects.get(name="Laptop")
		self.assertEqual(product.images.count(), 5)
		self.assertEqual(product.payment_link, "https://lipana.dev/pay/slug")

	def test_merchant_add_product_requires_at_least_five_images(self):
		post_data = {
			"action": "add_product",
			"category": str(self.category.id),
			"name": "Laptop2",
			"description": "Few images",
			"original_price": "1500",
			"discounted_price": "1200",
			"stock_quantity": "4",
		}
		files = [sample_image(f"img{i}.gif") for i in range(2)]
		self.client.post(reverse("merchant_products"), data={**post_data, "images": files})
		self.assertFalse(Product.objects.filter(name="Laptop2").exists())

	def test_assign_timeslot_creates_pending_entries(self):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Assigned",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		slot = TimeSlot.objects.create(
			name="Assign Slot",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			status="waiting",
			created_by=self.moderator,
		)

		resp = self.client.post(
			reverse("merchant_products"),
			{"action": "assign_timeslot", "timeslot_id": slot.id, "product_ids": [str(product.id)]},
		)
		self.assertRedirects(resp, reverse("merchant_products"))
		self.assertTrue(ProductTimeSlot.objects.filter(product=product, timeslot=slot).exists())

	def test_remove_from_timeslot_deletes_product_timeslot(self):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="To Remove",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		slot = TimeSlot.objects.create(
			name="Remove Slot",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			status="waiting",
			created_by=self.moderator,
		)
		pts = ProductTimeSlot.objects.create(product=product, timeslot=slot)

		resp = self.client.post(reverse("merchant_products"), {"action": "remove_from_timeslot", "pts_id": pts.id})
		self.assertRedirects(resp, reverse("merchant_products"))
		self.assertFalse(ProductTimeSlot.objects.filter(id=pts.id).exists())

	@patch("core.lipana_service.create_payment_link", return_value="https://lipana.dev/pay/newslug")
	def test_edit_product_updates_fields_and_regenerates_link(self, _mock_link):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Old Name",
			description="old",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)

		resp = self.client.post(
			reverse("merchant_products"),
			{
				"action": "edit_product",
				"product_id": product.id,
				"name": "New Name",
				"description": "new",
				"category": self.category.id,
				"original_price": "200",
				"discounted_price": "150",
				"stock_quantity": "7",
			},
		)
		self.assertRedirects(resp, reverse("merchant_products"))
		product.refresh_from_db()
		self.assertEqual(product.name, "New Name")
		self.assertEqual(product.stock_quantity, 7)
		self.assertEqual(product.payment_link, "https://lipana.dev/pay/newslug")

	def test_delete_product_removes_product(self):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Delete Me",
			description="d",
			original_price=100,
			discounted_price=80,
			stock_quantity=1,
		)
		ProductImage.objects.create(product=product, image=sample_image("delete.gif"))

		resp = self.client.post(
			reverse("merchant_products"),
			{"action": "delete_product", "product_id": product.id},
		)
		self.assertRedirects(resp, reverse("merchant_products"))
		self.assertFalse(Product.objects.filter(id=product.id).exists())

	@patch("core.lipana_service.create_payment_link", return_value="https://lipana.dev/pay/custom")
	def test_generate_payment_link_view_updates_product(self, _mock_link):
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Payable",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)

		resp = self.client.post(reverse("generate_payment_link", args=[product.id]), {"custom_amount": "120"})
		self.assertRedirects(resp, reverse("merchant_products"))
		product.refresh_from_db()
		self.assertEqual(product.payment_link, "https://lipana.dev/pay/custom")


@override_settings(MIDDLEWARE=MIDDLEWARE_NO_VISITOR)
class ModeratorViewTests(BaseCoreTestCase):
	def setUp(self):
		super().setUp()
		self.client.login(username=self.moderator.username, password="pass12345")

	def test_moderator_dashboard_renders(self):
		resp = self.client.get(reverse("moderator_dashboard"))
		self.assertEqual(resp.status_code, 200)

	def test_moderator_can_create_timeslot_when_tsm_assigned(self):
		resp = self.client.post(
			reverse("moderator_dashboard"),
			{
				"action": "create_slot",
				"name": "New Slot",
				"start_time": (timezone.now() + timedelta(hours=1)).isoformat(),
				"end_time": (timezone.now() + timedelta(hours=2)).isoformat(),
			},
		)
		self.assertRedirects(resp, reverse("moderator_dashboard"))
		self.assertTrue(TimeSlot.objects.filter(name="New Slot").exists())

	def test_moderator_approve_action_changes_product_timeslot_status(self):
		slot = TimeSlot.objects.create(
			name="Mod Slot",
			start_time=timezone.now() + timedelta(hours=1),
			end_time=timezone.now() + timedelta(hours=2),
			status="waiting",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Needs approval",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		pts = ProductTimeSlot.objects.create(product=product, timeslot=slot, status="pending")

		resp = self.client.post(
			reverse("moderator_dashboard"),
			{"action": "approve", "pts_id": pts.id},
		)
		self.assertRedirects(resp, reverse("moderator_dashboard"))
		pts.refresh_from_db()
		self.assertEqual(pts.status, "approved")


@override_settings(MIDDLEWARE=MIDDLEWARE_NO_VISITOR)
class CustomerViewTests(BaseCoreTestCase):
	def test_index_lists_only_live_approved_products(self):
		slot = TimeSlot.objects.create(
			name="Live For Customer",
			start_time=timezone.now() - timedelta(minutes=10),
			end_time=timezone.now() + timedelta(minutes=30),
			status="waiting",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Visible Product",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		ProductTimeSlot.objects.create(product=product, timeslot=slot, status="approved")
		slot.status = "live"
		slot.save(update_fields=["status"])

		resp = self.client.get(reverse("index"))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, "Visible Product")

	def test_product_detail_builds_whatsapp_url_for_live_product(self):
		slot = TimeSlot.objects.create(
			name="Live Detail Slot",
			start_time=timezone.now() - timedelta(minutes=10),
			end_time=timezone.now() + timedelta(minutes=30),
			status="waiting",
			created_by=self.moderator,
		)
		product = Product.objects.create(
			merchant=self.merchant_profile,
			category=self.category,
			name="Detail Product",
			description="d",
			original_price=100,
			discounted_price=90,
			stock_quantity=1,
		)
		ProductTimeSlot.objects.create(product=product, timeslot=slot, status="approved")
		slot.status = "live"
		slot.save(update_fields=["status"])

		resp = self.client.get(reverse("product_detail", args=[product.id]))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, "wa.me")
