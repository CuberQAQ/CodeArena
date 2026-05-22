"""Schema consistency checks: validate _Test* models match production models.

This test module provides CI-level protection against schema drift between
production SQLAlchemy models and their lightweight SQLite-compatible test
counterparts.  When a developer adds a column to a production model but
forgets to update the test models, this test fails with a clear diff.

The MODEL_REGISTRY defines every _Test* model and its corresponding
production model.  The registry is the single source of truth for which
models must stay in sync.

If you add a new _Test* model to a test file, you MUST also add an entry
to MODEL_REGISTRY below.
"""

import importlib

import pytest

from app.models.cf_sample_user import CFSampleUser
from app.models.challenge_session import ChallengeSession
from app.models.check_in import CheckIn
from app.models.contest_bot import ContestBot
from app.models.contest_medal import ContestMedal
from app.models.contest_problem_record import ContestProblemRecord
from app.models.contest_session import ContestSession
from app.models.elo_history import EloHistory
from app.models.hint_purchase import HintPurchase
from app.models.pp_record import PPRecord
from app.models.problem_statement import ProblemStatement
from app.models.pve_challenge_session import PvEChallengeSession
from app.models.submission_tracking import SubmissionTracking
from app.models.system_config import SystemConfig
from app.models.token_transaction import TokenTransaction
from app.models.topic_category import TopicCategory
from app.models.training_problem_record import TrainingProblemRecord
from app.models.training_session import TrainingSession
from app.models.user import User
from app.models.user_settings import UserSettings
from app.models.user_tag_elo import UserTagElo
from tests.conftest import assert_models_synced

# ---------------------------------------------------------------------------
# Registry: (test_file_module, _TestClassName) -> ProductionModel
# ---------------------------------------------------------------------------
# Each entry maps a _Test* model defined in a specific test file to its
# corresponding production model.  When adding a new _Test* model, add it here.

MODEL_REGISTRY: list[tuple[str, str, type]] = [
    # --- _TestUser variants ---
    ("tests.test_auth", "_TestUser", User),
    ("tests.test_avatar", "_TestUser", User),
    ("tests.test_cf_handle_service", "_TestUser", User),
    ("tests.test_challenge", "_TestUser", User),
    ("tests.test_checkin", "_TestUser", User),
    ("tests.test_contest", "_TestUser", User),
    ("tests.test_contest_simulation", "_TestUser", User),
    ("tests.test_economy", "_TestUser", User),
    ("tests.test_elo_service", "_TestUser", User),
    ("tests.test_hints", "_TestUser", User),
    ("tests.test_k_factor", "_TestUser", User),
    ("tests.test_medal", "_TestUser", User),
    ("tests.test_melo_service", "_TestUser", User),
    ("tests.test_overkill_bonus", "_TestUser", User),
    ("tests.test_pp_rank", "_TestUser", User),
    ("tests.test_pp_service", "_TestUser", User),
    ("tests.test_pve_challenge", "_TestUser", User),
    ("tests.test_ranking_api", "_TestUser", User),
    ("tests.test_s_value", "_TestUser", User),
    ("tests.test_submission_tracker", "_TestUser", User),
    ("tests.test_task22_hint_attenuation", "_TestUser", User),
    ("tests.test_task28_3_time_factor_elo", "_TestUser", User),
    ("tests.test_task29_1_melo_all_modes", "_TestUser", User),
    ("tests.test_task_19", "_TestUser", User),
    ("tests.test_admin", "_TestUser", User),
    ("tests.test_training", "_TestUser", User),
    ("tests.test_training_shield_polarization", "_TestUser", User),
    # --- _TestChallengeSession variants ---
    ("tests.test_challenge", "_TestChallengeSession", ChallengeSession),
    ("tests.test_task_19", "_TestChallengeSession", ChallengeSession),
    ("tests.test_admin", "_TestChallengeSession", ChallengeSession),
    # --- _TestTokenTransaction variants ---
    ("tests.test_challenge", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_checkin", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_contest", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_contest_simulation", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_economy", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_hints", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_pve_challenge", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_task22_hint_attenuation", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_task28_3_time_factor_elo", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_task_19", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_training", "_TestTokenTransaction", TokenTransaction),
    ("tests.test_training_shield_polarization", "_TestTokenTransaction", TokenTransaction),
    # --- _TestEloHistory variants ---
    ("tests.test_contest", "_TestEloHistory", EloHistory),
    ("tests.test_contest_simulation", "_TestEloHistory", EloHistory),
    ("tests.test_elo_service", "_TestEloHistory", EloHistory),
    ("tests.test_k_factor", "_TestEloHistory", EloHistory),
    ("tests.test_pve_challenge", "_TestEloHistory", EloHistory),
    ("tests.test_s_value", "_TestEloHistory", EloHistory),
    ("tests.test_task22_hint_attenuation", "_TestEloHistory", EloHistory),
    ("tests.test_task28_3_time_factor_elo", "_TestEloHistory", EloHistory),
    ("tests.test_task_19", "_TestEloHistory", EloHistory),
    ("tests.test_training", "_TestEloHistory", EloHistory),
    ("tests.test_training_shield_polarization", "_TestEloHistory", EloHistory),
    # --- _TestPPRecord variants ---
    ("tests.test_contest", "_TestPPRecord", PPRecord),
    ("tests.test_contest_simulation", "_TestPPRecord", PPRecord),
    ("tests.test_k_factor", "_TestPPRecord", PPRecord),
    ("tests.test_overkill_bonus", "_TestPPRecord", PPRecord),
    ("tests.test_pp_service", "_TestPPRecord", PPRecord),
    ("tests.test_pve_challenge", "_TestPPRecord", PPRecord),
    ("tests.test_s_value", "_TestPPRecord", PPRecord),
    ("tests.test_task22_hint_attenuation", "_TestPPRecord", PPRecord),
    ("tests.test_task28_3_time_factor_elo", "_TestPPRecord", PPRecord),
    # --- _TestContestSession variants ---
    ("tests.test_contest", "_TestContestSession", ContestSession),
    ("tests.test_contest_simulation", "_TestContestSession", ContestSession),
    ("tests.test_task22_hint_attenuation", "_TestContestSession", ContestSession),
    ("tests.test_task28_3_time_factor_elo", "_TestContestSession", ContestSession),
    ("tests.test_task_19", "_TestContestSession", ContestSession),
    ("tests.test_admin", "_TestContestSession", ContestSession),
    # --- _TestContestProblemRecord variants ---
    ("tests.test_contest", "_TestContestProblemRecord", ContestProblemRecord),
    ("tests.test_task22_hint_attenuation", "_TestContestProblemRecord", ContestProblemRecord),
    ("tests.test_task28_3_time_factor_elo", "_TestContestProblemRecord", ContestProblemRecord),
    ("tests.test_task_19", "_TestContestProblemRecord", ContestProblemRecord),
    # --- _TestUserTagElo variants ---
    ("tests.test_medal", "_TestUserTagElo", UserTagElo),
    ("tests.test_melo_service", "_TestUserTagElo", UserTagElo),
    ("tests.test_task22_hint_attenuation", "_TestUserTagElo", UserTagElo),
    ("tests.test_task28_3_time_factor_elo", "_TestUserTagElo", UserTagElo),
    ("tests.test_task29_1_melo_all_modes", "_TestUserTagElo", UserTagElo),
    ("tests.test_training", "_TestUserTagElo", UserTagElo),
    ("tests.test_training_shield_polarization", "_TestUserTagElo", UserTagElo),
    # --- _TestTopicCategory variants ---
    ("tests.test_task22_hint_attenuation", "_TestTopicCategory", TopicCategory),
    ("tests.test_task28_3_time_factor_elo", "_TestTopicCategory", TopicCategory),
    ("tests.test_training", "_TestTopicCategory", TopicCategory),
    ("tests.test_training_shield_polarization", "_TestTopicCategory", TopicCategory),
    # --- _TestTrainingSession variants ---
    ("tests.test_task22_hint_attenuation", "_TestTrainingSession", TrainingSession),
    ("tests.test_task28_3_time_factor_elo", "_TestTrainingSession", TrainingSession),
    ("tests.test_training", "_TestTrainingSession", TrainingSession),
    ("tests.test_training_shield_polarization", "_TestTrainingSession", TrainingSession),
    ("tests.test_admin", "_TestTrainingSession", TrainingSession),
    # --- _TestTrainingProblemRecord variants ---
    ("tests.test_task22_hint_attenuation", "_TestTrainingProblemRecord", TrainingProblemRecord),
    ("tests.test_task28_3_time_factor_elo", "_TestTrainingProblemRecord", TrainingProblemRecord),
    ("tests.test_training", "_TestTrainingProblemRecord", TrainingProblemRecord),
    ("tests.test_training_shield_polarization", "_TestTrainingProblemRecord", TrainingProblemRecord),
    # --- _TestPvESession variants ---
    ("tests.test_pve_challenge", "_TestPvESession", PvEChallengeSession),
    ("tests.test_task22_hint_attenuation", "_TestPvESession", PvEChallengeSession),
    ("tests.test_task28_3_time_factor_elo", "_TestPvESession", PvEChallengeSession),
    # --- _TestContestBot ---
    ("tests.test_contest_simulation", "_TestContestBot", ContestBot),
    # --- _TestContestMedal ---
    ("tests.test_medal", "_TestContestMedal", ContestMedal),
    # --- _TestUserSettings ---
    ("tests.test_avatar", "_TestUserSettings", UserSettings),
    ("tests.test_medal", "_TestUserSettings", UserSettings),
    # --- _TestSystemConfig ---
    ("tests.test_config_service", "_TestSystemConfig", SystemConfig),
    # --- _TestHintPurchase ---
    ("tests.test_hints", "_TestHintPurchase", HintPurchase),
    # --- _TestCheckIn ---
    ("tests.test_checkin", "_TestCheckIn", CheckIn),
    # --- _TestSubmissionTracking ---
    ("tests.test_submission_tracker", "_TestSubmissionTracking", SubmissionTracking),
    # --- _TestProblemStatement ---
    ("tests.test_problem_scraper", "_TestProblemStatement", ProblemStatement),
    # --- _TestCFSampleUser ---
    ("tests.test_cf_ranking_service", "_TestCFSampleUser", CFSampleUser),
    ("tests.test_ranking_api", "_TestCFSampleUser", CFSampleUser),
]


def _load_test_class(module_path: str, class_name: str) -> type:
    """Dynamically load a _Test* class from a test module.

    Uses importlib to avoid name collisions (each test file defines its own
    _Test* classes with identical names but potentially different schemas).
    """
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


# ---------------------------------------------------------------------------
# Parametrized test: validate every registered _Test* model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path,test_class_name,prod_model",
    MODEL_REGISTRY,
    ids=[f"{m}.{c}" for m, c, _ in MODEL_REGISTRY],
)
def test_model_schema_sync(module_path: str, test_class_name: str, prod_model: type):
    """Verify _Test* model columns exactly match the production model columns.

    If this test fails, it means either:
    - A production model gained a new column that the _Test* model doesn't have
      (add the missing column to the _Test* model in the test file)
    - A _Test* model has a stale column that no longer exists in production
      (remove the stale column from the _Test* model in the test file)
    """
    test_model = _load_test_class(module_path, test_class_name)
    assert_models_synced(
        test_model,
        prod_model,
        test_model_label=f"{module_path}::{test_class_name}",
        prod_model_label=prod_model.__name__,
    )


def test_registry_covers_all_unique_test_models():
    """Ensure the MODEL_REGISTRY covers all unique _Test* model classes.

    This is a meta-test that scans test files for _Test* classes and ensures
    they are all registered.  If you see this fail, add the missing entries
    to MODEL_REGISTRY above.
    """
    import ast
    import os

    tests_dir = os.path.dirname(__file__)
    registered_keys = {(m, c) for m, c, _ in MODEL_REGISTRY}

    missing: list[str] = []
    for fname in sorted(os.listdir(tests_dir)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        fpath = os.path.join(tests_dir, fname)
        with open(fpath) as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        module_path = f"tests.{fname[:-3]}"
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("_Test") or node.name == "_TestBase":
                continue
            key = (module_path, node.name)
            if key not in registered_keys:
                missing.append(f"{module_path}::{node.name}")

    assert not missing, (
        "Found _Test* models not in MODEL_REGISTRY:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\nPlease add them to MODEL_REGISTRY in test_schema_sync.py"
    )
