#!/usr/bin/env bash
# 하네스 스크립트 공통 함수. source로 불러 쓴다 (보호 경로).

# find_sys_python: venv가 아닌 시스템 Python(3.11 이상)을 찾아 SYSPY 배열에 `-I -S`와 함께 넣는다.
#   -I: 환경 변수(PYTHONPATH 등), 사용자 site-packages, 현재 폴더를 무시
#   -S: site 모듈을 불러오지 않음 → *.pth, sitecustomize, usercustomize가 실행되지 않음
# protected.py와 metrics.py는 표준 라이브러리만 쓰므로 이 방식으로 실행한다.
# 못 찾으면 1을 반환한다. 호출한 쪽이 실패 처리를 결정한다 (guard는 차단, gate는 오류 코드 3).
find_sys_python() {
  local candidate out
  local -a cmd
  for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if [ "$candidate" = py ]; then cmd=(py -3); else cmd=("$candidate"); fi
    out=$("${cmd[@]}" -I -S -c \
      'import sys; print("ok" if sys.version_info >= (3, 11) and sys.prefix == sys.base_prefix else "no")' \
      2>/dev/null | tr -d '\r') || continue
    if [ "$out" = "ok" ]; then
      SYSPY=("${cmd[@]}" -I -S)
      return 0
    fi
  done
  return 1
}
