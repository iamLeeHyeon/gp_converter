# Stripe 결제 설계 스펙

**날짜:** 2026-07-02
**연관:** Phase 3 후보 C (`docs/session-summary-2026-07-01.md`)

---

## 목표

Free/Pro 요금제를 도입해 사용량을 제한하고, Stripe로 Pro 구독 결제를 받는다.

| 항목 | 결정 |
|------|------|
| Free 플랜 | 월 3회 성공 변환, 저장 5개 |
| Pro 플랜 | $4.99/월, 무제한 |
| 변환 카운트 기준 | 성공한 변환만. 실패/재시도는 카운트 안 함 |
| 리셋 주기 | 가입일 기준 30일 롤링 (달력월 아님) — "최근 30일 내 성공 변환 수"로 매번 계산, 별도 카운터 컬럼 불필요 |
| 저장 5개 | 시간 무관, 유저가 보유한 File 행 개수 총량. 삭제하면 슬롯 회수됨 |
| 구독 해지/카드변경 | Stripe Customer Portal로 위임 (자체 UI 안 만듦) |
| 결제 UI | Stripe Checkout 호스티드 페이지로 리다이렉트 (임베디드 폼 안 만듦 — PCI 부담 없음, 스타일링 최소화 방침과도 부합) |

---

## 데이터 모델

`User`에 컬럼 1개 추가 (기존 `plan` 컬럼은 이미 있음, free/pro):

```python
stripe_customer_id = Column(String, nullable=True, unique=True, index=True)
```

구독 ID는 별도 저장하지 않는다 — Customer Portal은 `customer_id`만 있으면 되고, plan 상태는 webhook 이벤트가 올 때마다 최신값으로 갱신하면 되므로 별도 추적 불필요.

### 마이그레이션

공유 링크 기능(`docs/superpowers/specs/2026-07-01-shared-link-design.md`)에서 확립한 패턴 그대로: `app/database.py`의 `run_sqlite_migrations(engine)`에 `stripe_customer_id` 컬럼 추가 분기를 덧붙인다. `ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR` + `CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id ...`을 컬럼 존재 여부와 무관하게 매번 무조건 실행(멱등)하는 방식 — 이전 기능에서 "인덱스 생성이 컬럼-존재 체크 안에 갇혀서 부분마이그레이션 상태를 못 잡는" 버그를 이미 겪었으므로 처음부터 무조건 실행 형태로 만든다.

---

## 백엔드 API (`app/routers/billing.py`, 신규)

| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `POST /billing/checkout` | 필요 | Stripe Customer 없으면 생성(`stripe_customer_id` 저장) → Checkout Session 생성(price=`STRIPE_PRICE_ID_PRO`, mode=subscription) → `{url}` 반환 |
| `POST /billing/portal` | 필요 | `stripe_customer_id` 없으면 400. 있으면 Billing Portal Session 생성 → `{url}` 반환 |
| `POST /billing/webhook` | **불필요 (Stripe 서명 검증)** | `Stripe-Signature` 헤더 + `STRIPE_WEBHOOK_SECRET`으로 `stripe.Webhook.construct_event` 검증. 서명 불일치 시 400 |
| `GET /billing/usage` | 필요 | `{plan, conversions_used, conversions_limit, files_used, files_limit}` |

### 웹훅 이벤트 처리

- `checkout.session.completed` — `session.customer`로 유저 조회(이미 `stripe_customer_id`로 매칭됨) → `plan="pro"`
- `customer.subscription.updated` — `subscription.status`가 `active`/`trialing`이면 `plan="pro"`, 그 외(`canceled`/`unpaid`/`past_due` 등)면 `plan="free"`
- `customer.subscription.deleted` — `plan="free"`

`invoice.payment_failed` 등 결제 실패 세부 이벤트는 v1 범위 제외(YAGNI) — Stripe가 재시도 끝에 구독을 취소하면 `customer.subscription.deleted`가 와서 자동으로 `free`로 떨어진다.

### 사용량 제한 적용

- `GET /billing/usage`: `conversions_used` = 로그인 유저의 `File` 중 `gp5_path`가 비어있지 않고(`!= ""`) `created_at >= now - 30days`인 행 개수. `files_used` = 해당 유저의 `File` 행 총개수(성공 여부 무관).

  **사전 조건(버그 수정 포함)**: 현재 `app/main.py`의 `/convert`는 로그인 유저용 `File` 행을 변환 시작 시점에 `gp5_path=""`로 미리 만들어두고, 변환이 실제로 끝나도 이 값을 채워주는 코드가 어디에도 없다(`app/worker.py`의 `process_job`은 인메모리 `JobStore`만 갱신하고 DB `File` 행은 건드리지 않음). 즉 "성공한 변환"을 판별할 방법이 현재 코드베이스에 없다 — 이 스펙의 사용량 카운트가 정상 동작하려면 `process_job`이 변환 성공 시 해당 `File.gp5_path`를 실제 결과 경로로 갱신하도록 먼저 고쳐야 한다(플랜 Task 1). 결제 기능과 별개의 기존 버그지만, 이 기능이 의존하므로 최소 범위로 함께 고친다.
- `POST /convert` (`app/main.py`, 기존): 로그인 유저이고 `plan=="free"`이면, 작업 시작 전에 위와 동일한 방식으로 최근 30일 성공 변환 수를 세고 3 이상이면 402 `"무료 플랜 월 변환 한도(3회)를 초과했습니다"` 반환. 파일 저장 5개 제한도 같은 자리에서 체크(File 카운트 ≥5 → 402).
- Pro 유저는 무제한이라 위 체크를 건너뜀.

---

## 프론트엔드

### 사용량/업그레이드 UI

`App.tsx` 사이드바에 "요금제" 섹션 추가(신규 컴포넌트 `BillingPanel.tsx`):

- 마운트 시 `GET /billing/usage` 조회
- Free 유저: `현재 플랜: Free`, `변환 X/3`, `저장 Y/5`, "Pro로 업그레이드" 버튼 → `POST /billing/checkout` → 응답 `url`로 `window.location.href` 리다이렉트
- Pro 유저: `현재 플랜: Pro`, `무제한`, "구독 관리" 버튼 → `POST /billing/portal` → 응답 `url`로 리다이렉트

### 제한 초과 시 에러 표시

`POST /convert` 호출부(`UploadButton.tsx` 등, 기존 파일)에서 402 응답을 받으면 기존 에러 표시 경로에 그대로 태우되, 메시지에 업그레이드 유도 문구 포함(백엔드가 이미 한국어 안내 메시지를 detail로 보냄).

스타일링은 기존 컴포넌트들과 동일하게 최소 인라인 스타일만 사용.

---

## 환경변수

| 변수 | 설명 |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe API 시크릿 키 (서버) |
| `STRIPE_WEBHOOK_SECRET` | 웹훅 서명 검증용 시크릿 |
| `STRIPE_PRICE_ID_PRO` | Pro 플랜 Price ID ($4.99/월 구독) |

Stripe 계정이 아직 없으므로, 이번 구현에서는 이 값들을 환경변수로만 참조하고 실제 발급은 나중에 사용자가 직접 한다. 테스트는 전부 `stripe` SDK를 mock하므로 실제 키 없이도 통과해야 한다.

---

## 테스트 전략

- 백엔드 (pytest): `stripe.Customer.create`/`stripe.checkout.Session.create`/`stripe.billing_portal.Session.create`/`stripe.Webhook.construct_event`를 전부 mock. 웹훅 서명 불일치 → 400, 각 이벤트 타입별 plan 전이, `/convert` 제한 경계값(2/3/4회, 4/5/6개) 테스트
- 프론트 (vitest): `BillingPanel` 사용량 표시, 업그레이드/관리 버튼 클릭 시 리다이렉트, 402 에러 메시지 노출
- 기존 테스트 전체 회귀 없이 통과 유지

---

## 알려진 한계

- 비로그인(익명) 변환은 원래부터 `File`/`DbJob`에 `user_id`가 안 붙어 저장도 안 되고 이력도 안 남는 기존 동작 그대로임 — 따라서 이번 사용량 제한도 익명 변환에는 적용되지 않는다(로그인 안 하면 무제한이지만 결과가 저장 안 됨). 새로 생긴 우회로가 아니라 기존 아키텍처의 연장.

## 범위 제외 (YAGNI)

- 연간 결제 플랜, 쿠폰/프로모션 코드
- `invoice.payment_failed` 세부 처리(결제 실패 이메일 알림 등)
- 여러 등급의 유료 플랜 (Pro 하나만)
- 사용량 대시보드의 과거 이력/그래프
