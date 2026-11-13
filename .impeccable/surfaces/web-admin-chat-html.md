---
version: 1
slug: "web-admin-chat-html"
primary_target: "web/admin/chat.html"
related_targets: ["web/admin/src/chat"]
---

## Scope

직원 채팅 화면 (`/`, web/admin 빌드의 두 번째 입구 chat.html): 질문하기, 실시간 답, 인용 근거 문단, 대화 기록(목록·다시 보기·지우기). Mode: Operate.

## Audience and job

- 회사의 모든 직원. 업무용 데스크톱, 사무실 낮 시간. 업무 중 수시로 짧게 들어와 규정·절차를 묻고 바로 닫는다 (사용자 답).
- 할 일: 묻고, 답을 읽고, 필요하면 근거 문단을 확인한다. 가끔 지난 질문을 다시 연다.
- 피할 것 (사용자 답): 근거 확인이 번거로움, 딱딱하고 어려움, ChatGPT 복제처럼 보임.

## Constraints

- 화이트라벨(회사 이름·로고), 한국어, WCAG 2.2 AA, 데스크톱 우선, 휴대폰에서 깨지지 않게. 관리 화면과 같은 로그인.
- API: POST /ask(SSE: delta, done, error), /api/me·history·passages (README "채팅 화면 API와 대화 기록").
- 근거 문단은 답에 쓰인 조각까지만. 원본 파일 열기는 없다. 권한이 바뀐 지난 답은 가려져 온다(hidden).
- 상태: 답하는 중, 근거 없어 거절, 인용 확인 안 된 문장, 오류, 하루 한도(429), 준비 중(503), 기록 꺼짐(history_days 0).

## Direction contract

THESIS: 답의 문장과 근거 문단을 같은 색 형광펜으로 이어, 어느 문장이 어디서 왔는지 누르지 않아도 보인다. 말풍선과 보라 강조의 흔한 AI 채팅, 각주 번호만 달린 답을 거부한다.

OWN-WORLD: 흰 복사지 작업면(#FFFFFF), 왼쪽 목록칸은 옅은 회백(#F5F5F2), 먹 글자(#1D1D1B). 형광펜 세 색(노랑 #FFE14D, 민트 #9BE3C3, 분홍 #FFB8CB)이 인용 1·2·3번에 차례로 붙고 넷째부터 다시 돈다. 칠은 글자 아래 절반만 긋는 밑줄형, 번호는 둥근 테 번호표. 글꼴은 Pretendard 하나, 크기와 굵기로만 위계. 그림자 없음.

STORY: 묻는다 → 답이 흘러나온다 → 답이 끝나 인용이 확인되면 근거 있는 문장에 형광펜이 그어진다 → 오른쪽 근거 칸의 같은 색 문단을 읽는다. 칠이 없거나 점선 밑줄인 문장은 근거가 확인되지 않은 것이라 스스로 판단한다.

FIRST VIEWPORT: 3단. 왼쪽 248px 기록 목록(회사 이름, '새 질문', 오늘/이전 묶음, 아래에 이름·부서, 관리 역할이면 관리 화면 링크). 가운데 질문 제목과 메타(시각 · 근거 n건 · 인용 확인), 답 본문, 아래 고정 입력창과 '묻기'(주 동작)와 오늘 남은 질문 수. 오른쪽 440px '근거 문단' 칸: 번호표·문서 제목·조항·쪽·현행 여부와 문단. 첫 방문은 가운데에 입력창과 안내 한 줄.

SIGNATURE: 형광펜 연결. 칠한 문장이나 번호표에 마우스·초점을 두면 오른쪽 같은 색 문단이 진해지고 그 자리로 스크롤된다(반대 방향도). 답이 끝나면 칠이 왼쪽에서 오른쪽으로 한 번 그어진다(약 200ms, 움직임 줄이기면 즉시). 근거 칸은 문단 전체를 같은 색 띠로 표시하고, 원문 안의 정확한 문장을 칠한 척하지 않는다.

RAISES: 오늘 남은 질문 수를 입력창 옆에 늘 숫자로 (카세트 속지에서), 확인 안 된 문장은 색 대신 회색 점선 밑줄로도 구분 (분광선 띠에서), 번호표가 곧 주소: 누르면 그 근거 문단으로 바로 감 (행사 카탈로그에서).

FORM: 형광펜 밑줄, 내 후보 목록의 1번 (IMPECCABLE'S PICK으로 사용자가 고름), seed:2f3c029469007f16. 선택한 스케치: .impeccable/mocks/decision/model-pick.html (code-led).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
