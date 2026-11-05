from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the Librarian, Member and Donor groups"

    def handle(self, *args, **options):
        for name in ["Librarian", "Member", "Donor"]:
            _, created = Group.objects.get_or_create(name=name)
            self.stdout.write(f"{name}: {'created' if created else 'already exists'}")