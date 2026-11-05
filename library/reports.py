import datetime

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Book, Donation, Issue, Member


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def inventory(start, end):
    books = Book.objects.select_related("category")
    rows = [
        [b.title, b.author, b.isbn, b.category.name,
         b.total_copies, b.available_copies, b.total_copies - b.available_copies]
        for b in books
    ]
    summary = [
        ("Titles", len(rows)),
        ("Total copies", sum(r[4] for r in rows)),
        ("Available", sum(r[5] for r in rows)),
        ("On loan", sum(r[6] for r in rows)),
    ]
    return {
        "headers": ["Title", "Author", "ISBN", "Category", "Total", "Available", "On loan"],
        "rows": rows,
        "summary": summary,
    }


def open_loans(start, end):
    today = timezone.now().date()
    issues = (
        Issue.objects.filter(return_date__isnull=True)
        .select_related("book", "member")
        .order_by("due_date")
    )
    rows = []
    overdue_count = 0
    accrued = 0
    for i in issues:
        days = max((today - i.due_date).days, 0)
        fine = i.calculate_fine()
        if days:
            overdue_count += 1
            accrued += fine
        rows.append([
            i.book.title, i.member.name, i.issue_date, i.due_date,
            days, fine, "Overdue" if days else "On time",
        ])
    summary = [
        ("Books currently out", len(rows)),
        ("Overdue", overdue_count),
        ("Fines accruing", accrued),
    ]
    return {
        "headers": ["Book", "Member", "Issued", "Due", "Days overdue", "Fine so far", "Status"],
        "rows": rows,
        "summary": summary,
    }


def fines(start, end):
    issues = (
        Issue.objects.filter(return_date__isnull=False, fine_amount__gt=0)
        .select_related("book", "member")
        .order_by("-return_date")
    )
    if start:
        issues = issues.filter(return_date__gte=start)
    if end:
        issues = issues.filter(return_date__lte=end)

    totals = issues.aggregate(
        total=Sum("fine_amount"),
        collected=Sum("fine_amount", filter=Q(fine_paid=True)),
    )
    total = totals["total"] or 0
    collected = totals["collected"] or 0

    rows = [
        [i.member.name, i.book.title, i.due_date, i.return_date,
         i.fine_amount, "Paid" if i.fine_paid else "Unpaid"]
        for i in issues
    ]
    summary = [
        ("Total fined", total),
        ("Collected", collected),
        ("Outstanding", total - collected),
    ]
    return {
        "headers": ["Member", "Book", "Due", "Returned", "Fine", "Status"],
        "rows": rows,
        "summary": summary,
    }


def member_activity(start, end):
    members = Member.objects.annotate(
        total_loans=Count("issues"),
        current_loans=Count("issues", filter=Q(issues__return_date__isnull=True)),
        fines_charged=Sum("issues__fine_amount"),
        fines_unpaid=Sum("issues__fine_amount", filter=Q(issues__fine_paid=False)),
    ).order_by("-total_loans", "name")

    rows = [
        [m.name, m.email, "Active" if m.is_active else "Inactive",
         m.total_loans, m.current_loans,
         m.fines_charged or 0, m.fines_unpaid or 0]
        for m in members
    ]
    summary = [
        ("Members", len(rows)),
        ("Active members", sum(1 for r in rows if r[2] == "Active")),
        ("Total loans ever", sum(r[3] for r in rows)),
    ]
    return {
        "headers": ["Member", "Email", "Status", "Total loans", "Current loans",
                    "Fines charged", "Fines unpaid"],
        "rows": rows,
        "summary": summary,
    }


def donations(start, end):
    qs = Donation.objects.select_related("donor", "category", "reviewed_by")
    if start:
        qs = qs.filter(submitted_on__date__gte=start)
    if end:
        qs = qs.filter(submitted_on__date__lte=end)

    rows = [
        [d.donor.name, d.title, d.author, d.isbn, d.category.name,
         d.get_condition_display(), d.quantity, d.get_status_display(),
         d.submitted_on.date(),
         d.reviewed_by.username if d.reviewed_by else ""]
        for d in qs
    ]
    approved = qs.filter(status=Donation.Status.APPROVED)
    summary = [
        ("Requests", len(rows)),
        ("Pending", qs.filter(status=Donation.Status.PENDING).count()),
        ("Approved", approved.count()),
        ("Rejected", qs.filter(status=Donation.Status.REJECTED).count()),
        ("Copies added to inventory", approved.aggregate(s=Sum("quantity"))["s"] or 0),
    ]
    return {
        "headers": ["Donor", "Title", "Author", "ISBN", "Category", "Condition",
                    "Qty", "Status", "Submitted", "Reviewed by"],
        "rows": rows,
        "summary": summary,
    }


REPORTS = {
    "inventory": {
        "title": "Book Inventory",
        "description": "Every title with total, available and on-loan copies.",
        "func": inventory, "dates": False,
    },
    "open-loans": {
        "title": "Issued & Overdue Books",
        "description": "All books currently out, with days overdue and the fine so far.",
        "func": open_loans, "dates": False,
    },
    "fines": {
        "title": "Fines",
        "description": "Fines charged, collected and outstanding for returned books.",
        "func": fines, "dates": True,
    },
    "members": {
        "title": "Member Activity",
        "description": "Loans and fines per member.",
        "func": member_activity, "dates": False,
    },
    "donations": {
        "title": "Donations",
        "description": "Donation history and approval summary.",
        "func": donations, "dates": True,
    },
}