# 설치형 배포 (서버 한 대)

회사 서버(또는 회사 클라우드 VM)에 Docker Compose로 설치한다. 직원은 회사 로그인 토큰으로 질문 API를 부른다.

```
 직원 ──HTTPS──▶ [회사 리버스 프록시] ──▶ [app :8000] ──▶ Claude API (답변 생성)
                                            │
                                            ├─▶ [db] Postgres + pgvector (포트 비공개)
                                            └─▶ [keycloak] 로그인 (계정 시스템이 없는 회사만, 선택)
```

| 서비스 | 하는 일 |
|---|---|
| `db` | 문서 조각·벡터, 사용자, 감사 기록. 외부 포트를 열지 않는다 |
| `migrate` | 시작할 때마다 한 번: 스키마를 최신으로 올리고 앱·감사자 로그인 계정을 맞춘 뒤 끝난다 |
| `app` | 질문 API. 시작할 때 검색 모델을 미리 읽고, 다 읽으면 `/ready`가 200 |
| `keycloak` | 데모 로그인 서버 (`--profile keycloak`일 때만) |

## 준비물
- Docker (Compose v2), CPU 4코어 이상, 메모리 8GB 이상 (모델이 약 3GB를 차지한다), 디스크 15GB
- 인터넷: 설치 때 모델 내려받기, 질문할 때 Claude API. 폐쇄망은 아래 "폐쇄망" 참고

## 설치

```bash
cd deploy
cp .env.example .env        # DB_OWNER_PASSWORD, APP_DB_PASSWORD, ANTHROPIC_API_KEY, OIDC_* 채우기
docker compose build        # 앱 이미지 (모델은 넣지 않는다)

# 검색 모델(임베딩 BGE-M3, 리랭커)을 모델 볼륨에 받는다. 한 번만, 약 6GB
docker compose run --rm -e HF_HUB_OFFLINE=0 app python -m rag_service.deploy download-models

docker compose up -d        # db → migrate → app 순서로 시작
docker compose ps           # app이 healthy가 될 때까지 1~3분 (모델 읽는 중)
curl localhost:8000/ready   # {"ready": true, ...}

# 문서 수집 (CORPUS_DIR 폴더가 컨테이너의 /data/corpus로 보인다)
docker compose run --rm app python -m rag_service.ingest /data/corpus
curl localhost:8000/health  # index.documents, last_synced_at, mismatches 확인
```

질문은 `POST /ask`에 `Authorization: Bearer <회사 로그인 토큰>`을 붙여 보낸다 (README "질문 API").

## 정기 작업
서버의 cron(Windows는 작업 스케줄러)에 등록한다. `deploy` 폴더에서 실행한다.

```cron
# 매일 02:00 문서 증분 수집 (바뀐 문서만 다시 임베딩). 원문에서 지운 문서까지 정리하려면 --prune
0 2 * * *  cd /opt/rag/deploy && docker compose run --rm app python -m rag_service.ingest /data/corpus
# 매일 03:00 감사 기록 보관 기간 정리 (AUDIT_RETENTION_DAYS를 정한 경우만 지운다). 소유자 계정으로
0 3 * * *  cd /opt/rag/deploy && docker compose run --rm migrate python -m rag_service.audit purge
# 매주 월요일 원문과 인덱스 점검 (문제가 있으면 종료 코드 1 → 경보에 연결)
0 7 * * 1  cd /opt/rag/deploy && docker compose run --rm app python -m rag_service.ingest check /data/corpus
```

## 업데이트와 백업

```bash
# 백업 (매일 권장, 결과 파일은 다른 저장소로 옮긴다)
docker compose exec db pg_dump -U rag_owner -Fc rag > rag-$(date +%F).dump

# 업데이트: 백업 → 새 코드 받기 → 이미지 빌드 → 재시작 (migrate가 스키마를 올린다)
git pull && docker compose build && docker compose up -d

# 복구 (서비스를 멈추고)
docker compose stop app
docker compose exec -T db pg_restore -U rag_owner -d rag --clean --if-exists < rag-2026-11-11.dump
docker compose start app
```
마이그레이션은 앞으로만 올린다. 되돌려야 하면 백업으로 복구한다 (downgrade는 데이터를 지울 수 있다).

## 로그인
- **회사 로그인 시스템이 있으면**(Microsoft 365, Google Workspace, 사내 SSO): 그 시스템에 이 앱을 등록하고
  `.env`의 `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_LOGIN_CLAIM`을 채운다. `users.login`(문서 폴더의
  `org.yaml` id)이 토큰의 그 값(보통 메일 주소)과 같아야 한다.
- **없으면 Keycloak**을 함께 띄운다. 아래는 샘플 직원이 미리 들어 있는 데모 설정이다.

### Keycloak 데모

```bash
# .env: OIDC_ISSUER=http://keycloak:8080/realms/hanbit, OIDC_AUDIENCE=rag-service,
#       OIDC_LOGIN_CLAIM=preferred_username, OIDC_ALLOW_HTTP_HOSTS=keycloak, KEYCLOAK_ADMIN_PASSWORD=...
docker compose --profile keycloak up -d

# kim(개발팀 사원)으로 토큰 받기 (데모 비밀번호: demo-<아이디>)
TOKEN=$(curl -s -d client_id=rag-service -d grant_type=password -d username=kim -d password=demo-kim \
  http://localhost:8080/realms/hanbit/protocol/openid-connect/token | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -N -X POST localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @question.json   # {"question": "출장비 정산은 언제까지 해야 해?"} (UTF-8 파일)
```

- realm 파일: `deploy/keycloak/hanbit-realm.json` (`samples/org.yaml`의 kim, lee, park, choi, jung, han).
  관리 화면은 `http://localhost:8080/admin` (admin / `KEYCLOAK_ADMIN_PASSWORD`).
- **데모 전용인 부분**: 비밀번호 `demo-<아이디>`, 아이디·비밀번호로 바로 토큰을 받는 방식(password grant),
  http 통신(`OIDC_ALLOW_HTTP_HOSTS=keycloak`), `start-dev` 모드(내장 DB). 운영에서는 Keycloak을 HTTPS
  주소와 별도 DB로 띄우고(`start`), 웹 화면은 브라우저 로그인(authorization code + PKCE)을 쓴다.

## 폐쇄망 (인터넷이 막힌 서버)
1. 인터넷이 되는 PC에서 같은 이미지를 빌드하고 모델을 받는다.
   `docker save rag-service:latest pgvector/pgvector:pg17 -o images.tar`
   모델 볼륨은 `docker run --rm -v rag-service_models:/m -v $PWD:/out alpine tar czf /out/models.tgz -C /m .`
2. 서버에서 `docker load -i images.tar`, 모델 볼륨을 만들고 `models.tgz`를 풀어 넣는다.
3. 앱은 `HF_HUB_OFFLINE=1`(기본값)로 인터넷 없이 모델을 읽는다.

**남는 외부 통신은 Claude API(답변 생성)뿐이다.** 질문할 때 근거 문서 조각이 Anthropic으로 전송되므로
회사 보안 정책의 허용이 필요하다. 완전 폐쇄망이면 답변 LLM을 사내 모델로 바꿔야 한다 (로드맵 6-4).

## 규모가 커지면
| | 이 compose | 바꿀 것 |
|---|---|---|
| DB | 같은 서버의 컨테이너 | 관리형 Postgres(예: AWS RDS, Azure Database) + pgvector, 자동 백업 |
| 비밀 | `.env` 파일 | Vault, 클라우드 비밀 저장소, Kubernetes Secret |
| 앱 | 컨테이너 1개(워커 1) | 컨테이너 여러 개 + 부하 분산. 동시 요청 한도는 컨테이너마다 센다 |
| 수집 | cron + `compose run` | 작업 큐(로드맵 7단계), Kubernetes CronJob |
| 배포 | compose | Kubernetes. 이미지와 환경 변수는 그대로 쓰고 `migrate`는 Job, `/ready`는 readiness probe로 |
