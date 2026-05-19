"""Default system configuration values.

These serve as the fallback when no database override exists.  The
``ConfigService`` loads them into the ``system_config`` table on first
startup and uses them as the source of truth for ``reset_config`` and
validation ranges.
"""

DEFAULT_CONFIG: dict = {
    "elo": {
        "initial_elo": 1200,
        "k_factor": 32,
        "divisor": 400,
        "quit_penalty_min": 5,
        "quit_penalty_max": 10,
        "hint_decay": [0.75, 0.50, 0.25],
        "k_newbie": 40,
        "k_veteran": 20,
        "k_newbie_threshold": 20,
        "k_veteran_threshold": 100,
    },
    "pp": {
        "base_formula_coefficient": 10,
        "base_formula_offset": 800,
        "decay_factor": 0.95,
        "max_problems": 100,
        "performance_factor_wa_penalty": 0.03,
        "performance_factor_time_penalty": 0.01,
        "performance_factor_time_min": 0.6,
        "overkill_threshold": 150,
        "overkill_tiers": [
            {"min_gap": 150, "max_gap": 249, "multiplier": 1.2},
            {"min_gap": 250, "max_gap": 349, "multiplier": 1.5},
            {"min_gap": 350, "max_gap": 9999, "multiplier": 2.0},
        ],
    },
    "challenge": {
        "weight_within_100": 0.50,
        "weight_challenge_zone": 0.25,
        "weight_consolidation_zone": 0.15,
        "weight_surprise_zone": 0.10,
    },
    "economy": {
        "daily_token_cap": 120,
        "time_bonus_threshold_minutes": 20,
        "difficulty_tiers": {
            "gray": {"min": 800, "max": 1099, "ac_reward": 10, "attempt_reward": 2},
            "green": {"min": 1100, "max": 1399, "ac_reward": 20, "attempt_reward": 3},
            "blue": {"min": 1400, "max": 1699, "ac_reward": 30, "attempt_reward": 4},
            "purple": {"min": 1700, "max": 1999, "ac_reward": 40, "attempt_reward": 5},
            "yellow_red": {"min": 2000, "max": 9999, "ac_reward": 50, "attempt_reward": 6},
        },
        "hint_pricing": {
            "gray": [3, 10, 20],
            "green": [5, 15, 30],
            "blue": [8, 20, 40],
            "purple": [10, 25, 50],
            "yellow_red": [15, 30, 60],
        },
    },
    "contest": {
        "tiers": {
            "beginner": {"max_elo": 1400, "duration_minutes": 90, "problems": 4, "rating_range": [800, 1400]},
            "advanced": {
                "min_elo": 1400,
                "max_elo": 1800,
                "duration_minutes": 120,
                "problems": 5,
                "rating_range": [1200, 2000],
            },
            "master": {"min_elo": 1800, "duration_minutes": 150, "problems": 6, "rating_range": [1600, 2600]},
        }
    },
    "cf_api": {
        "base_url": "https://codeforces.com/api",
        "request_interval_seconds": 2,
        "max_retries": 3,
        "cache_ttl_seconds": 300,
    },
    "melo": {
        "initial_elo_inherit_global": True,
        "training_global_coefficient": 0.5,
        "training_melo_coefficient": 2.0,
    },
}

# ---------------------------------------------------------------------------
# Validation rules – per-key constraints applied by ConfigService.set_config
# ---------------------------------------------------------------------------

# Mapping from dot-path to (expected_type, min_value, max_value).
# Only scalar leaf values that need range validation are listed here.
# Nested dict / list values are validated for type only.
VALIDATION_RULES: dict[str, dict] = {
    "elo.initial_elo": {"type": int, "min": 0, "max": 5000},
    "elo.k_factor": {"type": (int, float), "min": 1, "max": 100},
    "elo.divisor": {"type": (int, float), "min": 100, "max": 1000},
    "elo.quit_penalty_min": {"type": int, "min": 0, "max": 50},
    "elo.quit_penalty_max": {"type": int, "min": 0, "max": 50},
    "elo.k_newbie": {"type": (int, float), "min": 1, "max": 100},
    "elo.k_veteran": {"type": (int, float), "min": 1, "max": 100},
    "elo.k_newbie_threshold": {"type": int, "min": 1, "max": 1000},
    "elo.k_veteran_threshold": {"type": int, "min": 1, "max": 10000},
    "pp.base_formula_coefficient": {"type": (int, float), "min": 1, "max": 100},
    "pp.base_formula_offset": {"type": int, "min": 0, "max": 2000},
    "pp.decay_factor": {"type": (int, float), "min": 0.0, "max": 1.0},
    "pp.max_problems": {"type": int, "min": 1, "max": 10000},
    "pp.performance_factor_wa_penalty": {"type": (int, float), "min": 0.0, "max": 0.1},
    "pp.performance_factor_time_penalty": {"type": (int, float), "min": 0.0, "max": 0.1},
    "pp.performance_factor_time_min": {"type": (int, float), "min": 0.0, "max": 1.0},
    "challenge.weight_within_100": {"type": (int, float), "min": 0.0, "max": 1.0},
    "challenge.weight_challenge_zone": {"type": (int, float), "min": 0.0, "max": 1.0},
    "challenge.weight_consolidation_zone": {"type": (int, float), "min": 0.0, "max": 1.0},
    "challenge.weight_surprise_zone": {"type": (int, float), "min": 0.0, "max": 1.0},
    "economy.daily_token_cap": {"type": int, "min": 1, "max": 10000},
    "economy.time_bonus_threshold_minutes": {"type": int, "min": 1, "max": 1440},
    "cf_api.request_interval_seconds": {"type": (int, float), "min": 0.1, "max": 60},
    "cf_api.max_retries": {"type": int, "min": 0, "max": 20},
    "cf_api.cache_ttl_seconds": {"type": (int, float), "min": 0, "max": 86400},
    "melo.initial_elo_inherit_global": {"type": bool},
    "melo.training_global_coefficient": {"type": (int, float), "min": 0.0, "max": 10.0},
    "melo.training_melo_coefficient": {"type": (int, float), "min": 0.0, "max": 10.0},
}
