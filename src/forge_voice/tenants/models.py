"""Pydantic schema for a synthetic home-services tenant.

The schema mirrors the tenant contract in roadmap #5. It is intentionally strict: unknown
fields, malformed ZIP rules and dangling references fail closed before a tenant can start.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from forge_voice.models import StrictModel, ensure_unique
from forge_voice.tenants.errors import UnknownServiceError

ZIP_RE = re.compile(r"^\d{5}$")
HOUR_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")

Zip = Annotated[str, Field(pattern=r"^\d{5}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Phone = Annotated[str, Field(pattern=r"^\+1\d{10}$")]


class PriceRange(StrictModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)
    currency: Literal["USD"]

    @model_validator(mode="after")
    def max_not_below_min(self) -> PriceRange:
        if self.max < self.min:
            raise ValueError("price_range.max must be greater than or equal to min")
        return self


class Persona(StrictModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    greeting: str = Field(min_length=1)
    disclosure: str = Field(min_length=1)


class BusinessHours(StrictModel):
    monday: list[str] = Field(default_factory=list)
    tuesday: list[str] = Field(default_factory=list)
    wednesday: list[str] = Field(default_factory=list)
    thursday: list[str] = Field(default_factory=list)
    friday: list[str] = Field(default_factory=list)
    saturday: list[str] = Field(default_factory=list)
    sunday: list[str] = Field(default_factory=list)

    @field_validator("*")
    @classmethod
    def validate_ranges(cls, ranges: list[str]) -> list[str]:
        for value in ranges:
            match = HOUR_RANGE_RE.fullmatch(value)
            if match is None:
                raise ValueError(f"invalid business-hours range {value!r}; expected HH:MM-HH:MM")
            if match.group(1) >= match.group(2):
                raise ValueError(f"business-hours range {value!r} must end after it starts")
        return ranges


class Service(StrictModel):
    id: Identifier
    name: str = Field(min_length=1)
    duration_minutes: int = Field(gt=0)
    price_range: PriceRange
    after_hours_eligible: bool
    emergency_eligible: bool


class ServiceArea(StrictModel):
    zip_allowlist: list[Zip] = Field(min_length=1)
    zip_exclusions: list[Zip] = Field(default_factory=list)
    dispatch_zones: dict[Zip, str] = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def validate_zip_rules(self) -> ServiceArea:
        ensure_unique(self.zip_allowlist, "zip_allowlist")
        ensure_unique(self.zip_exclusions, "zip_exclusions")
        allowed = set(self.zip_allowlist)
        excluded = set(self.zip_exclusions)
        outside = excluded - allowed
        if outside:
            raise ValueError(f"zip_exclusions must be a subset of zip_allowlist: {sorted(outside)}")
        served = allowed - excluded
        if set(self.dispatch_zones) != served:
            missing = sorted(served - set(self.dispatch_zones))
            extra = sorted(set(self.dispatch_zones) - served)
            raise ValueError(
                "dispatch_zones must cover exactly the served ZIPs; "
                f"missing={missing}, extra={extra}"
            )
        if any(not zone.strip() for zone in self.dispatch_zones.values()):
            raise ValueError("dispatch_zone names must not be empty")
        return self


class Technician(StrictModel):
    id: Identifier
    name: str = Field(min_length=1)
    skills: list[Identifier] = Field(min_length=1)
    zips: list[Zip] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_lists(self) -> Technician:
        ensure_unique(self.skills, "technician skills")
        ensure_unique(self.zips, "technician zips")
        return self


class Dispatch(StrictModel):
    strategy: Literal["nearest_skill_match"]
    max_drive_minutes: int = Field(gt=0)
    technicians: list[Technician] = Field(min_length=1)


class Policies(StrictModel):
    change_cutoff_minutes: int = Field(ge=0)
    booking_horizon_days: int = Field(gt=0, le=30)
    offer_ttl_seconds: int = Field(gt=0)
    confirmation_ttl_seconds: int = Field(gt=0)
    tool_timeout_ms: int = Field(gt=0)
    max_slots_offered: int = Field(ge=2, le=3)
    max_reprompts: int = Field(ge=1)
    recording: Literal["disclose_and_allow_opt_out"]
    data_retention_days: int = Field(gt=0)


class EmergencyCategory(StrictModel):
    id: Identifier
    label: str = Field(min_length=1)
    severity: Literal["life_safety", "urgent", "priority"]
    triggers: list[str] = Field(default_factory=list)
    safety_script: Identifier
    transfer_target: Identifier
    threshold: str | None = None

    @model_validator(mode="after")
    def has_trigger_or_threshold(self) -> EmergencyCategory:
        if not self.triggers and not self.threshold:
            raise ValueError(f"emergency category {self.id} needs triggers or a threshold")
        return self


class OnCall(StrictModel):
    target: Identifier
    ring_seconds: int = Field(gt=0)
    callback_sla_minutes: int = Field(gt=0)


class AfterHours(StrictModel):
    emergency: Literal["on_call"]
    non_emergency: Literal["next_business_day_callback"]


class Emergency(StrictModel):
    categories: list[EmergencyCategory] = Field(min_length=1)
    on_call: OnCall
    after_hours: AfterHours


class HandoffTarget(StrictModel):
    id: Identifier
    name: str = Field(min_length=1)
    phone: Phone
    hours: Literal["business_hours", "after_hours_and_emergency", "always"]


class Handoff(StrictModel):
    targets: list[HandoffTarget] = Field(min_length=1)
    default_target: Identifier
    callback_sla_minutes: dict[str, int | Literal["next_business_day"]]


class AdapterConfig(StrictModel):
    adapter: Identifier
    config: dict[str, str | list[str]]


class Integrations(StrictModel):
    calendar: AdapterConfig
    crm: AdapterConfig
    messaging: AdapterConfig


class FaqEntry(StrictModel):
    id: Identifier
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class PricingEntry(StrictModel):
    service_id: Identifier
    range: PriceRange
    includes: list[str] = Field(min_length=1)
    excludes: list[str] = Field(default_factory=list)
    caveat: str = Field(min_length=1)


class PolicyEntry(StrictModel):
    id: Identifier
    answer: str = Field(min_length=1)


class KnowledgeBase(StrictModel):
    faq: list[FaqEntry] = Field(min_length=1)
    pricing: list[PricingEntry] = Field(min_length=1)
    policies: list[PolicyEntry] = Field(min_length=1)


class TenantConfig(StrictModel):
    tenant_id: Identifier
    display_name: str = Field(min_length=1)
    legal_name: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    locale: Literal["en-US"]
    currency: Literal["USD"]
    persona: Persona
    business_hours: BusinessHours
    holidays: list[date] = Field(default_factory=list)
    services: list[Service] = Field(min_length=1)
    service_area: ServiceArea
    dispatch: Dispatch
    policies: Policies
    emergency: Emergency
    handoff: Handoff
    integrations: Integrations
    knowledge_base: KnowledgeBase

    @model_validator(mode="after")
    def validate_cross_references(self) -> TenantConfig:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone {self.timezone!r}") from exc

        service_ids = [service.id for service in self.services]
        ensure_unique(service_ids, "service ids")
        known_services = set(service_ids)
        ensure_unique([tech.id for tech in self.dispatch.technicians], "technician ids")
        ensure_unique([target.id for target in self.handoff.targets], "handoff target ids")

        for tech in self.dispatch.technicians:
            unknown_skills = set(tech.skills) - known_services
            if unknown_skills:
                raise ValueError(
                    f"technician {tech.id} references unknown services: {sorted(unknown_skills)}"
                )
            unknown_zips = set(tech.zips) - set(self.service_area.zip_allowlist)
            if unknown_zips:
                raise ValueError(
                    f"technician {tech.id} references ZIPs outside the allowlist: "
                    f"{sorted(unknown_zips)}"
                )

        target_ids = {target.id for target in self.handoff.targets}
        if self.handoff.default_target not in target_ids:
            raise ValueError(
                f"handoff.default_target {self.handoff.default_target!r} is not a target"
            )
        for category in self.emergency.categories:
            if category.transfer_target not in target_ids:
                raise ValueError(
                    f"emergency category {category.id} references unknown transfer target "
                    f"{category.transfer_target!r}"
                )
        if self.emergency.on_call.target not in target_ids:
            raise ValueError(
                f"emergency.on_call target {self.emergency.on_call.target!r} is not a target"
            )
        ensure_unique(
            [category.id for category in self.emergency.categories],
            "emergency category ids",
        )

        unknown_pricing = {
            entry.service_id for entry in self.knowledge_base.pricing
        } - known_services
        if unknown_pricing:
            raise ValueError(
                f"knowledge_base.pricing references unknown services: {sorted(unknown_pricing)}"
            )
        ensure_unique(
            [entry.service_id for entry in self.knowledge_base.pricing],
            "pricing service ids",
        )
        ensure_unique([entry.id for entry in self.knowledge_base.faq], "FAQ ids")
        ensure_unique([entry.id for entry in self.knowledge_base.policies], "policy ids")
        return self

    def require_service(self, service_id: str) -> Service:
        """Return a configured service or fail closed."""
        for service in self.services:
            if service.id == service_id:
                return service
        raise UnknownServiceError(
            f"tenant {self.tenant_id!r} does not offer service {service_id!r}"
        )

    def has_zip(self, zip_code: str) -> bool:
        return ZIP_RE.fullmatch(zip_code) is not None and (
            zip_code in self.service_area.zip_allowlist
            and zip_code not in self.service_area.zip_exclusions
        )
