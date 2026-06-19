from authorization_in_the_middle import build_entity_payload, entity_uid, resolve_jwt_principal

from src.config import settings

NAMESPACE = "notification"
_PLATFORM_EMAIL_RELAY_TYPE = f"{NAMESPACE}::PlatformEmailRelay"
_PLATFORM_EMAIL_RELAY_ID = "default"


def resolve_principal():
    return resolve_jwt_principal(NAMESPACE)


def build_platform_email_relay_resource():
    return build_entity_payload(
        _PLATFORM_EMAIL_RELAY_TYPE,
        _PLATFORM_EMAIL_RELAY_ID,
        {
            "issuer": settings.platform_jwt_issuer or "",
            "allowedSubjects": sorted(settings.platform_jwt_allowed_subjects),
        },
    )


def platform_email_relay_entities():
    return [resolve_principal(), build_platform_email_relay_resource()]


def platform_email_relay_resource_uid() -> str:
    return entity_uid(_PLATFORM_EMAIL_RELAY_TYPE, _PLATFORM_EMAIL_RELAY_ID)
