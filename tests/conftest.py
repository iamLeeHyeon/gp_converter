import os

# OAuth/JWT 관련 환경변수 — app.auth, app.routers.auth 모듈 수준 import 전에 세팅
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "gh-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "gh-secret")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("STRIPE_PRICE_ID_PRO", "price_dummy")
