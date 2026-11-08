# 프로젝트 안내

- 스택: Python 3.12, FastAPI, uv, pytest, ruff, mypy. 설계와 로드맵은 README.MD, 차별화 리서치는 RESEARCH.md
- 구조: `src/rag_service/` 코드, `tests/` 테스트, `eval/` 평가, `.claude/` 하네스 (자세한 내용: `.claude/HARNESS.md`)
- 명령: `uv run pytest -q`, `uv run ruff format .`, `uv run ruff check .`, `uv run mypy`
- 품질 게이트: 작업 중 `bash .claude/scripts/quality_gate.sh --fast`, 마무리 `--full` (커버리지, eval, baseline 비교)
- 응답을 마칠 때 Stop 훅이 `--fast`를 자동으로 돌린다. 실패하면 원인을 고친 뒤 다시 마친다 (최대 3번)

## 규칙

- 보호 경로(기존 테스트, conftest와 pytest/ruff/mypy/coverage 설정, eval 정답·baseline·채점 코드, .gitignore, 하네스 파일)를
  고쳐야 하면 직접 고치지 말고 이유를 설명한 뒤 사용자 승인을 받는다.
- 게이트가 실패한 채로 종료됐다면 숨기지 말고, 무엇이 실패했는지 사용자에게 보고한다.
- 새 테스트는 추가해도 된다. 공용 fixture는 `tests/fixtures/` 모듈에 두고 테스트 파일에서 명시적으로 import한다 (conftest.py 금지).
- `type: ignore`, `noqa`, `pragma: no cover`, skip으로 검사를 덮지 말고 원인을 고친다.
- `unlock.sh`, `approve.sh`, `make_baseline.sh` 실행과 `git add`/`git commit`은 사용자만 한다.
