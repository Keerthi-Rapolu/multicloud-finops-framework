"""
Generator configuration — controls data shape for synthetic billing generation.
Pass a GeneratorConfig to any generator's generate() function.
"""
import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta


TEAM_METADATA: dict[str, dict[str, str]] = {
    "platform": {
        "business_unit": "engineering",
        "application": "platform-core",
        "owner_email": "platform-owner@company.com",
        "support_group": "platform-operations",
    },
    "data-eng": {
        "business_unit": "data",
        "application": "data-platform",
        "owner_email": "data-eng-owner@company.com",
        "support_group": "data-platform-ops",
    },
    "frontend": {
        "business_unit": "product",
        "application": "customer-web",
        "owner_email": "frontend-owner@company.com",
        "support_group": "customer-experience-support",
    },
    "backend": {
        "business_unit": "product",
        "application": "core-api",
        "owner_email": "backend-owner@company.com",
        "support_group": "api-operations",
    },
    "ml": {
        "business_unit": "ai",
        "application": "ml-platform",
        "owner_email": "ml-owner@company.com",
        "support_group": "ml-platform-sre",
    },
}


def infer_workload_criticality(team: str | None, env: str) -> str:
    env_norm = str(env).lower()
    team_norm = str(team).lower() if team is not None else "unattributed"

    if env_norm == "prod" and team_norm == "platform":
        return "mission_critical"
    if env_norm == "prod":
        return "high"
    if env_norm in {"staging", "test", "qa", "nonprod"}:
        return "medium"
    return "low"


def sla_tier_for_criticality(workload_criticality: str) -> str:
    return {
        "mission_critical": "platinum",
        "high": "gold",
        "medium": "silver",
        "low": "bronze",
    }.get(workload_criticality, "bronze")


def workload_metadata(team: str | None, env: str) -> dict[str, str]:
    team_norm = str(team).lower() if team is not None else "unattributed"
    base = TEAM_METADATA.get(
        team_norm,
        {
            "business_unit": "shared-services",
            "application": "unassigned",
            "owner_email": "unassigned-owner@company.com",
            "support_group": "finops-governance",
        },
    ).copy()
    criticality = infer_workload_criticality(team, env)
    base["workload_criticality"] = criticality
    base["sla_tier"] = sla_tier_for_criticality(criticality)
    return base


_RESOURCE_TELEMETRY_PROFILES: dict[str, dict[str, tuple[float, float] | tuple[int, int]]] = {
    "active_compute": {
        "cpu": (32.0, 58.0),
        "memory": (38.0, 66.0),
        "disk": (24.0, 52.0),
        "idle_hours": (4, 28),
        "stale_days": (0, 2),
    },
    "steady_compute": {
        "cpu": (22.0, 42.0),
        "memory": (28.0, 52.0),
        "disk": (18.0, 42.0),
        "idle_hours": (12, 72),
        "stale_days": (1, 4),
    },
    "bursty_compute": {
        "cpu": (7.0, 20.0),
        "memory": (12.0, 28.0),
        "disk": (9.0, 24.0),
        "idle_hours": (72, 220),
        "stale_days": (3, 12),
    },
    "zombie_compute": {
        "cpu": (0.5, 5.0),
        "memory": (2.0, 10.0),
        "disk": (1.0, 8.0),
        "idle_hours": (240, 720),
        "stale_days": (14, 45),
    },
    "active_storage": {
        "cpu": (0.0, 0.0),
        "memory": (0.0, 0.0),
        "disk": (28.0, 62.0),
        "idle_hours": (0, 24),
        "stale_days": (0, 2),
    },
    "warm_storage": {
        "cpu": (0.0, 0.0),
        "memory": (0.0, 0.0),
        "disk": (10.0, 28.0),
        "idle_hours": (48, 220),
        "stale_days": (4, 18),
    },
    "cold_storage": {
        "cpu": (0.0, 0.0),
        "memory": (0.0, 0.0),
        "disk": (1.0, 10.0),
        "idle_hours": (220, 720),
        "stale_days": (15, 60),
    },
}


def _stable_rng(*parts: object) -> random.Random:
    raw = "|".join(str(part) for part in parts)
    seed = int(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def _resource_profile(resource_kind: str, team: str | None, env: str, criticality: str) -> str:
    resource_norm = str(resource_kind).lower()
    env_norm = str(env).lower()
    team_norm = str(team).lower() if team is not None else "unattributed"

    if resource_norm in {"s3", "gcs", "storage", "blob", "bucket"}:
        if "archive" in team_norm or env_norm in {"dev", "sandbox"}:
            return "cold_storage"
        if env_norm in {"staging", "test", "qa", "nonprod"}:
            return "warm_storage"
        return "active_storage"

    if team is None or env_norm in {"dev", "sandbox"}:
        return "zombie_compute"
    if env_norm in {"staging", "test", "qa", "nonprod"}:
        return "bursty_compute"
    if criticality == "mission_critical":
        return "active_compute"
    if criticality == "high":
        return "steady_compute"
    return "bursty_compute"


def telemetry_profile(
    resource_kind: str,
    resource_key: str,
    team: str | None,
    env: str,
    observed_at: datetime,
) -> dict[str, float | int | str]:
    metadata = workload_metadata(team, env)
    criticality = metadata["workload_criticality"]
    profile_name = _resource_profile(resource_kind, team, env, criticality)
    profile = _RESOURCE_TELEMETRY_PROFILES[profile_name]
    rng = _stable_rng(resource_kind, resource_key, team, env, observed_at.isoformat())

    cpu_low, cpu_high = profile["cpu"]
    mem_low, mem_high = profile["memory"]
    disk_low, disk_high = profile["disk"]
    idle_low, idle_high = profile["idle_hours"]
    stale_low, stale_high = profile["stale_days"]

    cpu_util_pct = round(rng.uniform(cpu_low, cpu_high), 2)
    memory_util_pct = round(rng.uniform(mem_low, mem_high), 2)
    disk_util_pct = round(rng.uniform(disk_low, disk_high), 2)
    idle_hours = int(round(rng.uniform(idle_low, idle_high)))
    stale_days = rng.uniform(stale_low, stale_high)

    if profile_name in {"active_compute", "active_storage"}:
        idle_hours = max(0, idle_hours - int(rng.uniform(0, 6)))
    if profile_name in {"zombie_compute", "cold_storage"}:
        idle_hours = max(idle_hours, int(rng.uniform(240, 720)))

    last_activity_at = observed_at - timedelta(days=stale_days, hours=rng.uniform(0, 18))
    return {
        "cpu_util_pct": cpu_util_pct,
        "memory_util_pct": memory_util_pct,
        "disk_util_pct": disk_util_pct,
        "idle_hours": idle_hours,
        "last_activity_at": last_activity_at.replace(microsecond=0).isoformat() + "Z",
        "telemetry_profile": profile_name,
    }


@dataclass
class GeneratorConfig:
    # What fraction of resources have NO cost allocation tags (0.0 – 1.0)
    untagged_pct: float = 0.15

    # AWS/GCP discount mix for compute resources (must sum to <= 1.0)
    ri_pct:  float = 0.20   # fraction covered by Reserved Instances / CUD
    sp_pct:  float = 0.15   # fraction covered by Savings Plans / SUD
    # on_demand_pct is derived: 1 - ri_pct - sp_pct

    # How many hours to sample per resource across the month
    # 72  = every 10th hour (fast, good for dev)
    # 720 = full month (realistic volume)
    sample_hours: int = 72

    # Global cost multiplier applied to all on-demand rates.
    # Use values > 1.0 to simulate cost spikes, < 1.0 for reductions.
    cost_multiplier: float = 1.0

    # Random seed. None = derive from billing_month hash (deterministic per month,
    # different across months). Set an integer for fully reproducible output.
    seed: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.untagged_pct <= 1.0:
            raise ValueError(f"untagged_pct must be 0–1, got {self.untagged_pct}")
        if self.ri_pct + self.sp_pct > 1.0:
            raise ValueError("ri_pct + sp_pct cannot exceed 1.0")
        if self.sample_hours < 1 or self.sample_hours > 720:
            raise ValueError(f"sample_hours must be 1–720, got {self.sample_hours}")
        if self.cost_multiplier <= 0:
            raise ValueError(f"cost_multiplier must be > 0, got {self.cost_multiplier}")

    def discount_pool(self, scale: int = 10) -> list[str]:
        """
        Build a weighted list used with random.choice() to assign discount type.
        scale controls granularity — higher = finer percentages.
        """
        ri_n  = round(self.ri_pct  * scale)
        sp_n  = round(self.sp_pct  * scale)
        od_n  = scale - ri_n - sp_n
        return ["ri"] * ri_n + ["sp"] * sp_n + ["on_demand"] * max(od_n, 0)

    def summary(self) -> str:
        od_pct = 1.0 - self.ri_pct - self.sp_pct
        mult_str = f"  x{self.cost_multiplier:.2f}" if self.cost_multiplier != 1.0 else ""
        return (
            f"untagged={self.untagged_pct:.0%}  "
            f"RI={self.ri_pct:.0%}  SP={self.sp_pct:.0%}  OD={od_pct:.0%}  "
            f"hours={self.sample_hours}{mult_str}"
        )


# ---------------------------------------------------------------------------
# Named scenarios — use with --scenario flag
# ---------------------------------------------------------------------------
SCENARIOS: dict[str, GeneratorConfig] = {
    "normal": GeneratorConfig(
        untagged_pct=0.15,
        ri_pct=0.20,
        sp_pct=0.15,
        sample_hours=72,
    ),
    "untagged-medium": GeneratorConfig(
        untagged_pct=0.35,
        ri_pct=0.20,
        sp_pct=0.15,
        sample_hours=72,
    ),
    "untagged-heavy": GeneratorConfig(
        untagged_pct=0.55,
        ri_pct=0.20,
        sp_pct=0.15,
        sample_hours=72,
    ),
    "ri-heavy": GeneratorConfig(
        untagged_pct=0.15,
        ri_pct=0.60,
        sp_pct=0.10,
        sample_hours=72,
    ),
    "sp-heavy": GeneratorConfig(
        untagged_pct=0.15,
        ri_pct=0.10,
        sp_pct=0.60,
        sample_hours=72,
    ),
    "full-month": GeneratorConfig(
        untagged_pct=0.15,
        ri_pct=0.20,
        sp_pct=0.15,
        sample_hours=720,
    ),
    "full-month-untagged": GeneratorConfig(
        untagged_pct=0.55,
        ri_pct=0.20,
        sp_pct=0.15,
        sample_hours=720,
    ),
    # showcase: high RI coverage (more waste), moderate untagged gap, month-varying seed.
    # Use with --cost-multiplier to simulate MoM cost changes across the 5-month window.
    "showcase": GeneratorConfig(
        untagged_pct=0.30,
        ri_pct=0.50,
        sp_pct=0.10,
        sample_hours=72,
    ),
    "decision-engine": GeneratorConfig(
        untagged_pct=0.18,
        ri_pct=0.35,
        sp_pct=0.20,
        sample_hours=144,
        cost_multiplier=1.05,
    ),
}
