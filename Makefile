.PHONY: setup lint typecheck test v2-test artifacts public-surface package verify

setup:
	uv sync --locked --all-groups

lint:
	.venv/bin/ruff check src development examples scripts tests
	.venv/bin/ruff format --check src development examples scripts tests

typecheck:
	.venv/bin/mypy

test:
	.venv/bin/pytest tests -q

v2-test:
	.venv/bin/python -m development.measurement_v2 validate --out artifacts/verification/v2-construction.json
	.venv/bin/python -m pytest development/measurement_v2/tests -q

artifacts:
	.venv/bin/python scripts/check_artifacts.py
	.venv/bin/python scripts/recompute_results.py
	.venv/bin/python scripts/replay_study.py
	.venv/bin/python scripts/audit_visibility.py

public-surface:
	.venv/bin/python scripts/check_public_surface.py

package:
	@set -eu; \
	out="$$(mktemp -d "$${TMPDIR:-/tmp}/cascadeshift-package.XXXXXX")"; \
	wheel_venv="$$(mktemp -d "$${TMPDIR:-/tmp}/cascadeshift-wheel.XXXXXX")"; \
	sdist_venv="$$(mktemp -d "$${TMPDIR:-/tmp}/cascadeshift-sdist.XXXXXX")"; \
	trap 'rm -rf "$$out" "$$wheel_venv" "$$sdist_venv"' EXIT; \
	.venv/bin/python -m hatchling build -t wheel -t sdist -d "$$out"; \
	test "$$(find "$$out" -maxdepth 1 -name '*.whl' -type f | wc -l | tr -d ' ')" = 1; \
	test "$$(find "$$out" -maxdepth 1 -name '*.tar.gz' -type f | wc -l | tr -d ' ')" = 1; \
	uv venv --offline --python .venv/bin/python "$$wheel_venv"; \
	UV_PROJECT_ENVIRONMENT="$$wheel_venv" uv sync --locked --offline --no-dev --group build --no-install-project; \
	uv pip install --offline --no-deps --python "$$wheel_venv/bin/python" "$$out"/*.whl; \
	cd "$$wheel_venv"; \
	"$$wheel_venv/bin/python" -c 'import cascadeshift; assert cascadeshift.__version__ == "1.3.0"'; \
	"$$wheel_venv/bin/cascadeshift" doctor --json >/dev/null; \
	"$$wheel_venv/bin/cascadeshift" world validate >/dev/null; \
	cd - >/dev/null; \
	uv venv --offline --python .venv/bin/python "$$sdist_venv"; \
	UV_PROJECT_ENVIRONMENT="$$sdist_venv" uv sync --locked --offline --no-dev --group build --no-install-project; \
	uv pip install --offline --no-deps --no-build-isolation --python "$$sdist_venv/bin/python" "$$out"/*.tar.gz; \
	cd "$$sdist_venv"; \
	"$$sdist_venv/bin/python" -c 'import cascadeshift; assert cascadeshift.__version__ == "1.3.0"'; \
	"$$sdist_venv/bin/cascadeshift" doctor --json >/dev/null; \
	"$$sdist_venv/bin/cascadeshift" world validate >/dev/null

verify: lint typecheck test v2-test artifacts public-surface package
	@echo "VERIFY OK: offline scientific and prototype checks passed"
