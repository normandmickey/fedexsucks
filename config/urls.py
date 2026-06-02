"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from tracker.views import home, internal_api_health, internal_api_package_detail, internal_api_package_latest_status, internal_api_package_search, package_detail, payroll_tax_lookup, research, weather_forecast

urlpatterns = [
    path('', home, name='home'),
    path('api/internal/health/', internal_api_health, name='internal_api_health'),
    path('api/internal/packages/search/', internal_api_package_search, name='internal_api_package_search'),
    path('api/internal/packages/<str:tracking_number>/', internal_api_package_detail, name='internal_api_package_detail'),
    path('api/internal/packages/<str:tracking_number>/latest-status/', internal_api_package_latest_status, name='internal_api_package_latest_status'),
    path('packages/<str:tracking_number>/', package_detail, name='package_detail'),
    path('research/', research, name='research'),
    path('weather/', weather_forecast, name='weather_forecast'),
    path('payroll-tax/', payroll_tax_lookup, name='payroll_tax_lookup'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
]
