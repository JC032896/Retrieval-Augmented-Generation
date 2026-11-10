# Claude Code 하네스

목표: **품질 기준을 통과하지 못하면 작업을 끝낼 수 없지만, 무한 루프나 토큰 폭증은 생기지 않는 구조.**

원칙
- 문서(md)에는 언제, 왜, 어떻게만 쓴다. 반드시 지켜야 하는 규칙은 훅과 스크립트로 강제한다.
- 가드(위험 동작 차단)는 오류가 나면 막는다(fail-closed). 게이트(종료 차단)는 오류가 나면 통과시킨다(fail-open).
- 훅이 Claude에게 돌려주는 출력은 짧게 유지한다 (stop-gate stderr 40줄 이내).
- 명령 정규식 차단은 1차 방어다. 최종 방어는 **파일 내용 해시 비교**(어떤 방법으로 바꿨든 결과에서 잡는다)와 CI의 해시 재계산이다.

## 구조

```
.claude/
├── settings.json            훅 등록 (보호 경로)
├── HARNESS.md               이 문서
├── protected.sha.lock       승인된 보호 기준 (state/protected.sha의 커밋된 사본)
├── hooks/
│   ├── guard.sh             PreToolUse: 위험 동작 차단 (fail-closed, onFailure: block, 10초)
│   ├── mark-dirty.sh        PostToolUse: 수정이 있었다는 표시만 남김 (5초)
│   └── stop-gate.sh         Stop: quality_gate --fast (fail-open, 재시도 상한 3, 180초)
├── scripts/
│   ├── quality_gate.sh      --fast / --full (종료 코드: 0 통과, 1 실패, 3 게이트 자체 오류)
│   ├── protected.py         보호 규칙의 원천: check, changed, write, venv-check, hooks-check, is-protected
│   ├── metrics.py           커버리지, skip 개수, 억제 주석, eval 점수를 baseline과 비교
│   ├── _common.sh           시스템 Python(3.11+, venv 아님)을 찾아 -I -S로 실행
│   ├── unlock.sh            [사용자 전용] 보호 경로 수정을 15분 허용
│   ├── approve.sh           [사용자 전용] 기준 갱신과 커밋 (기본은 dry-run, --yes로 실행)
│   ├── make_baseline.sh     [사용자 전용] eval/baseline.json 생성과 승인
│   └── tests/               하네스 회귀 테스트 (모두 임시 복제본에서 실행)
└── state/                   .gitignore 대상: protected.sha, venv_startup.sha, dirty, retries, unlock, gate.log
.github/workflows/quality.yml  CI: 해시 재계산(check --ci) + quality_gate --full
CLAUDE.md                      Claude가 매 세션 읽는 짧은 규칙
```

## 동작 흐름

| 시점 | 훅 | 하는 일 |
|---|---|---|
| 도구 실행 전 | guard.sh | 파괴적 명령(rm -rf, push --force, reset --hard, clean -f, Remove-Item -Recurse), 사용자 전용 스크립트 실행, git add/commit, 정책 레지스트리(Policies\ClaudeCode) 변경, 보호 경로 쓰기, 비밀 파일(.env 등) 읽기를 차단 |
| 도구 실행 후 | mark-dirty.sh | `.claude/state/dirty` 생성 (출력 없음, 자동 수정 없음) |
| 응답 종료 시 | stop-gate.sh | dirty가 있으면 `--fast` 실행. 통과하면 정리, 실패하면 exit 2로 계속 작업시킴. 2-2-2 다음 0으로 종료를 허용하고 Claude에게 실패 보고를 지시 |

`--fast` 검사 순서: 보호 경로 무결성 → 훅 설정 → venv 시작 코드 → lock 일치 → format → 타입체크 → lint → 억제 주석 → 관련 테스트
`--full`: 위 정적 검사 + 전체 테스트와 커버리지 + eval + baseline 비교 (커버리지 -0.5%p, skip 개수, 억제 주석, Recall@5/MRR, 권한 유출 0)

## 사용자 절차

모든 명령은 Claude Code 입력창에서 `!`를 붙여 실행한다. (guard는 Claude의 도구 호출만 검사한다. 혹시 막히면 별도 터미널에서 실행)

**보호 경로를 정당하게 바꿔야 할 때** (예: 테스트 기대값 수정)
1. Claude가 이유를 설명하고 승인을 요청한다
2. `! bash .claude/scripts/unlock.sh` (15분간 Claude가 보호 경로를 고칠 수 있음. 하네스 상태, lock, 사용자 설정은 제외)
3. Claude가 수정한다
4. `! bash .claude/scripts/approve.sh` 로 바뀐 목록과 diff --stat을 확인한다 (dry-run)
5. `! bash .claude/scripts/approve.sh --yes` 로 승인하고 커밋한다. unlock도 즉시 해제된다

**하네스 파일(.claude/scripts, hooks, settings.json)을 바꿀 때**: 4~5단계에 `--allow-harness-change`를 붙인다.

**baseline을 만들거나 갱신할 때** (golden set 변경, 의도적인 기준 변경): `! bash .claude/scripts/make_baseline.sh`

**의존성을 추가했을 때**: `uv.lock`은 보호 경로가 아니다. 다만 새 패키지가 `.pth`에 import 줄을 넣으면 "venv 시작 코드" 검사가 실패한다. 내용을 확인하고 `approve.sh --yes`로 승인한다.

**권한 규칙을 저장하고 싶을 때**: "다시 묻지 않기"는 `.claude/settings.local.json`에 저장된다. 이 파일은 보호하지 않지만, 게이트가 내용을 검사한다. 훅을 끄는 설정(disableAllHooks 등)이나 `hooks` 키가 있으면 실패한다. 훅은 `.claude/settings.json`에만 둔다.

**하네스 테스트 실행**
```
uv run --frozen python .claude/scripts/tests/test_protected.py
bash .claude/scripts/tests/test_approve.sh
bash .claude/scripts/tests/test_gate.sh
bash .claude/scripts/tests/test_hooks.sh
```

## 남은 위험

- **명령 정규식은 우회할 수 있다.** `python -c`, 스크립트 파일, `bash -c "..."` 안의 명령, 변수로 조립한 경로 등은 guard가 못 본다. 보호 경로는 게이트의 해시 비교로 결과에서 잡지만, 보호 경로가 아닌 곳에 대한 파괴적 명령은 막지 못할 수 있다.
- **기준 파일 동시 조작.** 보호 파일, `state/protected.sha`, lock을 함께 바꾸고 커밋까지 하면 로컬 검사는 통과한다. 커밋 차단(guard)은 정규식이라 우회할 수 있다. 최종 방어는 CI와 브랜치 보호다 (원격과 브랜치 보호를 설정해야 효과가 있다).
- **중첩 claude 실행.** Bash로 `claude -p --bare`나 `--settings '{"disableAllHooks":true}'`를 실행하면 훅 없는 에이전트가 돌 수 있다. guard는 이를 막지 않는다.
- **정책 레지스트리.** guard는 명령에 `Policies\ClaudeCode`가 보일 때만 막는다. `.reg` 파일 import처럼 경로가 명령에 드러나지 않으면 못 막는다. 결과는 게이트의 훅 설정 검사가 다음 종료 시점에 잡는다.
- **경로만 적힌 .pth.** venv 검사는 `.pth`의 import 줄만 비교한다. 경로 줄을 추가해 `sys.path` 앞쪽에 가짜 모듈(예: pytest)을 끼워 넣는 것은 잡지 못한다.
- **시스템 Python 자체 변조.** 프로젝트 밖(Python 설치 폴더)의 표준 라이브러리를 고치면 protected.py도 영향을 받는다.
- **`!` 명령과 훅.** 문서에는 `!` 명령이 "Claude를 거치지 않는다"고만 되어 있고 훅 적용 여부는 명시되어 있지 않다. 2026-11-08에 훅이 켜진 상태에서 `! bash .claude/scripts/approve.sh`가 막히지 않는 것을 실제로 확인했다. 이후 버전에서 막히면 별도 터미널에서 실행한다.
- **3회 실패 후 종료.** 게이트가 3번 연속 실패하면 종료를 허용한다. 이때 사용자에게 알리는 것은 Claude의 보고와 systemMessage(Stop에서 표시되는지 문서로 확인하지 못함)에 의존한다. dirty는 남으므로 다음 턴에 다시 검사한다.
- **훅 시간 초과.** guard는 셸 명령마다 0.7초 안팎이 걸린다. 경로가 아주 많은 명령은 10초를 넘겨 (fail-closed로) 차단될 수 있다. stop-gate가 180초를 넘기면 통과된다 (fail-open).
- **읽기만 해도 게이트 실행.** mark-dirty는 Bash/PowerShell 호출이면 읽기 명령이어도 표시한다. 그 턴의 종료 시점에 `--fast`(약 2~3초)가 돈다.
- **새 테스트 파일은 만드는 순간부터 수정이 막힌다.** guard는 경로 규칙(`tests/*`)으로 판단하므로, 승인 전이라도 Claude는 만든 파일을 고칠 수 없다 (2026-11-10 확인). 그래서 새 테스트는 임시 폴더에서 format·lint·타입체크·실행까지 통과시킨 뒤 한 번에 만든다. 고쳐야 하면 unlock이 필요하다. 해시 기준에는 approve.sh를 실행해야 들어간다.
- **사용자/플러그인 훅.** 다른 훅이 같은 이벤트에 등록되면 상호작용을 예측하기 어렵다.

## 나중에 검토할 항목

- **managed settings로 훅 고정** (지금은 만들지 않음). 관리자 권한으로 `C:\Program Files\ClaudeCode\managed-settings.json`을 만든다. managed 훅은 사용자/프로젝트 설정의 `disableAllHooks`로 끌 수 없다. managed 파일이 있으면 HKCU 정책 레지스트리도 무시된다. 초안:
  ```json
  {
    "hooks": {
      "PreToolUse": [{
        "matcher": "Bash|PowerShell|Edit|Write|NotebookEdit|Read",
        "hooks": [{
          "type": "command", "shell": "bash", "timeout": 10, "onFailure": "block",
          "command": "if [ -f \"$CLAUDE_PROJECT_DIR/.claude/hooks/guard.sh\" ]; then bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/guard.sh\"; fi"
        }]
      }]
    }
  }
  ```
  주의: managed 설정은 이 PC의 **모든 프로젝트**에 적용되므로, 위처럼 guard.sh가 없는 프로젝트에서는 아무 일도 하지 않게 해야 한다. 그런데 이렇게 하면 프로젝트의 guard.sh를 지우면 꺼진다(보호 경로라 게이트가 잡지만 사후). 더 강하게 하려면 guard 사본을 프로젝트 밖 관리자 전용 폴더에 두고 그 경로를 쓴다. 프로젝트 settings.json의 훅과 중복 실행되지 않게 정리가 필요하다.
- **eval 임베딩 캐시 해시 재사용**: `eval/cache/`가 커지면 매번 전체를 해시해 게이트가 느려진다. "크기 + 수정 시각이 같으면 이전 해시 재사용" 방식 검토.
- **run-eval 스킬**: eval을 구현한 뒤 사람만 실행하는 스킬(`disable-model-invocation: true`)로 만든다.
- **baseline.json 줄바꿈**: metrics.py가 Windows에서 CRLF로 쓴다 (해시는 정규화하므로 기능 문제는 없고, git이 줄바꿈 경고를 낸다). `newline="\n"`으로 쓰도록 수정.
- **guard 속도**: 경로 후보마다 Python을 새로 띄운다. protected.py에 여러 경로를 한 번에 판단하는 명령을 추가하면 빨라진다.
- **첫 커밋 작성자**: `b8516cb`는 예전 gmail 주소로 남아 있다. 원격에 올리기 전에 바꿀지 결정.
