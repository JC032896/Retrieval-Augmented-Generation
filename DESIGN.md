---
name: 문서 질의 관리 (web/admin)
description: 권한을 지키는 사내 문서 질의 서비스의 관리 화면. 문서는 등기처럼 허가된 사람에게만 배달되고, 모든 전달은 배송조회처럼 추적된다.
colors:
  kraft: "#7a5636"
  kraft-deep: "#5e4128"
  kraft-ink: "#fff8ee"
  kraft-tint: "#ecdfcf"
  paper: "#f6f6f2"
  sheet: "#ffffff"
  ink: "#1c1c1a"
  ink-2: "#55534d"
  rule: "#d9d6cc"
  rule-strong: "#1c1c1a"
  ok: "#2f6f4f"
  ok-tint: "#e6f0ea"
  ok-ink: "#1f4d36"
  blocked: "#c8102e"
  blocked-tint: "#fbe8eb"
  blocked-ink: "#8f0b21"
  pending: "#8a5a00"
  level-0: "#2f6f4f"
  level-1: "#2e5e8c"
  level-2: "#8a5a00"
  level-3: "#c8102e"
  focus: "#2e5e8c"
typography:
  display:
    fontFamily: "Barlow Condensed, Pretendard Variable, sans-serif"
    fontSize: "2.75rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.03em"
  headline:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1.55
  caption:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, Malgun Gothic, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.55
  number:
    fontFamily: "Barlow Condensed, Pretendard Variable, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.03em"
rounded:
  tag: "3px"
  control: "6px"
  dot: "50%"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "40px"
components:
  button-default:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-default-hover:
    backgroundColor: "{colors.paper}"
  button-primary:
    backgroundColor: "{colors.kraft}"
    textColor: "{colors.kraft-ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.kraft-deep}"
  button-danger:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.blocked}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-danger-hover:
    backgroundColor: "{colors.blocked}"
    textColor: "{colors.sheet}"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "40px"
  choice:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "36px"
  choice-selected:
    backgroundColor: "{colors.kraft-tint}"
    textColor: "{colors.ink}"
  nav-link:
    backgroundColor: "{colors.kraft}"
    textColor: "{colors.kraft-ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  nav-link-hover:
    backgroundColor: "{colors.kraft-deep}"
  nav-link-active:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  level-0:
    backgroundColor: "{colors.level-0}"
    textColor: "{colors.sheet}"
    typography: "{typography.caption}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  level-1:
    backgroundColor: "{colors.level-1}"
    textColor: "{colors.sheet}"
    typography: "{typography.caption}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  level-2:
    backgroundColor: "{colors.level-2}"
    textColor: "{colors.sheet}"
    typography: "{typography.caption}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  level-3:
    backgroundColor: "{colors.level-3}"
    textColor: "{colors.sheet}"
    typography: "{typography.caption}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  waybill-label:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "16px"
    height: "136px"
  panel:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "24px"
  notice-ok:
    backgroundColor: "{colors.ok-tint}"
    textColor: "{colors.ok-ink}"
    typography: "{typography.body-sm}"
    padding: "12px 16px"
  notice-blocked:
    backgroundColor: "{colors.blocked-tint}"
    textColor: "{colors.blocked-ink}"
    typography: "{typography.body-sm}"
    padding: "12px 16px"
  recipient-confirm:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "24px"
---

# Design System: 문서 질의 관리 (web/admin)

## Overview

**Creative North Star: "등기 접수 창구"**

이 화면은 우체국 등기 창구다. 문서는 등기번호를 받고, 받는 사람이 정해진 뒤에야 나가며, 그 뒤의 모든 일은 배송조회처럼 점과 선으로 남는다. 왼쪽에는 크라프트 상자색 메뉴 띠가 끝까지 이어지고, 오른쪽 작업면은 감열지처럼 희고 담담하다. 먹색 글자와 여백이 대부분의 구획을 맡고, 굵은 먹선은 송장 라벨처럼 "지금 꼭 읽어야 하는 칸"에만 둘러진다.

밀도는 낮게, 문장은 짧게 둔다. 사용자는 가끔 들어와 일을 처리하는 관리자라서, 화면은 설명 없이 읽혀야 하고 권한을 바꾸는 순간에는 불안 대신 확인을 준다: 저장 전에 받는 사람 명단과 숫자를 크게 보여 주는 단계가 반드시 끼어든다. 회색 사이드바·숫자 카드·파란 강조로 된 흔한 관리자 템플릿의 모양은 거부한다.

색은 의미를 가진 곳에만 쓴다. 크라프트는 브랜드의 손길(메뉴 띠, 주 버튼, 진행된 단계), 등급 네 색은 보안 등급에만, 적색은 기밀과 막힌 상태에만. 나머지는 먹과 종이다.

**Key Characteristics:**
- 크라프트 메뉴 띠(232px) + 종이색 바탕 + 흰 칸의 2단 구조
- 그림자 없는 평면. 구획은 여백, 흰 칸, 1px 연한 선으로
- 2px 먹선 상자는 송장 라벨(대시보드 상태 칸)과 받는 사람 확인 상자에만
- 등기번호와 숫자는 압축 숫자체(Barlow Condensed), 그 밖은 한글 고딕(Pretendard)
- 배송조회 점·선 단계 표시가 시그니처. 움직임은 점이 차례로 채워지는 짧은 전이 하나뿐

## Colors

크라프트 한 색과 먹·종이 중립색, 그리고 엄격히 묶인 상태색과 등급색으로 된 절제된 팔레트.

### Primary
- **크라프트 상자색** (kraft): 메뉴 띠 바탕, 주 버튼, 링크 글자, 배송조회에서 끝난 단계의 점과 선, 체크박스·라디오의 accent. 화면에서 "이 서비스의 손"이 닿는 곳.
- **짙은 크라프트** (kraft-deep): 메뉴 항목과 주 버튼의 hover.
- **크라프트 위 글자** (kraft-ink): 메뉴 띠와 주 버튼 위의 따뜻한 흰 글자.
- **크라프트 옅은 바탕** (kraft-tint): 고른 선택 칸의 바탕, "새로 봄" 꼬리표, 텍스트 선택 영역.

### Neutral
- **종이** (paper): 작업면 바탕. 활성 메뉴 항목의 바탕이기도 해서 "띠에서 종이로 나온" 느낌을 만든다.
- **감열지 흰 칸** (sheet): 패널, 표, 사실 목록, 송장 라벨의 바탕.
- **먹** (ink): 본문 글자, 기본 버튼 테두리. 같은 값의 **먹선**(rule-strong)은 송장 라벨·확인 상자 테두리와 표 머리 아래 2px 선.
- **흐린 먹** (ink-2): 보조 글자, 도움말, 입력 칸 테두리, 브라우저가 그리는 아이콘(검색 지우기, 날짜).
- **연한 줄** (rule): 표 행 사이, 목록 항목 사이 1px 선, 아직 오지 않은 배송조회 단계, 스크롤바.

### 상태색 (Secondary)
- **정상 녹색** (ok), **정상 알림 바탕/글자** (ok-tint / ok-ink): 정상 상태 문구, '확인할 일'이 비었을 때의 윗선, 성공 알림.
- **막힘 적색** (blocked), **막힘 알림 바탕/글자** (blocked-tint / blocked-ink): 막힌 송장 라벨, 막힘 알림, 위험 버튼, 삭제 구역 윗선, 더 이상 볼 수 없게 되는 사람.
- **대기 황토** (pending): 진행 중·거절된 감사 결과 등 "아직/보류" 상태.

### 보안 등급색 (Tertiary)
- **0 공개** (level-0, 녹색), **1 사내** (level-1, 남청), **2 대외비** (level-2, 황토), **3 기밀** (level-3, 적색): 등급 배지에만. 값이 상태색과 겹치지만 역할은 따로 관리한다.
- **초점 남청** (focus): 모든 키보드 초점 고리(2px, 2px 띄움). 크라프트 띠 위에서는 kraft-ink로 바뀐다.

### Named Rules
**The 적색 두 곳 Rule.** 적색은 3 기밀 등급과 막힌 상태(오류, 위험 동작, 권한을 잃는 사람)에만 쓴다. 강조나 장식으로 적색을 쓰면 막힘 신호가 죽는다.

**The 등급색 전용 Rule.** 등급 네 색은 등급 배지에만 쓴다. 차트·꼬리표·버튼에 같은 색을 빌려 쓰지 않는다.

**The 옅은 바탕 알림 Rule.** 알림(성공·막힘)은 테두리가 아니라 옅은 바탕(ok-tint, blocked-tint)과 짙은 글자(ok-ink, blocked-ink)로 표시한다. 옅은 바탕 위 대비는 4.5:1 이상을 지킨다.

## Typography

**Display Font:** Barlow Condensed 700 (Pretendard Variable로 대체)
**Body Font:** Pretendard Variable (Pretendard, -apple-system, Malgun Gothic으로 대체)

**Character:** 송장 번호처럼 좁고 굵은 숫자체와, 차분하고 읽기 쉬운 한글 고딕의 짝. 숫자는 도장처럼 찍히고, 문장은 조용히 설명한다.

### Hierarchy
- **Display** (700, 2.75rem, 1): 송장 라벨의 값, 문서 상세 머리의 등기번호, 받는 사람 수. 숫자 전용.
- **Headline** (700, 1.625rem, 1.3, -0.02em): 페이지 제목. 송장 라벨의 한글 값("준비됨", "설정 안 됨")도 숫자체 대신 이 크기의 본문 글꼴을 쓴다.
- **Title** (700, 1.125rem, 1.3): 패널·구역 제목.
- **Body** (400, 1rem, 1.55): 본문. 긴 설명은 65~72ch 안으로. `word-break: keep-all`로 어절 단위 줄바꿈.
- **Body-sm** (400, 0.875rem): 표 칸, 목록, 알림, 보조 설명.
- **Label** (700, 0.875rem): 입력 칸 이름, legend.
- **Caption** (400, 0.8125rem): 도움말, 사실 목록의 이름(dt), 표 머리, 범례, 등급 배지(700).
- **Number** (Barlow Condensed 700, 1.125rem, 0.03em): 표 안의 등기번호. 송장 라벨의 영문 코드(INDEX, MODEL…)는 0.06em.

### Named Rules
**The 숫자체는 숫자에만 Rule.** 압축 숫자체는 숫자와 등기번호(FD-0001, UP-0032)에만 쓴다. 아이디, 환경 변수 이름, 파일 경로, 한글 값은 본문 글꼴로 둔다.

**The 머리 위 꼬리글 금지 Rule.** 제목 위에 작은 대문자 꼬리글(eyebrow/kicker)을 달지 않는다. 맥락은 빵부스러기 경로(문서 / UP-0032)나 제목 옆 기준 시각으로 준다.

**The 도움말 분리 Rule.** 도움말은 label 안에 넣지 않고 label 아래 별도 문장으로 두며 `aria-describedby`로 입력 칸에 잇는다.

## Layout

- **골격:** 왼쪽 232px 크라프트 메뉴 띠(화면에 붙음, 스크롤해도 띠 색이 끝까지 이어짐) + 오른쪽 작업면(안쪽 여백 32px 40px). 페이지 내용 최대 폭 1480px.
- **본문 + 옆단:** 대시보드, 문서 상세, 감사 상세는 `본문 1fr + 옆단 380px`, 간격 32px. 옆단은 '확인할 일', '받는 사람', 확인 상자, 위험 구역처럼 판단을 돕는 칸.
- **송장 라벨 줄:** 최소 220px 칸이 자동으로 채워지는 격자, 간격 16px, 라벨 최소 높이 136px.
- **간격 리듬:** 4·8·12·16·24·32·40px 일곱 단계. 패널 안은 24px, 패널 사이 24~32px, 입력 묶음 안은 8px.
- **반응형:** 1180px 이하에서 옆단이 본문 아래로 내려가되 대시보드의 '확인할 일'은 위로 올라와 막힌 것이 먼저 보인다. 900px 이하에서 메뉴 띠가 위로 올라가 가로 줄로 놓이고 작업면 여백은 24px 16px. 720px 이하에서 표는 행마다 2열 격자 카드로 바뀌고 머리글은 화면 낭독기용으로만 남는다.

### Named Rules
**The 열 고정 Rule.** 표의 열 구성은 고정하고 상태만 행을 바꾼다. 상태 때문에 열을 숨기거나 순서를 바꾸지 않는다.

## Elevation & Depth

그림자는 쓰지 않는다. 깊이는 세 층의 색으로만 만든다: 크라프트 띠 → 종이 바탕 → 흰 칸. 칸은 테두리 없이 종이 위에 놓인 흰 면으로 구분되고, 칸 안의 항목은 1px 연한 줄로 나뉜다. 강조가 필요한 칸은 그림자 대신 윗선(4px)이나 2px 먹선 상자를 받는다.

### Named Rules
**The 그림자 없음 Rule.** box-shadow를 쓰지 않는다. 떠 보이게 하고 싶다면 흰 칸과 여백으로 해결한다.

## Shapes

- **모서리:** 조작 요소(버튼, 입력 칸, 선택 칸, 메뉴 항목)만 6px로 살짝 둥글다. 배지와 꼬리표는 3px. 패널, 송장 라벨, 확인 상자, 표는 각진 0px: 종이와 라벨은 잘린 모서리다.
- **원:** 배송조회 단계 점(표 10px, 범례 8px, 세로 이력 12px)만 완전한 원.
- **선의 위계:** 1px 연한 줄(구분) < 2px 먹선(표 머리 아래, 송장 라벨, 확인 상자) < 4px 윗선(옆단 '확인할 일'은 녹색/적색, 위험 구역과 막힘 안내는 적색).

### Named Rules
**The 먹선 상자 두 곳 Rule.** 사방을 두른 2px 먹선 상자는 대시보드 송장 라벨과 받는 사람 확인 상자에만 쓴다. 막힌 송장 라벨은 같은 2px 선을 적색으로 바꾼다. 다른 칸은 테두리 없이 흰 면과 여백으로 나눈다.

## Components

### Buttons
담백하고 단단하다. 누를 곳임이 선으로 분명하다.
- **Shape:** 6px 모서리, 최소 높이 40px, 좌우 16px, 글자와 아이콘 사이 8px.
- **기본:** 흰 칸 + 1px 먹선 + 먹 글자(500). hover는 종이색 바탕.
- **주 버튼:** 크라프트 바탕 + kraft-ink 글자(700). hover는 짙은 크라프트. 한 화면 한 구역에 하나.
- **위험:** 흰 바탕 + 적색 선과 글자. hover에서 적색 바탕 + 흰 글자로 뒤집힌다.
- **비활성:** 투명도 0.55, not-allowed 커서. 전이는 바탕색 160ms ease-out.

### Chips / 선택 칸
- **Style:** 체크박스·라디오를 감싼 칸. 흰 바탕 + 1px 연한 줄, 6px, 높이 36px, body-sm.
- **State:** 고르면 크라프트 선 + 크라프트 옅은 바탕 + 700. 키보드 초점은 칸 전체에 남청 고리.

### Cards / Containers (패널, 사실 목록)
- **Corner Style:** 0px.
- **Background:** 종이 위 흰 칸.
- **Shadow Strategy:** 없음 (Elevation & Depth 참조).
- **Border:** 없음. 강조는 4px 윗선으로만.
- **Internal Padding:** 24px. 사실 목록은 최소 180px 열이 자동으로 채워지는 격자, 이름은 caption + 흐린 먹, 값은 500.

### Inputs / Fields
- **Style:** 흰 바탕 + 1px 흐린 먹 선, 6px, 높이 40px, 좌우 12px. hover에서 선이 먹색으로.
- **Focus:** 전역 초점 고리(2px 남청, 2px 띄움).
- **이름과 도움말:** 이름은 label(700), 도움말은 그 아래 caption + 흐린 먹, `aria-describedby`로 연결.
- **브라우저 기본 부분:** 파일 고르기 버튼은 기본 버튼과 같은 모양, 검색 지우기 ×와 날짜 아이콘은 흐린 먹색 마스크 아이콘으로 다시 그린다.

### Notices / 알림
- 성공은 ok-tint 바탕 + ok-ink 글자(500), 막힘은 blocked-tint 바탕 + blocked-ink 글자(500), 중립은 흰 바탕 + 흐린 먹. 안쪽 12px 16px, body-sm. 테두리 없음.

### Navigation (크라프트 메뉴 띠)
- **Style:** 크라프트 바탕, 위에 회사 이름(title 700)과 제품 이름(caption), 아래 끝에 로그인한 사람·역할과 로그아웃(반투명 kraft-ink 1px 선으로 구분).
- **항목:** 아이콘 + 이름, 안쪽 10px 12px, 6px 모서리. hover는 짙은 크라프트, 현재 페이지는 종이색 바탕 + 먹 글자 700. 초점 고리는 kraft-ink.
- **좁은 화면:** 900px 이하에서 띠가 위쪽 가로 줄이 되고 항목이 줄바꿈된다. 역할에 따라 보이는 항목만 달라진다.

### 보안 등급 배지
- 등급 색 바탕 + 흰 글자, caption 700, 3px, 안쪽 2px 8px. 숫자와 이름을 함께 쓴다("1 사내") — 색만으로 뜻을 전하지 않는다.

### 송장 라벨 (대시보드 상태 칸)
- 흰 칸 + 2px 먹선, 0px, 안쪽 16px, 최소 높이 136px. 위 줄: 한글 이름(body-sm, 흐린 먹)과 오른쪽 영문 코드(숫자체 700). 가운데: Display 숫자 + 본문 글꼴 단위("건"), 또는 Headline 크기 한글 값. 아래: 한 줄 설명.
- 막히면 선과 값이 적색. 정상이면 설명이 녹색.

### 배송조회 단계 표시 (시그니처)
- **가로 단계:** 10px 점과 30px × 2px 선. 끝난 단계는 크라프트, 남은 단계는 연한 줄. 점은 차례로 채워진다(360ms ease-out, 단계마다 90ms 지연). 옆에 요약 문장(body-sm).
- **범례:** 8px 크라프트 점 + 이름이 한 덩어리로 줄바꿈된다(나눠지지 않음). caption, 흐린 먹.
- **세로 이력 (문서 상세):** 12px 원, 2px 크라프트 테두리. 가장 최근 단계만 크라프트로 채우고 지난 단계는 흰 속. 점 사이는 2px 연한 줄. 각 줄은 동작 이름 + 누가·언제(body-sm, 흐린 먹) + 한 줄 내용.
- **움직임:** 이 전이가 화면의 유일한 연출이다. `prefers-reduced-motion: reduce`에서 모든 시간 토큰이 0ms가 되어 즉시 채워진다.

### 받는 사람 명단과 확인 상자
- **명단:** Display 크라프트 숫자 + "명이 볼 수 있습니다" + 전체 수(흐린 먹). 부서별 줄은 7em 부서 이름 + 사람들, 1px 연한 줄로 구분.
- **바뀌는 사람:** 새로 보게 되는 사람은 "+ 이름" 700 + 크라프트 옅은 바탕 "새로 봄" 꼬리표. 더 이상 못 보게 되는 사람은 "− 이름" + blocked-ink 글자. 기호와 글자로 구분하고 색에만 기대지 않는다.
- **확인 상자:** 저장 전에 끼어드는 두 번째 단계. 흰 칸 + 2px 먹선, 안쪽 24px, 제목 "받는 사람 n명을 확인해 주세요"(title), 바뀌는 내용은 크라프트 가운뎃점 목록, 아래에 주 버튼(이 명단으로 저장)과 기본 버튼(다시 고치기).

## Do's and Don'ts

### Do:
- **Do** 모든 문서를 등기번호로 부르고, 등기번호는 숫자체(Barlow Condensed 700, 0.03em)로 쓴다.
- **Do** 권한을 바꾸는 저장 앞에는 받는 사람 수와 바뀌는 사람을 보여 주는 확인 상자를 둔다.
- **Do** 알림은 옅은 바탕(ok-tint, blocked-tint)과 짙은 글자(ok-ink, blocked-ink)로 표시한다.
- **Do** 칸은 테두리 대신 종이 위 흰 면과 24px 여백으로 나누고, 항목 사이는 1px 연한 줄로 나눈다.
- **Do** 상태와 등급을 색과 함께 글자·기호로도 표시한다("1 사내", "+ 새로 봄", "− 더 이상 못 봄").
- **Do** 브라우저가 그리는 부분(파일 고르기 버튼, 검색 지우기, 날짜 아이콘)도 팔레트로 다시 칠한다.
- **Do** 범례의 점과 이름은 한 덩어리로 줄바꿈되게 묶는다.
- **Do** 움직임은 시간 토큰(160ms, 360ms, 90ms 지연)만 쓰고, 줄이기 설정에서 0ms가 되게 한다.

### Don't:
- **Don't** 2px 먹선 상자를 송장 라벨과 받는 사람 확인 상자 밖에서 쓰지 않는다.
- **Don't** 적색을 기밀 등급과 막힌 상태(권한을 잃는 사람 포함) 밖에서 쓰지 않는다.
- **Don't** 등급 네 색을 등급 배지 밖에서 쓰지 않는다.
- **Don't** 제목 위에 eyebrow/kicker 꼬리글을 달지 않는다.
- **Don't** 아이디, 환경 변수 이름, 파일 경로에 숫자체를 쓰지 않는다.
- **Don't** 도움말을 label 안에 넣지 않는다.
- **Don't** box-shadow, 회색 사이드바, 숫자 카드 격자, 파란 강조색 같은 흔한 관리자 템플릿 모양을 쓰지 않는다.

## 열린 기회 (규칙 아님)

마감 검토에서 다음 단계로 미룬 항목이다. 아직 만들어지지 않았으므로 규칙이 아니라 방향으로만 남긴다.
- 송장 라벨 안쪽의 칸 나눔선(실제 송장처럼 이름·값·설명 구획).
- 문서 상세 머리에 가로 배송조회 단계 표시.
- 받는 사람 확인 단계를 영수증처럼 보이게 하기.
