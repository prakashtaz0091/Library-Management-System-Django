from .permissions import is_donor, is_librarian, is_member


def roles(request):
    return {
        "user_is_librarian": is_librarian(request.user),
        "user_is_member": is_member(request.user),
        "user_is_donor": is_donor(request.user),
    }