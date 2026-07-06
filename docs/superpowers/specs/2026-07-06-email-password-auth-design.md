# 자체 가입(이메일+비밀번호) 인증 설계 스펙

**날짜:** 2026-07-06
**연관:** 기존 Google/GitHub OAuth 로그인(완료됨)과 별개로, 이메일/비밀번호로 직접 가입할 수 있는 경로를 추가한다. OAuth를 실제로 연결하는 작업(Google/GitHub 앱 등록)은 별도 작업으로 분리.

---

## 목표

`app/routers/auth.py`의 기존 Google/GitHub OAuth 로그인과 공존하는, 이메일+비밀번호 기반 자체 가입/로그인/이메일인증/비밀번호 재설정 기능을 추가한다.

| 항목 | 결정 |
|------|------|
| 이메일 발송 | SMTP(Gmail 등) — Celery task로 비동기 발송(요청 블로킹 없음) |
| 비밀번호 재설정 | 이번 스펙에 포함 |
| 미인증 계정 제한 | 로그인은 허용, `/convert`(PDF 변환)만 차단 |
| 레이트리밋 | Redis 기반 직접 구현(IP당 시간당 20회), register/login/forgot-password/resend-verification 4개 엔드포인트 |
| 인증메일 재발송 | 포함 |
| OAuth-자체가입 이메일 충돌 | 자체가입 쪽만 명확한 에러 처리. 기존 OAuth 콜백의 동일 갭은 이번 스펙 범위 밖(선재 이슈, 안 건드림) |

---

## 데이터 모델 변경

`app/models.py`의 `User`에 컬럼 추가(SQLite `ALTER TABLE ADD COLUMN` 마이그레이션 가드, 기존 컨벤션 그대로):

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `password_hash` | String, nullable | OAuth 계정은 `NULL`. bcrypt 해시 |
| `email_verified` | Boolean, NOT NULL | 마이그레이션 시 기존 행(전부 OAuth로 생성됨) 전부 `True`로 백필. 신규 자체가입 행만 앱 코드에서 명시적으로 `False`로 삽입 |
| `verification_token` | String, nullable, indexed | 이메일 인증 링크용 1회성 토큰 |
| `verification_token_expires_at` | DateTime, nullable | 발급 후 24시간 |
| `reset_token` | String, nullable, indexed | 비밀번호 재설정 링크용 1회성 토큰 |
| `reset_token_expires_at` | DateTime, nullable | 발급 후 1시간 |

`provider`/`provider_id`는 기존 NOT NULL 그대로 유지(nullable로 바꾸는 건 SQLite에서 테이블 재생성급 작업이라 손대지 않음). 자체가입 계정은 `provider="password"`, `provider_id=email`로 채워 제약조건만 만족시키고 실질적 조회에는 안 쓴다(OAuth 조회는 `provider+provider_id` 조합으로만 하므로 충돌 없음).

**같은 이메일 충돌**: `email` 컬럼은 기존에 이미 `unique=True`다. 자체가입 시 이미 존재하는 이메일이면(어느 provider든) 400 에러 — provider가 `google`/`github`면 "이미 Google/GitHub로 가입된 이메일입니다"로 구분해서 안내. 기존 OAuth 콜백 쪽(반대 방향: OAuth 로그인 시 이미 password 계정으로 등록된 이메일이면 DB unique 제약 위반으로 크래시)은 이번 스펙에서 고치지 않는다 — 이미 있던 갭이고 범위 밖.

---

## API

### 회원가입 + 이메일 인증

**`POST /auth/register`** `{email, password, name?}`
- 이메일 형식, 비밀번호 최소 8자 검증
- 이메일 중복 체크(위 설명대로 provider별 에러 메시지 구분)
- `User(provider="password", provider_id=email, password_hash=bcrypt(password), email_verified=False, verification_token=secrets.token_urlsafe(32), verification_token_expires_at=now+24h)` 생성
- 가입 즉시 access/refresh JWT 발급(OAuth 콜백과 동일한 로그인 처리 — "로그인 허용, 기능만 제한" 정책)
- Celery task `send_verification_email_task(user_id)` 디스패치
- 레이트리밋: IP당 시간당 20회

**`GET /auth/verify?token=...`**
- 토큰으로 `User` 조회. 없거나 만료면 `{FRONTEND_URL}/login?verify=expired`로 리다이렉트
- 유효하면 `email_verified=True`, `verification_token`/`expires_at`을 `None`으로 비우고 `{FRONTEND_URL}/login?verify=success`로 리다이렉트

**`POST /auth/resend-verification`** `{email}`
- 계정이 있고 `provider="password"`이며 아직 미인증이면 새 토큰 발급 + `send_verification_email_task` 재디스패치
- 계정이 없거나 이미 인증됐거나 OAuth 계정이어도 **항상 동일한 200 메시지** 반환(계정 존재 여부 유추 방지)
- 레이트리밋: IP당 시간당 20회

### 로그인

**`POST /auth/login`** `{email, password}`
- `provider="password"` 유저 조회 + `bcrypt.checkpw` 검증
- 실패(계정 없음/비번 틀림 둘 다) → 401 "이메일 또는 비밀번호가 올바르지 않습니다"(계정 존재 여부 노출 안 함)
- 성공 시 OAuth와 동일하게 access/refresh JWT 발급
- 레이트리밋: IP당 시간당 20회

**`GET /auth/me`** (신규, JWT 필요)
- `{email, plan, email_verified}` 반환. 프론트가 로그인 직후/이메일인증 리다이렉트 복귀 시 호출해서 인증상태 갱신(현재 JWT 페이로드엔 `sub`만 있어서 이 정보를 알 방법이 없었음)

### 비밀번호 재설정

**`POST /auth/forgot-password`** `{email}`
- `provider="password"` 유저 있으면 `reset_token`/`reset_token_expires_at`(+1시간) 채우고 `send_reset_email_task(user_id)` 디스패치
- 계정 없거나 OAuth 계정이어도 **항상 동일한 200 메시지**(계정 존재 여부 유추 방지)
- 레이트리밋: IP당 시간당 20회

**`POST /auth/reset-password`** `{token, new_password}`
- 토큰 조회, 없거나 만료면 400
- 유효하면 `password_hash` 재해시, `reset_token`/`expires_at` 비움
- 기존 발급된 JWT는 재설정 후에도 자연 만료 전까지 유효(JWT가 stateless라 즉시 무효화 안 함 — 범위 밖)

### `/convert` 제한

- 기존 익명(로그인 없이) 변환 동작은 그대로 유지, 이번 스펙과 무관
- JWT가 있는데 그 유저 `email_verified=False`면 403 "이메일 인증 후 이용 가능합니다"

---

## 이메일 발송

**환경변수(신규):** `SMTP_HOST`, `SMTP_PORT`(기본 587), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS`(기본 true)

**`app/email.py`(신규):** `smtplib`+`email.mime`로 직접 발송(추가 라이브러리 없음). `send_email(to: str, subject: str, html_body: str) -> None` 함수 하나.

**`app/tasks.py`에 task 2개 추가:**
- `send_verification_email_task(user_id)` — 워커가 `user_id`로 유저 재조회(기존 `process_job_task`와 동일 컨벤션), `{BACKEND_URL}/auth/verify?token=...` 링크 담은 한글 메일 발송
- `send_reset_email_task(user_id)` — `{FRONTEND_URL}/reset-password?token=...` 링크 담은 메일 발송

테스트: `smtplib.SMTP`는 mock, Celery `.delay()`도 기존 컨벤션대로 mock — 실제 SMTP 서버/네트워크 없이 전체 스위트 통과.

---

## 레이트리밋

새 패키지 추가 없이 기존 Redis 인프라 재사용. `app/rate_limit.py`(신규): FastAPI dependency 함수 하나 — 요청 IP + 엔드포인트명으로 Redis 키를 만들어 `INCR` 후 `EXPIRE 3600`(최초 요청 시에만), 카운트가 20 초과면 429 "너무 많은 요청입니다. 잠시 후 다시 시도하세요." 4개 엔드포인트(`register`/`login`/`forgot-password`/`resend-verification`)에 동일하게 적용.

---

## 프론트엔드

**`LoginPage.tsx`**: 기존 Google/GitHub 버튼 아래에 이메일/비밀번호 입력 + 로그인 버튼, "회원가입"/"비밀번호를 잊으셨나요?" 링크 추가. URL의 `?verify=success|expired` 쿼리파라미터 보고 배너 표시.

**새 라우트 3개** (`App.tsx`):
- `/register` — `RegisterPage`(이메일/비밀번호/비밀번호확인 폼) → 성공 시 토큰 저장 + `/`로 이동 + "인증메일을 확인해주세요" 안내, "인증메일 다시 받기" 링크(resend-verification 호출)
- `/forgot-password` — `ForgotPasswordPage`(이메일 입력 → 발송 요청, 결과와 무관하게 동일 안내문구)
- `/reset-password` — `ResetPasswordPage`(URL의 `token` + 새 비밀번호 입력 → 백엔드 POST)

**`authStore.ts`**: `emailVerified`/`plan` 상태 + `fetchMe()` 액션 추가 — 로그인 직후, 앱 시작 시 토큰 있으면, 이메일인증 리다이렉트 복귀 시 호출.

**`MainPage`**: `token && !emailVerified`일 때 배너("이메일 인증이 필요합니다 — 메일함을 확인하세요" + "다시 받기" 버튼) 추가. `/convert` 403 에러 메시지는 그대로 화면에 노출(기존 에러 표시 패턴 재사용).

기존 컴포넌트 컨벤션대로 전부 최소 인라인 스타일만(디자인은 사용자가 나중에 직접 — 프로젝트 기존 컨벤션).

---

## 파일 계획

| 파일 | 변경 |
|------|------|
| `requirements.txt` (수정) | `bcrypt` 추가(비밀번호 해싱) |
| `app/models.py` (수정) | `User`에 컬럼 6개 추가 |
| `app/database.py` (수정) | `run_sqlite_migrations`에 위 컬럼들 ADD COLUMN 가드 추가 |
| `app/email.py` (신규) | `send_email()` — smtplib 기반 SMTP 발송 |
| `app/rate_limit.py` (신규) | Redis 기반 레이트리밋 dependency |
| `app/routers/auth.py` (수정) | `register`/`verify`/`resend-verification`/`login`/`me`/`forgot-password`/`reset-password` 7개 엔드포인트 추가 |
| `app/tasks.py` (수정) | `send_verification_email_task`/`send_reset_email_task` 추가 |
| `app/main.py` (수정) | `/convert` 라우터에 `email_verified` 체크 추가 |
| `README.md` (수정) | 신규 환경변수(`SMTP_*`) 문서화 |
| `frontend/src/components/Auth/LoginPage.tsx` (수정) | 이메일/비번 폼 + 링크 추가 |
| `frontend/src/components/Auth/RegisterPage.tsx` (신규) | 회원가입 폼 |
| `frontend/src/components/Auth/ForgotPasswordPage.tsx` (신규) | 비번찾기 요청 폼 |
| `frontend/src/components/Auth/ResetPasswordPage.tsx` (신규) | 비번 재설정 폼 |
| `frontend/src/store/authStore.ts` (수정) | `emailVerified`/`plan` 상태 + `fetchMe()` |
| `frontend/src/App.tsx` (수정) | 라우트 3개 추가, `MainPage`에 미인증 배너 |

---

## 알려진 한계 / 범위 제외 (YAGNI)

- OAuth 콜백 쪽의 이메일 충돌 갭(반대 방향)은 안 고침 — 선재 이슈
- 계정 연결(OAuth 계정에 비밀번호 추가 등) 없음
- 비밀번호 재설정 후 기존 JWT 즉시 무효화 안 함(자연 만료까지 유효)
- 비밀번호 정책은 최소 8자만, 복잡도 규칙 없음
- 레이트리밋은 IP 기준 단순 카운터(프록시/CDN 뒤에서 IP가 뭉치는 경우 등 정교한 처리 없음)
