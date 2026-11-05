from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=150)
    isbn = models.CharField(max_length=20, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    total_copies = models.PositiveIntegerField(default=1)
    available_copies = models.PositiveIntegerField(default=1)
    added_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.title} by {self.author}"


class Member(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Optional: link to a login account",
    )
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    joined_on = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def default_due_date():
    return timezone.now().date() + timedelta(days=settings.LOAN_PERIOD_DAYS)


class Issue(models.Model):
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="issues")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="issues")
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(default=default_due_date)
    return_date = models.DateField(null=True, blank=True)
    fine_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fine_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"{self.book.title} -> {self.member.name}"

    @property
    def is_returned(self):
        return self.return_date is not None

    def calculate_fine(self, as_of=None):
        """Fine = overdue days * FINE_PER_DAY. Uses return_date if returned."""
        end = self.return_date or as_of or timezone.now().date()
        overdue_days = (end - self.due_date).days
        return max(overdue_days, 0) * settings.FINE_PER_DAY


class Donor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    registered_on = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Donation(models.Model):
    class Condition(models.TextChoices):
        NEW = "new", "New"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="donations")
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=150)
    isbn = models.CharField(max_length=20)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    condition = models.CharField(max_length=10, choices=Condition.choices)
    quantity = models.PositiveIntegerField(default=1)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    submitted_on = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_donations"
    )
    reviewed_on = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    book = models.ForeignKey(
        Book, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Inventory record created from this donation",
    )

    class Meta:
        ordering = ["-submitted_on"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @transaction.atomic
    def approve(self, librarian):
        if self.status != self.Status.PENDING:
            return
        book, created = Book.objects.get_or_create(
            isbn=self.isbn,
            defaults={
                "title": self.title,
                "author": self.author,
                "category": self.category,
                "total_copies": self.quantity,
                "available_copies": self.quantity,
            },
        )
        if not created:  # book already exists, add copies
            book.total_copies += self.quantity
            book.available_copies += self.quantity
            book.save()

        self.book = book
        self.status = self.Status.APPROVED
        self.reviewed_by = librarian
        self.reviewed_on = timezone.now()
        self.save()

    def reject(self, librarian, remarks=""):
        if self.status != self.Status.PENDING:
            return
        self.status = self.Status.REJECTED
        self.reviewed_by = librarian
        self.reviewed_on = timezone.now()
        self.remarks = remarks
        self.save()