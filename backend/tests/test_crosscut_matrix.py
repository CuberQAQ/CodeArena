"""Cross-cutting feature matrix test (Task 43.7).

Uses AST analysis to verify that all four game modes consistently call
the expected cross-cutting service functions (Elo, PP, Token, Achievement)
in their settlement flows.  Generates a readable matrix report and asserts
all expected intersections are covered.

Run:  pytest tests/test_crosscut_matrix.py -v
"""

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVICES_DIR = BACKEND_DIR / "app" / "services"

SERVICE_FILES = {
    "challenge": SERVICES_DIR / "challenge_service.py",
    "pve": SERVICES_DIR / "pve_challenge_service.py",
    "training": SERVICES_DIR / "training_service.py",
    "contest": SERVICES_DIR / "contest_service.py",
}

# ---------------------------------------------------------------------------
# Expected matrix
# ---------------------------------------------------------------------------
# True  = the mode MUST call the cross-cutting feature in its settlement flow.
# False = intentionally absent (documented reason below).
#
# Contest PP:  Contest records PP per-problem in submit_problem(), not in the
#              PR-based settlement (_settle_with_pr).  Since PP *is* recorded
#              during the contest flow, we mark it True.
# Contest Achievement: check_contest_win + overkill + personal-best PP are all
#              called in end_contest / _settle_with_pr, so True.
# ---------------------------------------------------------------------------

EXPECTED_MATRIX: dict[str, dict[str, bool]] = {
    "challenge": {"elo": True, "pp": True, "token": True, "achievement": True},
    "pve": {"elo": True, "pp": True, "token": True, "achievement": True},
    "training": {"elo": True, "pp": True, "token": True, "achievement": True},
    "contest": {"elo": True, "pp": True, "token": True, "achievement": True},
}

# ---------------------------------------------------------------------------
# Settlement function names per mode
# ---------------------------------------------------------------------------

SETTLEMENT_FUNCTIONS: dict[str, list[str]] = {
    "challenge": ["_settle_challenge", "submit_result", "quit_challenge"],
    "pve": ["submit_result", "quit_challenge"],
    "training": ["submit_problem", "abandon_training"],
    "contest": ["submit_problem", "end_contest", "_settle_with_pr", "_auto_end_expired"],
}

# ---------------------------------------------------------------------------
# Service call patterns to detect
# ---------------------------------------------------------------------------

# Each entry: (human_name, set of patterns to look for in AST Call nodes)
# We detect by looking at ast.Attribute.attr names when the value is a known
# service name, OR by matching function names directly.

ELO_PATTERNS = {
    # Direct EloService calls
    "EloService",
    # Also detect direct EloHistory creation (contest mode creates history directly)
    "EloHistory",
}

PP_PATTERNS = {
    "PPService",
}

TOKEN_PATTERNS = {
    # economy_svc is imported as `from app.services import economy_service as economy_svc`
    # Calls look like `economy_svc.award_tokens(...)` or `economy_svc.tokens_for_rating(...)`
    "economy_svc",
    "economy_service",
}

ACHIEVEMENT_PATTERNS = {
    "AchievementService",
}

FEATURE_DETECTORS: dict[str, set[str]] = {
    "elo": ELO_PATTERNS,
    "pp": PP_PATTERNS,
    "token": TOKEN_PATTERNS,
    "achievement": ACHIEVEMENT_PATTERNS,
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse_file(path: Path) -> ast.Module:
    """Parse a Python file into an AST."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    """Find all top-level and class-level function defs (including nested in classes)."""
    funcs: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs[node.name] = node

    return funcs


def _extract_call_targets(func_node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    """Extract all call targets from a function body.

    Returns a set of strings like "EloService.calculate_s_value",
    "economy_svc.award_tokens", "EloHistory", "PPService.record_pp", etc.
    """
    targets: set[str] = set()

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        # Case 1: attribute call -- e.g. EloService.calculate_s_value(...)
        if isinstance(func, ast.Attribute):
            attr_name = func.attr
            # Get the value side (could be Name, Attribute, etc.)
            if isinstance(func.value, ast.Name):
                obj_name = func.value.id
                targets.add(f"{obj_name}.{attr_name}")
                targets.add(obj_name)  # Also record just the service name
            elif isinstance(func.value, ast.Attribute):
                # Nested attribute -- unlikely but handle
                targets.add(attr_name)
            else:
                targets.add(attr_name)

        # Case 2: direct name call -- e.g. award_tokens(...)
        elif isinstance(func, ast.Name):
            targets.add(func.id)

    return targets


def _detect_features_in_calls(
    call_targets: set[str],
    feature_name: str,
) -> bool:
    """Check whether any call target matches the given feature's patterns."""
    patterns = FEATURE_DETECTORS[feature_name]
    for target in call_targets:
        for pattern in patterns:
            if target == pattern or target.startswith(pattern + "."):
                return True
    return False


def _detect_features_for_mode(
    mode: str,
    tree: ast.Module,
) -> dict[str, bool]:
    """Detect which cross-cutting features are present in a mode's settlement functions."""
    all_funcs = _find_functions(tree)
    settlement_names = SETTLEMENT_FUNCTIONS.get(mode, [])

    # Collect call targets across all settlement functions
    combined_targets: set[str] = set()
    found_any = False
    for name in settlement_names:
        func_node = all_funcs.get(name)
        if func_node is not None:
            combined_targets |= _extract_call_targets(func_node)
            found_any = True

    if not found_any:
        # Could not find any settlement functions -- return all False
        return {feat: False for feat in FEATURE_DETECTORS}

    return {feat: _detect_features_in_calls(combined_targets, feat) for feat in FEATURE_DETECTORS}


# ---------------------------------------------------------------------------
# Text-based fallback (grep) for cases AST misses dynamic imports / aliasing
# ---------------------------------------------------------------------------


def _grep_detect_features(mode: str, file_path: Path) -> dict[str, bool]:
    """Fallback detection using text search (grep)."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {feat: False for feat in FEATURE_DETECTORS}

    # Only look within settlement function regions
    settlement_names = SETTLEMENT_FUNCTIONS.get(mode, [])

    # Extract text of settlement functions via simple string search
    settlement_text = ""
    lines = source.split("\n")
    for fname in settlement_names:
        for i, line in enumerate(lines):
            # Match function definition (async def or def)
            stripped = line.strip()
            if stripped.startswith("async def " + fname) or stripped.startswith("def " + fname):
                # Collect the function body (approximate: until next def at same or lower indent)
                base_indent = len(line) - len(line.lstrip())
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if next_line.strip() == "":
                        j += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    # Stop at next function/class def at same indent level
                    if next_indent <= base_indent and (
                        next_line.strip().startswith("async def ")
                        or next_line.strip().startswith("def ")
                        or next_line.strip().startswith("class ")
                    ):
                        break
                    j += 1
                settlement_text += "\n".join(lines[i:j]) + "\n"
                break

    if not settlement_text:
        # Fallback to full file if no settlement function found
        settlement_text = source

    result: dict[str, bool] = {}
    for feat, patterns in FEATURE_DETECTORS.items():
        found = False
        for pattern in patterns:
            if pattern in settlement_text:
                found = True
                break
        result[feat] = found

    return result


# ---------------------------------------------------------------------------
# Matrix report builder
# ---------------------------------------------------------------------------


def _build_matrix_report(
    actual: dict[str, dict[str, bool]],
    expected: dict[str, dict[str, bool]],
) -> str:
    """Build a readable text matrix report."""
    modes = list(expected.keys())
    features = list(next(iter(expected.values())).keys())

    # Column widths
    mode_w = max(len(m) for m in modes) + 2
    feat_w = max(len(f) for f in features) + 2

    header = " " * mode_w + "".join(f.center(feat_w) for f in features)
    sep = "-" * mode_w + "".join("-" * feat_w for _ in features)

    lines = [
        "=" * len(header),
        "CROSS-CUTTING FEATURE MATRIX",
        "=" * len(header),
        "",
        header,
        sep,
    ]

    for mode in modes:
        row = mode.ljust(mode_w)
        for feat in features:
            act = actual.get(mode, {}).get(feat, False)
            exp = expected.get(mode, {}).get(feat, False)
            if act and exp:
                cell = "OK"
            elif not act and not exp:
                cell = "--"
            elif act and not exp:
                cell = "??"
            else:
                cell = "MISS"
            row += cell.center(feat_w)
        lines.append(row)

    lines.append(sep)
    lines.append("")
    lines.append("Legend:  OK = present and expected  |  -- = absent and not expected")
    lines.append("        MISS = absent but expected  |  ?? = present but not expected")
    lines.append("")

    # Detail failures
    failures = []
    for mode in modes:
        for feat in features:
            act = actual.get(mode, {}).get(feat, False)
            exp = expected.get(mode, {}).get(feat, False)
            if exp and not act:
                failures.append(f"  MISS: {mode}.{feat} -- expected but not detected")
            if not exp and act:
                failures.append(f"  ???: {mode}.{feat} -- detected but not expected")

    if failures:
        lines.append("Details:")
        lines.extend(failures)
    else:
        lines.append("All checks passed.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrossCutMatrix:
    """Cross-cutting feature consistency matrix across all game modes."""

    @pytest.fixture(autouse=True)
    def _compute_matrix(self):
        """Compute the actual matrix once for all tests in this class."""
        self.actual: dict[str, dict[str, bool]] = {}
        self.trees: dict[str, ast.Module] = {}

        for mode, path in SERVICE_FILES.items():
            if not path.exists():
                self.actual[mode] = {feat: False for feat in FEATURE_DETECTORS}
                continue
            tree = _parse_file(path)
            self.trees[mode] = tree
            # Use AST detection, supplement with grep fallback
            ast_result = _detect_features_for_mode(mode, tree)
            grep_result = _grep_detect_features(mode, path)

            # Merge: AST OR grep (if either detects, count as present)
            merged: dict[str, bool] = {}
            for feat in FEATURE_DETECTORS:
                merged[feat] = ast_result.get(feat, False) or grep_result.get(feat, False)
            self.actual[mode] = merged

        # Print report for visibility
        report = _build_matrix_report(self.actual, EXPECTED_MATRIX)
        print("\n" + report)

    def test_all_service_files_exist(self):
        """All four game mode service files must exist."""
        for mode, path in SERVICE_FILES.items():
            assert path.exists(), f"Service file not found: {path} (mode={mode})"

    def test_challenge_elo(self):
        """PvP challenge must call EloService in settlement."""
        assert self.actual["challenge"]["elo"], "PvP challenge settlement missing EloService calls"

    def test_challenge_pp(self):
        """PvP challenge must call PPService in settlement."""
        assert self.actual["challenge"]["pp"], "PvP challenge settlement missing PPService calls"

    def test_challenge_token(self):
        """PvP challenge must call economy_service in settlement."""
        assert self.actual["challenge"]["token"], "PvP challenge settlement missing economy_service.award_tokens calls"

    def test_challenge_achievement(self):
        """PvP challenge must call AchievementService in settlement."""
        assert self.actual["challenge"]["achievement"], "PvP challenge settlement missing AchievementService calls"

    def test_pve_elo(self):
        """PvE challenge must call EloService in settlement."""
        assert self.actual["pve"]["elo"], "PvE challenge settlement missing EloService calls"

    def test_pve_pp(self):
        """PvE challenge must call PPService in settlement."""
        assert self.actual["pve"]["pp"], "PvE challenge settlement missing PPService calls"

    def test_pve_token(self):
        """PvE challenge must call economy_service in settlement."""
        assert self.actual["pve"]["token"], "PvE challenge settlement missing economy_service.award_tokens calls"

    def test_pve_achievement(self):
        """PvE challenge must call AchievementService in settlement."""
        assert self.actual["pve"]["achievement"], "PvE challenge settlement missing AchievementService calls"

    def test_training_elo(self):
        """Training must call EloService in settlement."""
        assert self.actual["training"]["elo"], "Training settlement missing EloService calls"

    def test_training_pp(self):
        """Training must call PPService in settlement."""
        assert self.actual["training"]["pp"], "Training settlement missing PPService calls"

    def test_training_token(self):
        """Training must call economy_service in settlement."""
        assert self.actual["training"]["token"], "Training settlement missing economy_service.award_tokens calls"

    def test_training_achievement(self):
        """Training must call AchievementService in settlement."""
        assert self.actual["training"]["achievement"], "Training settlement missing AchievementService calls"

    def test_contest_elo(self):
        """Contest must call EloService in settlement."""
        assert self.actual["contest"]["elo"], "Contest settlement missing EloService calls"

    def test_contest_pp(self):
        """Contest must call PPService in settlement (per-problem in submit_problem)."""
        assert self.actual["contest"]["pp"], "Contest settlement missing PPService calls"

    def test_contest_token(self):
        """Contest must call economy_service in settlement."""
        assert self.actual["contest"]["token"], "Contest settlement missing economy_service.award_tokens calls"

    def test_contest_achievement(self):
        """Contest must call AchievementService in settlement."""
        assert self.actual["contest"]["achievement"], "Contest settlement missing AchievementService calls"

    def test_full_matrix_matches_expected(self):
        """Full matrix must match the expected matrix."""
        mismatches = []
        for mode in EXPECTED_MATRIX:
            for feat in EXPECTED_MATRIX[mode]:
                expected = EXPECTED_MATRIX[mode][feat]
                actual = self.actual.get(mode, {}).get(feat, False)
                if expected != actual:
                    mismatches.append(f"{mode}.{feat}: expected={expected}, actual={actual}")

        assert not mismatches, "Cross-cutting feature matrix mismatches:\n" + "\n".join(f"  {m}" for m in mismatches)

    def test_settlement_functions_exist(self):
        """All expected settlement function names must exist in the service files."""
        missing = []
        for mode, path in SERVICE_FILES.items():
            if not path.exists():
                continue
            tree = _parse_file(path)
            all_funcs = _find_functions(tree)
            for fname in SETTLEMENT_FUNCTIONS.get(mode, []):
                if fname not in all_funcs:
                    missing.append(f"{mode}: function '{fname}' not found in {path.name}")

        assert not missing, "Missing settlement functions:\n" + "\n".join(f"  {m}" for m in missing)
