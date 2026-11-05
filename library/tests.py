from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import IssueForm
from .models import Book, Category, Donation, Donor, Issue, Member


def today():
    return timezone.now().date()


class BaseTestCase(TestCase):
    """Shared fixtures and small helpers."""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Fiction")
        cls.librarian = User.objects.create_user("lib", password="pass12345")
        lib_group, _ = Group.objects.get_or_create(name="Librarian")
        cls.librarian.groups.add(lib_group)

    def make_book(self, isbn="111", total=3, available=None):
        return Book.objects.create(
            title=f"Book {isbn}", author="Author", isbn=isbn,
            category=self.category, total_copies=total,
            available_copies=total if available is None else available,
        )

    def make_member(self, email="m@example.com", active=True):
        return Member.objects.create(name="Member", email=email, is_active=active)


# ---------------------------------------------------------------- fines

@override_settings(FINE_PER_DAY=5, LOAN_PERIOD_DAYS=14)
class FineCalculationTests(BaseTestCase):
    def setUp(self):
        self.book = self.make_book()
        self.member = self.make_member()

    def make_issue(self, due_offset, returned_offset=None):
        issue = Issue.objects.create(
            book=self.book, member=self.member,
            due_date=today() + timedelta(days=due_offset),
        )
        if returned_offset is not None:
            issue.return_date = today() + timedelta(days=returned_offset)
            issue.save()
        return issue

    def test_not_yet_due_has_no_fine(self):
        self.assertEqual(self.make_issue(due_offset=3).calculate_fine(), 0)

    def test_due_today_has_no_fine(self):
        self.assertEqual(self.make_issue(due_offset=0).calculate_fine(), 0)

    def test_open_overdue_loan_accrues_fine(self):
        # 4 days overdue * 5 = 20
        self.assertEqual(self.make_issue(due_offset=-4).calculate_fine(), 20)

    def test_returned_on_due_date_has_no_fine(self):
        issue = self.make_issue(due_offset=-10, returned_offset=-10)
        self.assertEqual(issue.calculate_fine(), 0)

    def test_returned_fine_is_frozen_at_return_date(self):
        # returned 3 days late; later dates must not increase it
        issue = self.make_issue(due_offset=-10, returned_offset=-7)
        self.assertEqual(issue.calculate_fine(), 15)
        self.assertEqual(issue.calculate_fine(as_of=today() + timedelta(days=30)), 15)

    def test_as_of_is_used_for_open_loans(self):
        issue = self.make_issue(due_offset=0)
        self.assertEqual(issue.calculate_fine(as_of=today() + timedelta(days=2)), 10)

    def test_default_due_date_uses_loan_period(self):
        issue = Issue.objects.create(book=self.book, member=self.member)
        self.assertEqual(issue.due_date, today() + timedelta(days=14))

    def test_fine_rate_comes_from_settings(self):
        issue = self.make_issue(due_offset=-2)
        with self.settings(FINE_PER_DAY=10):
            self.assertEqual(issue.calculate_fine(), 20)


# ----------------------------------------------------------- loan limits

@override_settings(MAX_BOOKS_PER_MEMBER=2)
class LoanLimitTests(BaseTestCase):
    def setUp(self):
        self.member = self.make_member()
        self.books = [self.make_book(isbn=str(i)) for i in range(4)]

    def loan(self, book, returned=False):
        return Issue.objects.create(
            book=book, member=self.member,
            return_date=today() if returned else None,
        )

    def form(self, book, member=None):
        return IssueForm({"book": book.pk, "member": (member or self.member).pk})

    def test_member_under_limit_can_borrow(self):
        self.loan(self.books[0])
        self.assertTrue(self.form(self.books[1]).is_valid())

    def test_member_at_limit_is_blocked(self):
        self.loan(self.books[0])
        self.loan(self.books[1])
        form = self.form(self.books[2])
        self.assertFalse(form.is_valid())
        self.assertIn("already has 2 books", str(form.non_field_errors()))

    def test_returned_loans_do_not_count(self):
        self.loan(self.books[0], returned=True)
        self.loan(self.books[1], returned=True)
        self.assertTrue(self.form(self.books[2]).is_valid())

    def test_same_book_twice_is_blocked(self):
        self.loan(self.books[0])
        form = self.form(self.books[0])
        self.assertFalse(form.is_valid())
        self.assertIn("already has a copy", str(form.non_field_errors()))

    def test_book_with_no_copies_cannot_be_chosen(self):
        empty = self.make_book(isbn="empty", total=1, available=0)
        form = self.form(empty)
        self.assertFalse(form.is_valid())
        self.assertIn("book", form.errors)

    def test_inactive_member_cannot_be_chosen(self):
        inactive = self.make_member(email="x@example.com", active=False)
        form = self.form(self.books[0], member=inactive)
        self.assertFalse(form.is_valid())
        self.assertIn("member", form.errors)


# ------------------------------------------------------------ donations

class DonationApprovalTests(BaseTestCase):
    def setUp(self):
        user = User.objects.create_user("donor1", password="pass12345")
        self.donor = Donor.objects.create(user=user, name="Dana")

    def make_donation(self, isbn="999", quantity=2):
        return Donation.objects.create(
            donor=self.donor, title="Donated", author="Someone", isbn=isbn,
            category=self.category, condition=Donation.Condition.GOOD,
            quantity=quantity,
        )

    def test_approving_new_isbn_creates_book(self):
        donation = self.make_donation(isbn="999", quantity=2)
        donation.approve(self.librarian)

        book = Book.objects.get(isbn="999")
        self.assertEqual((book.total_copies, book.available_copies), (2, 2))

        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.APPROVED)
        self.assertEqual(donation.book, book)
        self.assertEqual(donation.reviewed_by, self.librarian)
        self.assertIsNotNone(donation.reviewed_on)

    def test_approving_existing_isbn_adds_copies_not_duplicate(self):
        existing = self.make_book(isbn="999", total=2, available=1)  # 1 on loan
        donation = self.make_donation(isbn="999", quantity=3)
        donation.approve(self.librarian)

        self.assertEqual(Book.objects.filter(isbn="999").count(), 1)
        existing.refresh_from_db()
        self.assertEqual((existing.total_copies, existing.available_copies), (5, 4))

        donation.refresh_from_db()
        self.assertEqual(donation.book, existing)

    def test_approving_twice_does_not_add_copies_twice(self):
        donation = self.make_donation(isbn="999", quantity=2)
        donation.approve(self.librarian)
        Donation.objects.get(pk=donation.pk).approve(self.librarian)

        self.assertEqual(Book.objects.get(isbn="999").total_copies, 2)

    def test_reject_records_reason_and_adds_no_book(self):
        donation = self.make_donation()
        donation.reject(self.librarian, remarks="Water damaged")

        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.REJECTED)
        self.assertEqual(donation.remarks, "Water damaged")
        self.assertEqual(donation.reviewed_by, self.librarian)
        self.assertFalse(Book.objects.exists())

    def test_rejected_donation_cannot_be_approved_later(self):
        donation = self.make_donation()
        donation.reject(self.librarian)
        Donation.objects.get(pk=donation.pk).approve(self.librarian)

        self.assertFalse(Book.objects.exists())
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.REJECTED)

    def test_approved_donation_cannot_be_rejected_later(self):
        donation = self.make_donation()
        donation.approve(self.librarian)
        Donation.objects.get(pk=donation.pk).reject(self.librarian, remarks="oops")

        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.APPROVED)
        self.assertEqual(donation.remarks, "")


# ---------------------------------------------- views and permissions

@override_settings(FINE_PER_DAY=5, LOAN_PERIOD_DAYS=14, MAX_BOOKS_PER_MEMBER=3)
class ViewTests(BaseTestCase):
    def setUp(self):
        self.donor_user = User.objects.create_user("donor1", password="pass12345")
        donor_group, _ = Group.objects.get_or_create(name="Donor")
        self.donor_user.groups.add(donor_group)
        self.donor = Donor.objects.create(user=self.donor_user, name="Dana")

    def test_issuing_a_book_reduces_available_copies(self):
        book = self.make_book(total=3)
        member = self.make_member()
        self.client.force_login(self.librarian)

        response = self.client.post(
            reverse("issue_create"), {"book": book.pk, "member": member.pk}
        )

        self.assertRedirects(response, reverse("issue_list"))
        book.refresh_from_db()
        self.assertEqual(book.available_copies, 2)
        issue = Issue.objects.get()
        self.assertEqual(issue.due_date, today() + timedelta(days=14))

    def test_late_return_saves_fine_and_restores_copy(self):
        book = self.make_book(total=3, available=2)
        member = self.make_member()
        issue = Issue.objects.create(
            book=book, member=member, due_date=today() - timedelta(days=4)
        )
        self.client.force_login(self.librarian)

        self.client.post(reverse("return_book", args=[issue.pk]))

        issue.refresh_from_db()
        book.refresh_from_db()
        self.assertEqual(issue.return_date, today())
        self.assertEqual(issue.fine_amount, 20)
        self.assertFalse(issue.fine_paid)
        self.assertEqual(book.available_copies, 3)

    def test_returning_twice_does_not_inflate_copies(self):
        book = self.make_book(total=3, available=2)
        member = self.make_member()
        issue = Issue.objects.create(book=book, member=member)
        self.client.force_login(self.librarian)

        self.client.post(reverse("return_book", args=[issue.pk]))
        self.client.post(reverse("return_book", args=[issue.pk]))

        book.refresh_from_db()
        self.assertEqual(book.available_copies, 3)

    def test_donor_is_forbidden_from_librarian_pages(self):
        self.client.force_login(self.donor_user)
        for name in ["book_create", "member_list", "issue_list",
                     "donation_list", "report_index"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_donor_can_open_donation_form(self):
        self.client.force_login(self.donor_user)
        self.assertEqual(self.client.get(reverse("donation_create")).status_code, 200)

    def test_librarian_cannot_use_donor_form(self):
        self.client.force_login(self.librarian)
        self.assertEqual(self.client.get(reverse("donation_create")).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("book_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_csv_export_neutralises_formulas(self):
        Donation.objects.create(
            donor=self.donor, title="=1+1", author="A", isbn="1",
            category=self.category, condition=Donation.Condition.NEW,
        )
        self.client.force_login(self.librarian)

        response = self.client.get(
            reverse("report_view", args=["donations"]), {"export": "csv"}
        )

        content = response.content.decode()
        self.assertIn("'=1+1", content)
        self.assertNotIn(",=1+1,", content)