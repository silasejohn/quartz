"""
Draft data models for the Quartz draft simulation.
"""
from typing import Optional

from pydantic import BaseModel

ROLES = ["TOP", "JGL", "MID", "BOT", "SUP"]


class CaptainEntry(BaseModel):
    effective_id: str
    pv: float
    primary_pos: Optional[str] = None
    secondary_pos: Optional[str] = None
    slot: int                   # 1-indexed pick slot


class DraftConfig(BaseModel):
    captains: list[CaptainEntry]    # sorted by slot
    player_pool: list[dict]         # {effective_id, pv, primary_pos, secondary_pos, player_type}
    picks_per_captain: int = 4
    r2_threshold: float = 0.0
    r4_threshold: float = 0.0
    reorder_after_round: Optional[int] = None
    soft_cap_trigger: Optional[float] = None
    soft_cap_scale: float = 0.5


class TeamState(BaseModel):
    captain: CaptainEntry
    picks: list[dict] = []
    soft_cap_raise: float = 0.0     # computed after pick 1 if soft cap triggered

    @property
    def total_pv(self) -> float:
        return self.captain.pv + sum(p["pv"] for p in self.picks)

    @property
    def pick_count(self) -> int:
        return len(self.picks)

    def effective_threshold(self, base: float) -> float:
        return base + self.soft_cap_raise

    def _all_positions(self) -> list[str]:
        pos = [self.captain.primary_pos, self.captain.secondary_pos]
        for p in self.picks:
            pos.extend([p.get("primary_pos"), p.get("secondary_pos")])
        return [x for x in pos if x]

    def unfilled_roles(self) -> list[str]:
        covered = set(self._all_positions())
        return [r for r in ROLES if r not in covered]


class ThresholdCheck(BaseModel):
    after_round: int
    base_threshold: float
    results: dict   # effective_id → {"team_pv", "soft_cap_raise", "effective_threshold", "passed"}


class DraftResult(BaseModel):
    teams: dict             # effective_id → TeamState.model_dump()
    play_by_play: list[str]
    r2_check: Optional[ThresholdCheck] = None
    r4_check: Optional[ThresholdCheck] = None
    reorder: Optional[list[str]] = None     # set only when reorder_after_round is configured
