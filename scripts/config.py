"""
Generator configuration — controls data shape for synthetic billing generation.
Pass a GeneratorConfig to any generator's generate() function.
"""
from dataclasses import dataclass, field


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
}
