"""Read-only serializers for the plugin API.

Plain Serializers rather than ModelSerializers: the payloads are computed
aggregates, not database rows.
"""

from rest_framework import serializers


class StockItemNEQSerializer(serializers.Serializer):
    """One stock item's contribution to a magazine total."""

    stock_item_id = serializers.IntegerField()
    part_id = serializers.IntegerField()
    part_name = serializers.CharField()
    location_id = serializers.IntegerField(allow_null=True)
    location_name = serializers.CharField(allow_null=True)
    quantity = serializers.FloatField()
    neq_per_unit_kg = serializers.FloatField(allow_null=True)
    neq_total_kg = serializers.FloatField(allow_null=True)
    division = serializers.CharField(allow_null=True)
    compatibility_group = serializers.CharField(allow_null=True)
    classification_code = serializers.CharField(allow_null=True)
    un_number = serializers.CharField(allow_null=True)


class LocationNEQSerializer(serializers.Serializer):
    """Everything the location panel and the magazine register need."""

    location_id = serializers.IntegerField()
    location_name = serializers.CharField()

    neq_kg = serializers.FloatField()
    gross_mass_kg = serializers.FloatField()

    # None when the location has no licensed limit set.
    limit_kg = serializers.FloatField(allow_null=True)
    utilisation = serializers.FloatField(allow_null=True)
    over_limit = serializers.BooleanField()

    include_sublocations = serializers.BooleanField()

    by_division = serializers.DictField(child=serializers.FloatField())
    items = StockItemNEQSerializer(many=True)

    # e.g. a colliding parameter template declared in grams.
    config_errors = serializers.ListField(child=serializers.CharField(), required=False)


class PartExplosiveSerializer(serializers.Serializer):
    """The explosive properties of a single part."""

    is_explosive = serializers.BooleanField()
    neq_per_unit_kg = serializers.FloatField(allow_null=True)
    gross_mass_per_unit_kg = serializers.FloatField(allow_null=True)
    division = serializers.CharField(allow_null=True)
    compatibility_group = serializers.CharField(allow_null=True)
    classification_code = serializers.CharField(allow_null=True)
    un_number = serializers.CharField(allow_null=True)
    proper_shipping_name = serializers.CharField(allow_null=True)
    issues = serializers.ListField(child=serializers.CharField())


class BootstrapSerializer(serializers.Serializer):
    """Result of re-running the parameter template bootstrap."""

    created = serializers.ListField(child=serializers.CharField())
    existing = serializers.ListField(child=serializers.CharField())
    errors = serializers.ListField(child=serializers.CharField())
