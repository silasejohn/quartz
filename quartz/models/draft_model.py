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
    r2_threshold: float = 0.0
    r4_threshold: float = 0.0


class TeamState(BaseModel):
    captain: CaptainEntry
    picks: list[dict] = []

    @property
    def total_pv(self) -> float:
        return self.captain.pv + sum(p["pv"] for p in self.picks)

    @property
    def pick_count(self) -> int:
        return len(self.picks)

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
    threshold: float
    results: dict   # effective_id → {"team_pv": float, "passed": bool}


class DraftResult(BaseModel):
    teams: dict             # effective_id → TeamState.model_dump()
    play_by_play: list[str]
    r2_check: Optional[ThresholdCheck] = None
    r4_check: Optional[ThresholdCheck] = None
    reorder: list[str]      # effective_ids in phase 2 slot order (descending team PV)
