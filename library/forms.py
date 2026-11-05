from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.db import transaction

from django.contrib.auth import password_validation
from django.conf import settings
from .models import Book, Donation, Donor, Issue, Member


class MemberForm(forms.ModelForm):
    # Only used when creating a new member
    create_login = forms.BooleanField(required=False, label="Create a login account")
    username = forms.CharField(max_length=150, required=False)
    password = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = Member
        fields = ["name", "email", "phone", "address", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs["class"] = css
        # login fields make sense only on create
        if self.instance.pk:
            for name in ("create_login", "username", "password"):
                del self.fields[name]
        else:
            del self.fields["is_active"]

    def clean(self):
        data = super().clean()
        if not self.instance.pk and data.get("create_login"):
            username = data.get("username")
            password = data.get("password")
            if not username:
                self.add_error("username", "Required when creating a login.")
            elif User.objects.filter(username=username).exists():
                self.add_error("username", "This username is already taken.")
            if not password:
                self.add_error("password", "Required when creating a login.")
            else:
                try:
                    password_validation.validate_password(password)
                except forms.ValidationError as e:
                    self.add_error("password", e)
        return data

    @transaction.atomic
    def save(self, commit=True):
        member = super().save(commit=False)

        if not self.instance.pk and self.cleaned_data.get("create_login"):
            user = User.objects.create_user(
                username=self.cleaned_data["username"],
                email=member.email,
                password=self.cleaned_data["password"],
            )
            group, _ = Group.objects.get_or_create(name="Member")
            user.groups.add(group)
            member.user = user

        member.save()

        # keep the linked login in sync with the member record
        if member.user:
            member.user.is_active = member.is_active
            member.user.email = member.email
            member.user.save()
        return member


class DonorRegistrationForm(UserCreationForm):
    name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.save()
        Donor.objects.create(
            user=user,
            name=self.cleaned_data["name"],
            phone=self.cleaned_data["phone"],
            address=self.cleaned_data["address"],
        )
        group, _ = Group.objects.get_or_create(name="Donor")
        user.groups.add(group)
        return user
    
    
class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["title", "author", "isbn", "category", "total_copies"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["category"].widget.attrs["class"] = "form-select"

    def clean_total_copies(self):
        total = self.cleaned_data["total_copies"]
        if self.instance.pk:
            on_loan = self.instance.total_copies - self.instance.available_copies
            if total < on_loan:
                raise forms.ValidationError(
                    f"{on_loan} copies are currently on loan, so total can't be below that."
                )
        return total

    def save(self, commit=True):
        book = super().save(commit=False)
        if not book.pk:
            book.available_copies = book.total_copies
        else:
            on_loan = self.initial["total_copies"] - book.available_copies
            book.available_copies = book.total_copies - on_loan
        if commit:
            book.save()
        return book
    
    
class IssueForm(forms.Form):
    book = forms.ModelChoiceField(
        queryset=Book.objects.filter(available_copies__gt=0),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Only books with available copies are listed.",
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Only active members are listed.",
    )

    def clean(self):
        data = super().clean()
        book, member = data.get("book"), data.get("member")
        if book and member:
            open_loans = Issue.objects.filter(member=member, return_date__isnull=True)
            if open_loans.count() >= settings.MAX_BOOKS_PER_MEMBER:
                raise forms.ValidationError(
                    f"{member.name} already has {settings.MAX_BOOKS_PER_MEMBER} books out."
                )
            if open_loans.filter(book=book).exists():
                raise forms.ValidationError(
                    f"{member.name} already has a copy of this book."
                )
        return data    


class DonationForm(forms.ModelForm):
    class Meta:
        model = Donation
        fields = ["title", "author", "isbn", "category", "condition", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["category"].widget.attrs["class"] = "form-select"
        self.fields["condition"].widget.attrs["class"] = "form-select"
        self.fields["quantity"].min_value = 1
        self.fields["quantity"].widget.attrs["min"] = 1

    def clean_isbn(self):
        return self.cleaned_data["isbn"].strip()

    def clean_quantity(self):
        qty = self.cleaned_data["quantity"]
        if qty < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return qty    










    
    