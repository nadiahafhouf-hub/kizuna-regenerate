import hashlib
import json

from django.db import models, transaction

from core.models import Parcel

GENESIS_HASH = "0" * 64


def canonical_json(data) -> str:
    """Sérialisation stable (clés triées, sans espaces) pour un hash reproductible."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Passport(models.Model):
    """Bloc 4 : passeport du sol. Chaîne de hash locale :
    data_hash = sha256(prev_hash + JSON canonique du LandProfile)."""

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="passeports")
    land_profile = models.JSONField()
    prev_hash = models.CharField(max_length=64, default=GENESIS_HASH)
    data_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Passeport #{self.pk} {self.parcel.parcelle_id} {self.data_hash[:10]}"

    def compute_hash(self) -> str:
        payload = self.prev_hash + canonical_json(self.land_profile)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self.pk:
            with transaction.atomic():
                last = Passport.objects.select_for_update().order_by("-id").first()
                self.prev_hash = last.data_hash if last else GENESIS_HASH
                self.data_hash = self.compute_hash()
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def is_valid(self) -> bool:
        """Vérifie que le contenu n'a pas été modifié et que le lien avec le précédent tient."""
        if self.compute_hash() != self.data_hash:
            return False
        prev = Passport.objects.filter(id__lt=self.id).order_by("-id").first()
        return self.prev_hash == (prev.data_hash if prev else GENESIS_HASH)
