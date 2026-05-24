"""
PV weights persistence — load/save PVWeights to/from pv_weights.json.

pv_weights.json is the single source of truth for active weight configuration.
PVWeights() defaults are used as fallback when no file exists.

Usage:
    from quartz.pv_weights_io import load_weights, save_weights
    weights = load_weights(base_data_dir)
    save_weights(weights, base_data_dir)
"""

import json
import os

from quartz.models.pv_model import PVWeights

WEIGHTS_FILENAME = "pv_weights.json"


def load_weights(base_data_dir: str) -> tuple[PVWeights, bool]:
    """
    Load PVWeights from pv_weights.json in base_data_dir.

    Returns (weights, from_file):
      weights   — PVWeights instance (from file or defaults)
      from_file — True if loaded from file, False if using defaults
    """
    path = os.path.join(base_data_dir, WEIGHTS_FILENAME)
    if not os.path.exists(path):
        return PVWeights(), False

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return PVWeights(**data), True


def save_weights(weights: PVWeights, base_data_dir: str) -> str:
    """
    Serialize PVWeights to pv_weights.json in base_data_dir.
    Returns the full path written.
    """
    path = os.path.join(base_data_dir, WEIGHTS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(weights.model_dump(), f, indent=2)
    return path
