"""Protocol seed derivation (documented in protocol/preregistration.md)."""

PROTOCOL_SEED = 20260822
CATALOG_SEED = 20260822  # world/rule catalog generation
DEV_SPLIT_SEED = 20260823  # development corpus (exploratory)
SHIFT_CANDIDATE_SEED = 20260824  # confirmatory candidate generation/order
SELECTION_ORDER_SEED = 20260824  # selection permutation
BOOTSTRAP_SEed = 20260825  # noqa: N816 - bootstrap resampling (fixed)


def bootstrap_seed() -> int:
    return 20260825
