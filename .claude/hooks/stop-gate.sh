#!/usr/bin/env bash
# Stop: 이번 턴에 수정이 있었으면 quality_gate.sh --fast를 돌린다 (fail-open, 재시도 상한 3).
#
# - 이 스크립트나 게이트 자체에 오류가 나면 통과시킨다 (trap ERR → exit 0, 게이트 종료 코드 3).
#   고장 난 게이트 때문에 같은 실패가 무한히 반복되지 않게 하기 위해서다.
# - 실패하면 재시도 카운터를 올리고 exit 2 (stderr가 Claude에게 전달되어 작업을 이어 간다).
# - 카운터가 3에 도달한 다음 호출에서는 카운터를 지우고 exit 0으로 종료를 허용한다 (2, 2, 2, 0).
#   dirty 표시는 남겨 두므로 다음 턴에 다시 검사한다.
# - stop_hook_active는 쓰지 않는다: 재시도 횟수를 정확히 세려면 직접 센 카운터가 필요하다.
trap 'echo "stop-gate 내부 오류, 게이트 건너뜀" >&2; exit 0' ERR
set -Eeuo pipefail

INPUT=$(cat 2>/dev/null || true)
if command -v jq >/dev/null 2>&1; then
  jq -e . >/dev/null 2>&1 <<<"$INPUT" || true # 입력 형식 확인만 (내용은 쓰지 않음)
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"
STATE=.claude/state
DIRTY="$STATE/dirty"
RETRIES="$STATE/retries"
MAX=3

if [ ! -f "$DIRTY" ]; then exit 0; fi

retries=$(tr -dc '0-9' <"$RETRIES" 2>/dev/null || true)
retries=${retries:-0}
if [ "$retries" -ge "$MAX" ]; then
  rm -f "$RETRIES"
  echo "게이트 실패 상태로 종료함. 사용자에게 실패 내용을 반드시 보고할 것" >&2
  # 사용자 화면에도 경고를 띄운다 (Stop에서 표시되는지는 공식 문서로 확인하지 못함)
  printf '{"systemMessage": "%s"}\n' "품질 게이트가 ${MAX}회 연속 실패한 상태로 종료했습니다. 자세한 내용: .claude/state/gate.log"
  exit 0
fi

rc=0
bash .claude/scripts/quality_gate.sh --fast >/dev/null 2>&1 || rc=$?

if [ "$rc" -eq 0 ]; then
  rm -f "$DIRTY" "$RETRIES"
  exit 0
fi
if [ "$rc" -ne 1 ]; then
  echo "품질 게이트 자체 오류(종료 코드 $rc)로 이번 검사를 건너뜀. .claude/state/gate.log 참고" >&2
  exit 0
fi

retries=$((retries + 1))
echo "$retries" >"$RETRIES"
{
  echo "품질 게이트 실패 ($retries/$MAX). 원인을 고친 뒤 다시 마치세요. 보호 경로는 직접 고치지 말 것."
  tail -n 30 "$STATE/gate.log"
} >&2
exit 2
