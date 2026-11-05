from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from django.views.decorators.http import require_POST

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .forms import BookForm, DonationForm, DonorRegistrationForm, IssueForm, MemberForm
from .models import Book, Category, Donation, Donor, Issue, Member
from .permissions import donor_required, is_donor, is_librarian, is_member, librarian_required

import csv

from django.http import Http404, HttpResponse

from .reports import REPORTS, parse_date


@login_required
def book_list(request):
    """Visible to all logged-in users. Includes search."""
    books = Book.objects.select_related("category")

    q = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "")
    available_only = request.GET.get("available") == "1"

    if q:
        books = books.filter(
            Q(title__icontains=q) | Q(author__icontains=q) | Q(isbn__icontains=q)
        )
    if category_id:
        books = books.filter(category_id=category_id)
    if available_only:
        books = books.filter(available_copies__gt=0)

    paginator = Paginator(books, 10)
    page = paginator.get_page(request.GET.get("page"))

    # keep filters when moving between pages
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "library/book_list.html", {
        "page": page,
        "categories": Category.objects.all(),
        "q": q,
        "selected_category": category_id,
        "available_only": available_only,
        "querystring": params.urlencode(),
        "is_librarian": is_librarian(request.user),
    })


@librarian_required
def book_create(request):
    form = BookForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Book added.")
        return redirect("book_list")
    return render(request, "library/book_form.html", {"form": form, "title": "Add Book"})


@librarian_required
def book_update(request, pk):
    book = get_object_or_404(Book, pk=pk)
    form = BookForm(request.POST or None, instance=book)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Book updated.")
        return redirect("book_list")
    return render(request, "library/book_form.html", {"form": form, "title": "Edit Book"})


@librarian_required
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        try:
            book.delete()
            messages.success(request, "Book deleted.")
        except ProtectedError:
            messages.error(request, "This book has issue history and can't be deleted.")
        return redirect("book_list")
    return render(request, "library/book_confirm_delete.html", {"book": book})


def register_donor(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = DonorRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Registration successful. Please log in.")
            return redirect("login")
    else:
        form = DonorRegistrationForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    user = request.user
    today = timezone.now().date()
    context = {
        "is_librarian": is_librarian(user),
        "is_member": is_member(user),
        "is_donor": is_donor(user),
        "today": today,
    }

    if context["is_librarian"]:
        open_loans = Issue.objects.filter(return_date__isnull=True)
        unpaid = Issue.objects.filter(
            return_date__isnull=False, fine_amount__gt=0, fine_paid=False
        ).aggregate(total=Sum("fine_amount"))["total"] or 0
        context["stats"] = {
            "books_out": open_loans.count(),
            "overdue": open_loans.filter(due_date__lt=today).count(),
            "pending_donations": Donation.objects.filter(
                status=Donation.Status.PENDING
            ).count(),
            "unpaid_fines": unpaid,
            "titles": Book.objects.count(),
            "active_members": Member.objects.filter(is_active=True).count(),
        }

    elif context["is_member"]:
        member = Member.objects.filter(user=user).first()
        context["member"] = member
        if member:
            context["current_loans"] = Issue.objects.filter(
                member=member, return_date__isnull=True
            ).select_related("book").order_by("due_date")
            context["unpaid_fines"] = Issue.objects.filter(
                member=member, return_date__isnull=False,
                fine_amount__gt=0, fine_paid=False,
            ).aggregate(total=Sum("fine_amount"))["total"] or 0

    elif context["is_donor"]:
        donor = Donor.objects.filter(user=user).first()
        if donor:
            donations = Donation.objects.filter(donor=donor)
            context["pending_count"] = donations.filter(
                status=Donation.Status.PENDING
            ).count()
            context["recent_donations"] = donations[:5]

    return render(request, "library/dashboard.html", context)


@librarian_required
def member_list(request):
    members = Member.objects.all()
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")

    if q:
        members = members.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        )
    if status == "active":
        members = members.filter(is_active=True)
    elif status == "inactive":
        members = members.filter(is_active=False)

    paginator = Paginator(members, 10)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "library/member_list.html", {
        "page": page, "q": q, "status": status,
        "querystring": params.urlencode(),
    })


@librarian_required
def member_create(request):
    form = MemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Member added.")
        return redirect("member_list")
    return render(request, "library/member_form.html", {"form": form, "title": "Add Member"})


@librarian_required
def member_update(request, pk):
    member = get_object_or_404(Member, pk=pk)
    form = MemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Member updated.")
        return redirect("member_list")
    return render(request, "library/member_form.html", {"form": form, "title": "Edit Member"})


@librarian_required
@require_POST
def member_toggle_active(request, pk):
    member = get_object_or_404(Member, pk=pk)
    member.is_active = not member.is_active
    member.save()
    if member.user:
        member.user.is_active = member.is_active
        member.user.save()
    state = "activated" if member.is_active else "deactivated"
    messages.success(request, f"{member.name} {state}.")
    return redirect("member_list")


@librarian_required
def issue_list(request):
    issues = Issue.objects.select_related("book", "member")
    today = timezone.now().date()

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")

    if q:
        issues = issues.filter(
            Q(book__title__icontains=q) | Q(member__name__icontains=q)
        )
    if status == "active":
        issues = issues.filter(return_date__isnull=True)
    elif status == "overdue":
        issues = issues.filter(return_date__isnull=True, due_date__lt=today)
    elif status == "returned":
        issues = issues.filter(return_date__isnull=False)
    elif status == "unpaid":
        issues = issues.filter(fine_amount__gt=0, fine_paid=False)

    paginator = Paginator(issues, 10)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "library/issue_list.html", {
        "page": page, "q": q, "status": status, "today": today,
        "querystring": params.urlencode(),
    })


@librarian_required
def issue_create(request):
    form = IssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # lock the row so two librarians can't issue the last copy at once
            book = Book.objects.select_for_update().get(pk=form.cleaned_data["book"].pk)
            if book.available_copies < 1:
                messages.error(request, "No copies available.")
                return redirect("issue_create")
            issue = Issue.objects.create(book=book, member=form.cleaned_data["member"])
            book.available_copies -= 1
            book.save()
        messages.success(request, f"Book issued. Due on {issue.due_date}.")
        return redirect("issue_list")
    return render(request, "library/issue_form.html", {"form": form})


@librarian_required
@require_POST
def return_book(request, pk):
    with transaction.atomic():
        issue = get_object_or_404(Issue.objects.select_for_update(), pk=pk)
        if issue.is_returned:
            messages.info(request, "This book was already returned.")
            return redirect("issue_list")
        issue.return_date = timezone.now().date()
        issue.fine_amount = issue.calculate_fine()
        issue.save()
        Book.objects.filter(pk=issue.book_id).update(
            available_copies=F("available_copies") + 1
        )
    if issue.fine_amount > 0:
        messages.warning(request, f"Returned late. Fine: {issue.fine_amount}.")
    else:
        messages.success(request, "Book returned. No fine.")
    return redirect("issue_list")


@librarian_required
@require_POST
def pay_fine(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    if issue.is_returned and issue.fine_amount > 0:
        issue.fine_paid = True
        issue.save()
        messages.success(request, "Fine marked as paid.")
    return redirect("issue_list")


@login_required
def my_loans(request):
    member = Member.objects.filter(user=request.user).first()
    issues = Issue.objects.filter(member=member).select_related("book") if member else []
    return render(request, "library/my_loans.html", {
        "member": member, "issues": issues, "today": timezone.now().date(),
    })


@donor_required
def donation_create(request):
    donor = Donor.objects.filter(user=request.user).first()
    if donor is None:
        messages.error(request, "Your account has no donor profile. Please contact a librarian.")
        return redirect("dashboard")

    form = DonationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        donation = form.save(commit=False)
        donation.donor = donor
        donation.save()
        messages.success(request, "Donation request submitted. A librarian will review it.")
        return redirect("my_donations")
    return render(request, "library/donation_form.html", {"form": form})


@donor_required
def my_donations(request):
    donor = Donor.objects.filter(user=request.user).first()
    donations = (
        Donation.objects.filter(donor=donor).select_related("category")
        if donor else []
    )
    return render(request, "library/my_donations.html", {"donations": donations})


@librarian_required
def donation_list(request):
    """Librarian review queue. Defaults to pending requests."""
    status = request.GET.get("status", "pending")
    donations = Donation.objects.select_related("donor", "category", "reviewed_by")
    if status in ("pending", "approved", "rejected"):
        donations = donations.filter(status=status)

    paginator = Paginator(donations, 10)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "library/donation_list.html", {
        "page": page, "status": status, "querystring": params.urlencode(),
    })


@librarian_required
@require_POST
def donation_approve(request, pk):
    with transaction.atomic():
        donation = get_object_or_404(Donation.objects.select_for_update(), pk=pk)
        if donation.status != Donation.Status.PENDING:
            messages.info(request, "This donation was already reviewed.")
            return redirect("donation_list")
        donation.approve(request.user)
    messages.success(
        request, f"Approved. '{donation.title}' was added to the inventory."
    )
    return redirect("donation_list")


@librarian_required
@require_POST
def donation_reject(request, pk):
    remarks = request.POST.get("remarks", "").strip()
    with transaction.atomic():
        donation = get_object_or_404(Donation.objects.select_for_update(), pk=pk)
        if donation.status != Donation.Status.PENDING:
            messages.info(request, "This donation was already reviewed.")
            return redirect("donation_list")
        donation.reject(request.user, remarks)
    messages.warning(request, f"Rejected '{donation.title}'.")
    return redirect("donation_list")


def _csv_safe(value):
    """Stop spreadsheet apps from running user-entered text as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@librarian_required
def report_index(request):
    return render(request, "library/report_index.html", {"reports": REPORTS})


@librarian_required
def report_view(request, name):
    report = REPORTS.get(name)
    if report is None:
        raise Http404

    start = parse_date(request.GET.get("start"))
    end = parse_date(request.GET.get("end"))
    data = report["func"](start, end)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        filename = f"{name}_{timezone.now():%Y%m%d}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(data["headers"])
        for row in data["rows"]:
            writer.writerow([_csv_safe(cell) for cell in row])
        return response

    export_params = request.GET.copy()
    export_params["export"] = "csv"
    return render(request, "library/report.html", {
        "report": report,
        "data": data,
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "export_query": export_params.urlencode(),
        "name": name,
    })














