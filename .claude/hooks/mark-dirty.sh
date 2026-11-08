#!/usr/bin/env bash
# PostToolUse: 이번 턴에 파일을 바꿀 수 있는 도구가 실행됐다는 표시(.claude/state/dirty)만 남긴다.
# - Stop 훅은 응답이 끝날 때마다 실행되므로, 실제로 수정이 있었던 턴에만 게이트를 돌리기 위한 표시다.
# - 아무것도 출력하지 않고 항상 exit 0 (실패해도 작업을 방해하지 않는다).
# - format/lint 자동 수정은 넣지 않는다: 파일 내용이 바뀌면 Claude의 다음 Edit이 실패하고
#   파일을 다시 읽느라 토큰이 늘어난다.
trap 'exit 0' ERR
INPUT=$(cat 2>/dev/null || true)
if command -v jq >/dev/null 2>&1; then
  TOOL=$(jq -r '.tool_name // ""' <<<"$INPUT" 2>/dev/null || true)
  # 읽기 전용 도구는 matcher에서 이미 제외되어 있다. 혹시 들어오면 표시하지 않는다.
  if [ "$TOOL" = "Read" ]; then exit 0; fi
fi
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
mkdir -p "$ROOT/.claude/state" 2>/dev/null && : >"$ROOT/.claude/state/dirty" 2>/dev/null
exit 0
