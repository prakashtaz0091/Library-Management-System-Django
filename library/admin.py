from django.contrib import admin
from .models import Category, Book, Member, Issue, Donor, Donation

admin.site.register(Category)
admin.site.register(Book)
admin.site.register(Member)
admin.site.register(Issue)
admin.site.register(Donor)
admin.site.register(Donation)