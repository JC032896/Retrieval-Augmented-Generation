#!/usr/bin/env bash
# [사용자 전용] 보호 경로 수정을 일정 시간(기본 15분) 허용한다.
# 사용: ! bash .claude/scripts/unlock.sh
# Claude가 이 스크립트를 실행하는 것은 guard.sh가 차단한다.
# 만료 시각(epoch 초)을 .claude/state/unlock에 기록하고, guard.sh가 매번 이 시각을 확인한다.
set -euo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
mkdir -p "$ROOT/.claude/state"
minutes="${UNLOCK_MINUTES:-15}"
expires=$(( $(date +%s) + minutes * 60 ))
echo "$expires" >"$ROOT/.claude/state/unlock"
echo "보호 경로 잠금 해제: $(date -d "@$expires" '+%H:%M:%S')까지 (${minutes}분)."
echo "수정이 끝나면 확인: ! bash .claude/scripts/approve.sh  → 승인: ! bash .claude/scripts/approve.sh --yes"
