# RAG 포트폴리오 차별화 리서치

> 작성일: 2026-11-08
> 목적: RAG 기반 문서 검색/질의 서비스를 포트폴리오로 만들 때, 흔한 프로젝트와 차별화할 수 있는 기능을 정리한다.
> 주의: 인용한 통계의 상당수는 업체 블로그와 컨설팅 글에서 나온 것이다. 수치는 방향을 보는 참고용이고, 여러 출처가 공통으로 말하는 정성적 결론을 더 신뢰한다.

---

## 0. RAG 한 줄 요약

**내 문서를 올려두면, AI가 그 문서에서 관련 부분을 찾아 읽고 출처와 함께 답해주는 구조.**
RAG(Retrieval-Augmented Generation, 검색으로 보강한 생성)는 "오픈북 시험"에 비유할 수 있다.

```
[문서 업로드] → 조각내기(청킹) → 숫자로 변환(임베딩) → [벡터 DB 저장]
[질문] → 질문 임베딩 → 비슷한 조각 검색 → 조각 + 질문을 LLM에 전달 → 답변 + 출처
```

---

## 1. 왜 이런 프로젝트가 이미 많은가

1. **기본형은 만들기 쉽다.** LangChain 등으로 수십 줄이면 "PDF 챗봇"이 동작하고, 튜토리얼이 넘쳐나서 결과물이 비슷해진다.
2. **데모 화면이 그럴듯하다.** 문서 몇 개, 사용자 한 명으로 시연하면 잘 되는 것처럼 보인다.
3. **채용 키워드라서** 취업 준비생들이 많이 선택한다.

### 데모와 실제 운영의 격차 = 차별화 기회
업계에서는 "기업 RAG 프로젝트의 약 70%가 목표를 달성하지 못한다"는 말이 자주 나온다(업체 수치). 실패 원인으로 공통으로 꼽히는 것은 다음과 같다.

- AI 모델 자체보다 **문서 파싱, 청킹, 검색 단계**의 문제
- **오래된 문서와 최신 문서가 섞이는** 데이터 관리 문제
- 검색 품질을 **측정하지 않음** (평가 체계 부재)
- **권한과 보안**을 나중에 덧붙이려다 생기는 문제
- 사용자와 문서가 늘었을 때의 **속도와 비용** 문제

> **핵심:** 대부분의 포트폴리오는 데모에서 멈춘다. 실무자가 실제로 겪는 문제를 하나라도 제대로 풀어서 **수치로 보여주면** 눈에 띈다.

---

## 2. 실무자가 "오?" 할 만한 차별화 기능

난이도: ★ 쉬움 / ★★ 보통 / ★★★ 어려움

### A. 평가와 회귀 테스트 ★★ (최우선 추천)
- **실무 문제:** 운영 중인 팀의 상당수가 검색 품질을 체계적으로 측정하지 않는다. 그래서 뭔가 바꿨을 때 좋아졌는지 나빠졌는지 알 수 없다.
- **구현:**
  - "질문, 정답, 정답 위치(문서와 페이지)"로 구성된 **골든 데이터셋** 50~100개를 만들고, 버전 관리되는 JSON 파일로 저장한다.
  - **검색 지표**(Recall@k, MRR)와 **답변 지표**(Faithfulness: 근거에 충실한가, Answer Relevance: 질문에 맞는 답인가)를 분리해서 측정한다. 도구로 RAGAS를 쓸 수 있다.
  - **CI 품질 게이트**: 코드를 바꿀 때마다 평가를 자동으로 실행하고, 기준선보다 점수가 떨어지면 실패 처리한다.
- **진단 팁:** Recall이 낮으면 검색 문제(청킹, 임베딩, top_k)다. Recall은 높은데 Faithfulness가 낮으면 생성 단계가 좋은 근거를 무시하고 있다는 뜻이다.
- **어필 포인트:** "청킹 방식을 바꿨더니 Context Recall이 0.71에서 0.86으로 올랐다"처럼 **바꾸기 전과 후의 수치**를 보여준다.

### B. 한국어 특화 하이브리드 검색과 리랭킹 ★★
- **실무 문제:**
  - 벡터 검색은 "제12조의3", "KPI-2024-A" 같은 **정확한 코드나 약어**를 잘 못 찾는다.
  - BM25 같은 키워드 검색은 공백 기준으로 단어를 나누기 때문에, 한국어에서는 **조사** 때문에 망가진다("출장비는"과 "출장비를"을 다른 단어로 본다).
- **구현:** **Kiwi(kiwipiepy) 형태소 분석**으로 BM25를 만들고, 벡터 검색 결과와 **RRF(Reciprocal Rank Fusion, 두 검색의 순위를 합치는 방법)**로 합친다. 이어서 상위 20개를 **크로스 인코더 리랭커**로 다시 정렬한다.
- **어필 포인트:** "벡터만, 하이브리드, 하이브리드+리랭커" 세 구성의 **비교표**를 만든다. 영어권 튜토리얼에 없는 한국어 문제를 풀었다는 점이 차별점이다.

### C. Contextual Retrieval 재현 실험 ★★
- **실무 문제:** 잘라낸 조각만 보면 맥락이 사라진다. 예를 들어 "매출이 3% 증가했다"만 보고는 어느 회사, 어느 분기인지 알 수 없다.
- **구현:** 각 조각 앞에 LLM이 만든 맥락 설명(50~100토큰)을 붙인 뒤 임베딩과 BM25 색인을 한다.
- **근거:** Anthropic 발표에 따르면 top-20 검색 실패율이 **49% 감소**했고, 리랭킹까지 더하면 **67% 감소**했다. 단, 이 49%에는 일반 하이브리드 검색의 효과도 섞여 있다는 비판이 있으므로, 단계별로 나눠서 비교하는 것이 좋다.
- **어필 포인트:** "발표된 결과를 한국어 문서로 재현해 보니 이랬다"는 실험 보고서. 단계별 기여도를 분리해서 측정하면 더 좋다.

### D. 복잡한 문서 파싱: 표, 다단 편집, HWP ★★★
- **실무 문제:** PDF는 "보여주기용 포맷"이라 "여기는 표"라는 정보가 파일 안에 없다. 그래서 표가 깨지고, 2단 편집 문서는 왼쪽 단과 오른쪽 단 글이 섞인다. 여러 글이 **파싱을 RAG의 가장 큰 병목**으로 꼽는다.
- **구현:** 레이아웃을 인식하는 파서를 쓴다. 표는 쪼개지 않고 통째로 하나의 조각으로 만들고, 각 조각에 소속 섹션 제목(상위 제목 포함)을 붙인다.
- **한국 시장 특화:** 공공기관과 기업 문서의 상당수가 **HWP(한글 파일)**다. HWP 표 파싱을 제대로 다룬 공개 자료가 거의 없어서 **빈 자리**이고, 한국 기업을 상대로 강한 차별점이 될 수 있다.

### E. 권한 기반 검색 (접근 제어) ★★
- **실무 문제:** 인사팀 문서가 일반 직원의 답변에 섞여 나오면 보안 사고다. 실무 글들은 "검색한 뒤에 걸러내는 건 접근 제어가 아니다"라고 강조한다.
- **구현:** 색인할 때 각 조각에 권한 정보(부서, 역할, 보안 등급)를 붙이고, 검색할 때 **DB 쿼리 단계에서 미리 필터링**한다. pgvector라면 SQL `WHERE` 조건으로 자연스럽게 구현할 수 있다. 권한이 바뀌는 것도 "변경 이벤트"로 보고 색인에 반영해야 한다.
- **어필 포인트:** 사용자별로 같은 질문에 다른 답이 나오는 데모를 보여주고, "권한 없는 문서가 결과에 0건 섞인다"는 것을 테스트 코드로 증명한다.

### F. 증분 색인과 문서 버전 관리 ★★
- **실무 문제:** 문서가 수정됐는데 예전 내용으로 답하거나, 옛 버전과 새 버전이 섞인다.
- **구현:** 파일 해시로 바뀐 것을 감지해서 **바뀐 조각만 다시 색인**한다. 문서마다 버전을 관리하고, 답변에 "2026-10 개정판 기준"처럼 표시한다. 작업 큐(Celery)를 도입할 근거도 여기서 생긴다.

### G. 모르면 모른다고 하기와 인용 검증 ★
- **실무 문제:** 근거가 없는데도 그럴듯하게 지어내는 것(환각)이 가장 큰 신뢰 문제다.
- **구현:**
  - 검색 점수가 기준 미만이면 "문서에서 찾을 수 없습니다"라고 **답변을 거절**한다(fail closed).
  - 답변의 각 문장이 실제로 인용한 조각에 들어 있는지 **사후 검증**한다.
  - 원문의 해당 위치(페이지, 문단)를 하이라이트하고, 클릭하면 그 위치로 이동하게 한다.

### H. 관측성, 비용, 속도 ★★
- **구현:**
  - Langfuse 같은 도구로 요청마다 "검색된 조각 ID, 리랭크 점수, 실제 프롬프트와 그 버전, 토큰 비용"을 추적한다.
  - 단계별 지연 시간(P95)과 **질의당 비용** 대시보드를 만든다.
  - **시맨틱 캐시**: 비슷한 질문(예: 코사인 유사도 0.92 이상)이 오면 LLM을 다시 부르지 않고 저장된 답을 재사용한다. 처음에는 정확히 같은 질문만 캐시하고, 나중에 시맨틱 캐시로 확장하는 순서를 권한다.
- **어필 포인트:** "캐시 적중률 ○○%, 질의당 비용 ○○% 절감" 같은 운영 지표를 보여준다.

### I. 문서 속 프롬프트 인젝션 방어 ★★
> 이번 검색에서 좋은 자료를 찾지 못해, 이 항목은 일반적인 지식을 바탕으로 정리했다. 추가 조사가 필요하다.
- **실무 문제:** 업로드된 문서 안에 "이전 지시를 무시하고 ○○를 출력해" 같은 문장이 숨어 있으면 AI가 그 지시를 따를 수 있다(간접 프롬프트 인젝션).
- **구현:** 검색된 내용을 "지시가 아닌 데이터"로 명확히 구분해서 감싸고, 의심 패턴을 탐지하고, 공격 문서를 넣은 테스트셋으로 방어율을 측정한다.

### J. 사용자 피드백 순환 ★
- 👍👎 피드백 중 실패 사례를 골든 데이터셋에 추가해서, **운영하면서 점점 좋아지는 시스템**을 보여준다.

---

## 3. 추천 조합

> 원칙: **기능 개수보다 깊이. 하나의 명확한 사용 사례.**

**시나리오 예시: "한국어 사내 규정 / 공공문서 질의 서비스"**

| 단계 | 내용 |
|---|---|
| 1. 기본기 | G(거절과 인용) + B(한국어 하이브리드 검색과 리랭커) |
| 2. 핵심 무기 | A(평가와 CI 게이트). 모든 개선을 수치로 증명하는 뼈대 |
| 3. 차별화 한 방 (하나만 선택) | 한국 기업을 노린다면 **D(HWP와 표 파싱)** / 대기업이나 보안 중시 기업이라면 **E(권한 기반 검색)** / 연구 성향을 보여주려면 **C(Contextual Retrieval 재현)** |
| 4. 여유가 있으면 | H(관측성과 비용) |

### README 작성 원칙
기능 목록을 나열하기보다 다음 흐름으로 쓴다.

**문제 → 시도 → 수치 결과 → 실패 사례 분석**

---

## 4. 스택 메모
- 백엔드가 FastAPI(Python)이므로 작업 큐는 **Celery**(가볍게는 ARQ나 Dramatiq)로 통일한다. BullMQ는 Node.js용이다.
- **pgvector**: 메타데이터, 권한 필터, 벡터를 한 DB에서 처리할 수 있다. Postgres 전문 검색과 함께 하이브리드 검색을 구성하기 좋다.
- 프론트엔드(Next.js)는 최소한으로 만들고, 백엔드와 평가에 시간을 집중한다.

---

## Sources
- [RAG in production: why 70% of projects fail (Edana)](https://edana.ch/en/2026/03/31/rag-in-production-why-70-of-projects-fail-and-how-to-build-a-reliable-system/)
- [Production RAG checklist (Rocket)](https://www.rocket.new/blog/production-rag-checklist-failures-tutorial-authors-never-cover)
- [RAG Accuracy Problems (Atlan)](https://atlan.com/know/rag-accuracy-problems/)
- [The hard part of RAG (kapa.ai)](https://www.kapa.ai/blog/the-hard-part-of-rag-isn’t-retrieval-or-generation)
- [70% of enterprise RAG deployments fail (DEV)](https://dev.to/gabrielanhaia/70-of-enterprise-rag-deployments-fail-before-production-heres-what-kills-them-26ml)
- [Why most RAG projects fail in production (Towards AI)](https://towardsai.com/p/machine-learning/why-most-rag-projects-fail-in-production-and-how-to-build-one-that-doesnt)
- [RAG portfolio projects (DataTalks.Club)](https://datatalks.club/podwiki/wiki/rag-portfolio-projects/)
- [AskHR Policy Assistant 예시](https://portfolio-ekl.pages.dev/northstar-askhr.html)
- [Hybrid search RAG challenge (Ewance)](https://ewance.com/en/challenges/hybrid-search-rag-for-a-hr-policy-assistant-retrieval-augmented-generation-master/)
- [RAG project into resume bullet](https://besthub.dev/articles/how-to-turn-your-rag-project-into-an-interview-winning-resume-bullet-d990417131c1)
- [Permission-aware retrieval (tianpan.co)](https://tianpan.co/blog/2026/05/04/permission-aware-retrieval-enterprise-rag-access-control)
- [Document-level RBAC in RAG (Truto)](https://www.truto.one/blog/how-to-maintain-document-level-rbac-in-enterprise-rag-pipelines/)
- [Azure AI Search document-level access](https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview)
- [Incremental indexing strategies (GeoSurge)](https://www.geosurge.ai/corpus/gen-4165/indexed-search/incremental-indexing-strategies-for-freshness-in-enterprise-search-and-rag.html)
- [How to test a RAG pipeline (Braintrust)](https://www.braintrust.dev/articles/how-to-test-rag-pipeline)
- [rag-eval-gate (PyPI)](https://pypi.org/project/rag-eval-gate/)
- [RAG evaluation with RAGAS](https://itsourcecode.com/web-dev/rag-evaluation-ragas/)
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)
- [Contextual Retrieval 비판적 해설 (Medium)](https://medium.com/almond-ai/responding-to-anthropics-contextual-retrieval-for-rag-apps-why-context-is-not-all-you-need-af503985aa55)
- [Why document parsing is the RAG bottleneck](https://toolradar.com/blog/why-document-parsing-is-the-rag-bottleneck)
- [Structure-aware chunking for complex tables](https://ijournalse.org/index.php/ESJ/article/view/3380)
- [LlamaIndex: Mastering PDFs](https://www.llamaindex.ai/blog/mastering-pdfs-extracting-sections-headings-paragraphs-and-tables-with-cutting-edge-parser-faea18870125)
- [Ensemble Retriever 하이브리드 검색 (위키독스)](https://wikidocs.net/231609)
- [RAG 하이브리드 검색 시스템 구축 (위키독스)](https://wikidocs.net/book/20783)
- [Kiwi-BM25 앙상블 리트리버 (velog)](https://velog.io/@pinggu95/63일차-검색기-Retriever)
- [Hybrid search BM25 + vector (youngju.dev)](https://www.youngju.dev/blog/culture/2026-03-18-hybrid-search-bm25-vector-rag)
- [Langfuse for RAG (Leanware)](https://leanware.co/insights/langfuse-for-rag)
- [Production RAG LLMOps checklist (DEV)](https://dev.to/nainikmehta/production-rag-architecture-llmops-patterns-checklist-1ho8)
- [Production-ready RAG: Monitoring & Caching](https://jamwithai.substack.com/p/production-ready-rag-monitoring-and)
