from django.contrib import admin

from .models import Passport


@admin.register(Passport)
class PassportAdmin(admin.ModelAdmin):
    list_display = ("id", "parcel", "data_hash", "prev_hash", "created_at")
    readonly_fields = ("data_hash", "prev_hash")
