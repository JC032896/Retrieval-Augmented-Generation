#!/usr/bin/env bash
# [사용자 전용] --full 지표로 eval/baseline.json을 만들거나 갱신한다.
# 사용: ! bash .claude/scripts/make_baseline.sh
# 언제: 첫 baseline 생성, golden set 변경 후, 의도적으로 기준을 바꿀 때 (모두 사용자 승인 필요)
# 하는 일:
#   1) quality_gate.sh --full --no-compare 실행 (실패하면 중단: 깨진 상태를 기준으로 삼지 않음)
#   2) eval이 있으면 한 번 더 실행해서 두 결과가 같은지 확인 (결정성 확인 → 허용 오차 0)
#   3) eval/baseline.json 저장 후 approve.sh --yes로 보호 기준 갱신과 커밋
#      (approve가 중단되면 baseline.json을 이전 내용으로 되돌린다)
# Claude가 이 스크립트를 실행하는 것은 guard.sh가 차단한다.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8  # Windows에서 한글 출력이 cp949로 깨지지 않게
set -euo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# eval은 프로젝트 의존성이 필요하므로 venv(uv run)로, 지표 계산은 시스템 Python -I -S로 실행한다
PY=(uv run --frozen --quiet python)
# shellcheck source=.claude/scripts/_common.sh
. .claude/scripts/_common.sh
find_sys_python || { echo "시스템 Python 3.11 이상을 찾을 수 없습니다." >&2; exit 1; }
METRICS=("${SYSPY[@]}" .claude/scripts/metrics.py)
STATE=.claude/state

if ! bash .claude/scripts/quality_gate.sh --full --no-compare; then
  echo "게이트가 실패해서 baseline을 만들지 않았습니다."
  exit 1
fi

repeat=()
if [ -f "$STATE/eval.json" ] && [ -f eval/run_eval.py ]; then
  echo "== 결정성 확인을 위해 eval 한 번 더 실행"
  "${PY[@]}" eval/run_eval.py --json "$STATE/eval_repeat.json"
  repeat=(--eval-repeat "$STATE/eval_repeat.json")
fi

mkdir -p eval
BASELINE=eval/baseline.json
backup=""
if [ -f "$BASELINE" ]; then
  backup=$(mktemp)
  cp "$BASELINE" "$backup"
fi
restore_baseline() {
  if [ -n "$backup" ]; then mv "$backup" "$BASELINE"; else rm -f "$BASELINE"; fi
  echo "approve가 중단되어 $BASELINE 을 이전 상태로 되돌렸습니다." >&2
}

"${METRICS[@]}" baseline --metrics "$STATE/metrics.json" "${repeat[@]}" \
  --out "$BASELINE"
if ! bash .claude/scripts/approve.sh --yes; then
  restore_baseline
  exit 1
fi
[ -n "$backup" ] && rm -f "$backup"
exit 0
