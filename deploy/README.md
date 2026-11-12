# 설치형 배포 (서버 한 대)

회사 서버(또는 회사 클라우드 VM)에 Docker Compose로 설치한다. 직원은 회사 로그인 토큰으로 질문 API를 부른다.

```
 직원 ──HTTPS──▶ [회사 리버스 프록시] ──▶ [app :8000] ──▶ Claude API (답변 생성)
                                            │
                                            ├─▶ [db] Postgres + pgvector (포트 비공개)
                                            └─▶ [keycloak] 데모 로그인 (회사 로그인 시스템이 없을 때)
```

| 서비스 | 하는 일 |
|---|---|
| `setup` | 시작할 때마다 한 번: 비밀번호 파일이 없으면 만들고, 검색 모델이 없으면 받는다 |
| `db` | 문서 조각·벡터, 사용자, 감사 기록. 외부 포트를 열지 않는다 |
| `migrate` | 시작할 때마다 한 번: 스키마를 최신으로 올리고 앱·감사자 로그인 계정을 맞춘다 |
| `sync` | 시작할 때마다 한 번: 문서 폴더를 증분 수집한다 (바뀐 문서만). 앱 시작을 막지 않는다 |
| `app` | 질문 API. 시작할 때 검색 모델을 미리 읽고, 다 읽으면 `/ready`가 200 |
| `keycloak` | 데모 로그인 서버 (`compose.override.yaml`, 기본으로 함께 뜬다) |

## 준비물
- Docker (Compose v2), CPU 4코어 이상, 메모리 8GB 이상 (모델이 약 3GB를 차지한다), 디스크 15GB
- 인터넷: 처음 설치할 때 모델 내려받기, 질문할 때 Claude API. 폐쇄망은 아래 "폐쇄망" 참고

## 설치

```bash
cd deploy
docker compose up -d
```

이것만으로 샘플 문서(가상 회사 "한빛소프트")와 데모 로그인까지 준비된다.

- 처음에는 앱 이미지(약 2.5GB)와 검색 모델(약 6GB)을 받느라 수 분에서 수십 분 걸린다. 진행 상황은 다른 창에서
  `docker compose logs -f setup`. 두 번째부터는 금방 뜬다.
- 앱 이미지는 받은 코드의 버전과 같은 태그(`ghcr.io/jc032896/rag-service:<버전>`)를 GitHub 이미지 저장소에서 받는다.
  받을 수 없으면(아직 올리지 않은 버전 등) 이 폴더의 `Dockerfile`로 직접 만든다(약 5분).
- 확인: `curl localhost:8000/ready` → `{"ready": true, ...}`, `curl localhost:8000/health` → 문서 22개, 불일치 0.
- 관리 화면: 브라우저로 `http://localhost:8000/admin` → "회사 계정으로 로그인" → 데모 계정 han(중앙 관리자),
  lee(개발팀 문서 담당), park(감사 담당), 비밀번호 `demo-<아이디>`. 로그인 화면 주소는 `keycloak.localhost:8080`이다
  (브라우저가 이 PC로 보낸다. 안 열리면 hosts 파일에 `127.0.0.1 keycloak.localhost`를 넣는다).
- 답변을 받으려면 Claude API 키가 필요하다: `cp .env.example .env`, `ANTHROPIC_API_KEY=` 채우고 `docker compose up -d`.
  키가 없으면 로그인과 검색까지는 되고 답변 단계에서 503("답변 LLM이 설정되지 않았습니다")이 난다.

### 비밀번호
DB 소유자·앱·감사 담당 계정과 데모 Keycloak 관리자 비밀번호는 `setup`이 처음 한 번 무작위로 만들어 비밀 볼륨에
파일로 저장한다. 사람이 알 필요가 없고, 화면이나 로그에 출력하지 않는다. 볼륨은 필요한 서비스에만 붙인다:
앱 컨테이너는 앱·감사 계정 비밀번호만 보고, DB 소유자 비밀번호는 모른다.

- 직접 정하려면 **처음 실행하기 전에** `.env`의 `*_PASSWORD`를 채운다. 이미 만들어진 뒤에 바꾸면 반영되지 않는다
  (DB는 처음 만들 때의 소유자 비밀번호를 기억한다).
- 확인이 필요하면: `docker compose exec keycloak cat /run/rag/keycloak/keycloak_admin_password` (데모 관리자).
- 처음부터 다시 설치하려면 데이터와 비밀번호를 함께 지운다: `docker compose down -v` (**DB 데이터도 지워진다**).

### 회사 문서 넣기
`.env`의 `CORPUS_DIR`을 회사 문서 폴더로 바꾸고 `docker compose up -d`. 폴더 형식은 샘플(`samples/`)과 같다:
`org.yaml`(부서·역할·직원), `acl.yaml`(문서별 제목, 보안 등급, 볼 수 있는 부서·역할), `docs/`(PDF, DOCX, MD).
시작할 때마다 `sync`가 바뀐 문서만 다시 수집한다.

관리 화면(API는 `/admin/api/documents`)에서 올린 문서는 `uploads` 볼륨에 두고 권한은 DB에 저장한다.
두 방식을 함께 써도 서로 지우거나 덮어쓰지 않는다 (README "문서 올리기와 권한 지정"). 리버스 프록시의
요청 크기 제한(nginx `client_max_body_size`)을 `UPLOAD_MAX_MB`(기본 30MB)보다 크게 둔다.

질문은 `POST /ask`에 `Authorization: Bearer <로그인 토큰>`을 붙여 보낸다 (README "질문 API").

## 정기 작업
서버의 cron(Windows는 작업 스케줄러)에 등록한다. `deploy` 폴더에서 실행한다.

```cron
# 매일 02:00 문서 증분 수집 (바뀐 문서만 다시 임베딩). 원문에서 지운 문서까지 정리하려면 --prune
0 2 * * *  cd /opt/rag/deploy && docker compose run --rm sync
# 매일 03:00 감사 기록 보관 기간 정리 (AUDIT_RETENTION_DAYS를 정한 경우만 지운다). 소유자 계정으로
0 3 * * *  cd /opt/rag/deploy && docker compose run --rm migrate python -m rag_service.audit purge
# 매주 월요일 원문과 인덱스 점검 (문제가 있으면 종료 코드 1 → 경보에 연결)
0 7 * * 1  cd /opt/rag/deploy && docker compose run --rm sync python -m rag_service.ingest check /data/corpus
```

## 업데이트와 백업

```bash
# 백업 (매일 권장, 결과 파일은 다른 저장소로 옮긴다). 비밀 볼륨도 함께 보관한다
docker compose exec db pg_dump -U rag_owner -Fc rag > rag-$(date +%F).dump
# 관리 화면에서 올린 문서 원문 (DB 백업과 같은 시점에)
docker compose exec app tar czf - -C /data/uploads docs > uploads-$(date +%F).tgz

# 업데이트: 백업 → 새 버전 코드 받기 → 다시 시작. 버전이 바뀌면 그 버전의 이미지를 받고,
# setup·migrate·sync가 필요한 일을 한다
git fetch --tags && git checkout v0.2.0 && docker compose up -d
# 코드를 직접 고쳐서 쓰는 경우에만: docker compose up -d --build

# 복구 (서비스를 멈추고)
docker compose stop app
docker compose exec -T db pg_restore -U rag_owner -d rag --clean --if-exists < rag-2026-11-11.dump
docker compose start app
```
마이그레이션은 앞으로만 올린다. 되돌려야 하면 백업으로 복구한다 (downgrade는 데이터를 지울 수 있다).

## 로그인
- **데모 (기본)**: `compose.override.yaml`이 Keycloak을 띄우고 앱을 연결한다. `samples/org.yaml`의 직원
  kim, lee, park, choi, jung, han이 들어 있고 비밀번호는 `demo-<아이디>`다. 관리 역할 그룹은 han(중앙 관리자),
  lee(개발팀 문서 담당), park(감사 담당)에 들어 있다.
- **관리 역할**: 회사 로그인 시스템에 그룹 세 개(기본 이름 `rag-admin`, `rag-doc-manager`, `rag-auditor`)를 만들고
  토큰에 그룹 값(`groups`)이 실리게 한다. 이름이 다르면 `.env`의 `ADMIN_GROUP` 등을 바꾼다 (README "관리 API").
- **관리 화면 로그인 (운영)**: 회사 로그인 시스템에 이 앱을 "단일 페이지 앱(SPA, 공개 클라이언트 + PKCE)"으로 등록하고
  리디렉션 주소 `https://<서버>/admin/callback`, 로그아웃 후 주소 `https://<서버>/admin/`, 웹 출처 `https://<서버>`를
  넣는다. 클라이언트 id가 `OIDC_AUDIENCE`와 다르면 `.env`의 `ADMIN_UI_CLIENT_ID`에 적는다.
- **회사 로그인 시스템 (운영)**: `compose.override.yaml`을 지우고(또는 `docker compose -f compose.yaml up -d`),
  그 시스템(Microsoft 365, Google Workspace, 사내 SSO)에 이 앱을 등록한 뒤 `.env`의 `OIDC_ISSUER`,
  `OIDC_AUDIENCE`, `OIDC_LOGIN_CLAIM`을 채운다. `users.login`(문서 폴더 `org.yaml`의 id)이 토큰의 그 값
  (보통 메일 주소)과 같아야 한다.

### 데모 계정으로 질문하기

```bash
# kim(개발팀 사원)으로 토큰 받기
TOKEN=$(curl -s -d client_id=rag-service -d grant_type=password -d username=kim -d password=demo-kim \
  http://keycloak.localhost:8080/realms/hanbit/protocol/openid-connect/token | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -N -X POST localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @question.json   # {"question": "출장비 정산은 언제까지 해야 해?"} (UTF-8 파일)
```

- realm 파일: `deploy/keycloak/hanbit-realm.json`. Keycloak 관리 화면은 `http://localhost:8080/admin`
  (admin / 위 "비밀번호"의 명령으로 확인).
- **데모 전용인 부분**: 비밀번호 `demo-<아이디>`, 아이디·비밀번호로 바로 토큰을 받는 방식(password grant),
  http 통신(`OIDC_ALLOW_HTTP_HOSTS=keycloak.localhost`), `start-dev` 모드(내장 DB). 운영에서 Keycloak을 쓰려면 HTTPS
  주소와 별도 DB로 띄우고(`start`), 웹 화면은 브라우저 로그인(authorization code + PKCE)을 쓴다.
- Windows Git Bash에서는 `docker compose run ... /data/...` 같은 경로가 바뀌므로 `MSYS_NO_PATHCONV=1`을 앞에
  붙이거나 PowerShell에서 실행한다. `curl -d`로 한글을 보내면 깨지니 UTF-8 파일을 `--data-binary @파일`로 보낸다.

## 폐쇄망 (인터넷이 막힌 서버)
1. 인터넷이 되는 PC에서 `docker compose up -d`로 한 번 설치해 이미지와 모델을 만든다.
   `docker save ghcr.io/jc032896/rag-service:0.1.0 pgvector/pgvector:pg17 quay.io/keycloak/keycloak:26.0 -o images.tar`
   (버전은 받은 코드의 것. 사내 레지스트리에 올려 두고 `.env`의 `APP_IMAGE`로 가리켜도 된다)
   모델 볼륨은 `docker run --rm -v rag-service_models:/m -v $PWD:/out alpine tar czf /out/models.tgz -C /m .`
2. 서버에서 `docker load -i images.tar`, 모델 볼륨 `rag-service_models`를 만들고 `models.tgz`를 풀어 넣는다.
3. `.env`에 `OFFLINE_INSTALL=1`을 넣고 `docker compose up -d`. `setup`은 모델을 받지 않고 있는지만 확인한다.

**남는 외부 통신은 Claude API(답변 생성)뿐이다.** 질문할 때 근거 문서 조각이 Anthropic으로 전송되므로
회사 보안 정책의 허용이 필요하다. 완전 폐쇄망이면 답변 LLM을 사내 모델로 바꾼다:
`LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`(사내 vLLM·Ollama 주소), `LLM_MODEL`.
함께 띄우는 예시는 `docker compose --profile ollama up -d` 후 `docker compose exec ollama ollama pull <모델>`
(모델 파일도 인터넷이 되는 곳에서 받아 볼륨째 옮긴다). 품질 차이는 README "답변 LLM 선택" 참고.

## 규모가 커지면
| | 이 compose | 바꿀 것 |
|---|---|---|
| DB | 같은 서버의 컨테이너 | 관리형 Postgres(예: AWS RDS, Azure Database) + pgvector, 자동 백업 |
| 비밀 | 비밀 볼륨의 파일 (`setup`이 생성) | Vault, 클라우드 비밀 저장소, Kubernetes Secret (`*_FILE` 설정은 그대로 쓴다) |
| 앱 | 컨테이너 1개(워커 1) | 컨테이너 여러 개 + 부하 분산. 동시 요청 한도는 컨테이너마다 센다 |
| 수집 | 시작 시 `sync` + cron | 작업 큐(로드맵 7단계), Kubernetes CronJob |
| 배포 | compose | Kubernetes. 이미지와 환경 변수는 그대로 쓰고 `setup`·`migrate`는 Job, `/ready`는 readiness probe로 |
