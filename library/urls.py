from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register_donor, name="register"),
    
    path("books/", views.book_list, name="book_list"),
    path("books/add/", views.book_create, name="book_create"),
    path("books/<int:pk>/edit/", views.book_update, name="book_update"),
    path("books/<int:pk>/delete/", views.book_delete, name="book_delete"),
    
    path("members/", views.member_list, name="member_list"),
    path("members/add/", views.member_create, name="member_create"),
    path("members/<int:pk>/edit/", views.member_update, name="member_update"),
    path("members/<int:pk>/toggle/", views.member_toggle_active, name="member_toggle_active"),
    
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/new/", views.issue_create, name="issue_create"),
    path("issues/<int:pk>/return/", views.return_book, name="return_book"),
    path("issues/<int:pk>/pay/", views.pay_fine, name="pay_fine"),
    path("my-loans/", views.my_loans, name="my_loans"),
    
    path("donate/", views.donation_create, name="donation_create"),
    path("donations/mine/", views.my_donations, name="my_donations"),
    path("donations/", views.donation_list, name="donation_list"),
    path("donations/<int:pk>/approve/", views.donation_approve, name="donation_approve"),
    path("donations/<int:pk>/reject/", views.donation_reject, name="donation_reject"),
    
    path("reports/", views.report_index, name="report_index"),
    path("reports/<slug:name>/", views.report_view, name="report_view"),
    
]