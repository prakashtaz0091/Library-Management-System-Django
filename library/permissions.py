from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()


def is_librarian(user):
    # superusers count as librarians
    return user.is_authenticated and (user.is_superuser or in_group(user, "Librarian"))


def is_donor(user):
    return in_group(user, "Donor")


def is_member(user):
    return in_group(user, "Member")


def librarian_required(view_func):
    """Login required, and the user must be a librarian (else 403)."""
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_librarian(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper


def donor_required(view_func):
    """Login required, and the user must be in the Donor group (else 403)."""
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_donor(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper









