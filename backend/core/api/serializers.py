"""Serializers validate shape and type at the boundary, and nothing else.

Business rules live in services (§9.1). A serializer that starts asking whether
a sale exceeds the units held is a serializer that has taken a rule out of the
one place it belongs.
"""

from __future__ import annotations

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(max_length=256, trim_whitespace=False)
