from django.contrib import admin
from models import *

class CategoryAdmin(admin.ModelAdmin):
    pass


class ProductAdmin(admin.ModelAdmin):
    pass


class QuantityInline(admin.TabularInline):
    model = SoldQuantity
    


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('date',)    
    inlines = [
        QuantityInline,
    ]
    


admin.site.register(ProductCategory, CategoryAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(WarehouseEntry, admin.ModelAdmin)
admin.site.register(SaleInvoice, InvoiceAdmin)
