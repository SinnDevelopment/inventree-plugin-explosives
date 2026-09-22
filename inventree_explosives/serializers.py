"""Read-only serializers for the plugin API.

Plain Serializers rather than ModelSerializers: the payloads are computed
aggregates, not database rows.
"""

from rest_framework import serializers

from .constants import COMPATIBILITY_GROUPS, DIVISIONS


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

    # The vocabularies the edit form's selects use, so the frontend shares one
    # source of truth with the backend rather than hardcoding them.
    divisions = serializers.ListField(child=serializers.CharField(), required=False)
    compatibility_groups = serializers.ListField(
        child=serializers.CharField(), required=False
    )


class PartExplosiveUpdateSerializer(serializers.Serializer):
    """Writable explosive properties of a part (PATCH).

    Every field is optional so a PATCH can touch one field at a time. Masses are
    CharFields, not FloatFields, because the product accepts unit-bearing input
    like "500 g"; validation.validate_mass (pint-backed) is the authority and runs
    when the Parameter row is saved.
    """

    is_explosive = serializers.BooleanField(required=False)
    neq_per_unit_kg = serializers.CharField(required=False, allow_blank=True)
    gross_mass_per_unit_kg = serializers.CharField(required=False, allow_blank=True)
    division = serializers.ChoiceField(
        choices=DIVISIONS, required=False, allow_blank=True
    )
    compatibility_group = serializers.ChoiceField(
        choices=COMPATIBILITY_GROUPS, required=False, allow_blank=True
    )
    un_number = serializers.CharField(required=False, allow_blank=True)
    proper_shipping_name = serializers.CharField(required=False, allow_blank=True)


class LocationLimitUpdateSerializer(serializers.Serializer):
    """The licensed NEQ limit of a location (PATCH).

    A CharField so unit-bearing input ("50000 g") is accepted. Blank removes the
    limit, which is distinct from a 0 kg limit.
    """

    limit_kg = serializers.CharField(required=True, allow_blank=True)


class BootstrapSerializer(serializers.Serializer):
    """Result of re-running the parameter template bootstrap."""

    created = serializers.ListField(child=serializers.CharField())
    existing = serializers.ListField(child=serializers.CharField())
    errors = serializers.ListField(child=serializers.CharField())


class TemplateStatusSerializer(serializers.Serializer):
    """Presence and fitness of one of the plugin's parameter templates."""

    name = serializers.CharField()
    present = serializers.BooleanField()
    ok = serializers.BooleanField()


class StatusSerializer(serializers.Serializer):
    """Read-only health of the plugin's parameter templates.

    Backs the banner on the settings page: 'ready' is False whenever any template
    is missing or misconfigured, so the admin sees the problem without a restart
    or a trip to the server log.
    """

    ready = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.CharField())
    templates = TemplateStatusSerializer(many=True)
