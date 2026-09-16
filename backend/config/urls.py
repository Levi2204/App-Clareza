from django.urls import path, include
from rest_framework.routers import DefaultRouter
from finance import api
from finance.profile import profile
router = DefaultRouter()
for prefix, view in [('accounts', api.AccountViewSet), ('cards', api.CardViewSet), ('categories', api.CategoryViewSet), ('transactions', api.TransactionViewSet), ('invoices', api.InvoiceViewSet), ('subscriptions', api.SubscriptionViewSet), ('goals', api.GoalViewSet), ('bills', api.BillViewSet), ('installment-purchases', api.InstallmentPurchaseViewSet)]:
    router.register(prefix, view)
urlpatterns = [path('api/v1/profile/', profile), path('api/v1/sync/', api.sync), path('api/v1/dashboard/', api.dashboard), path('api/v1/planning/<int:year>/<int:month>/', api.dashboard), path('api/v1/history/<int:year>/<int:month>/', api.dashboard), path('api/v1/payments/upcoming/', api.upcoming), path('api/v1/payments/pending/', api.pending), path('api/v1/', include(router.urls))]
