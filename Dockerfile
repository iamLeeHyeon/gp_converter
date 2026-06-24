# Audiveris의 Linux 릴리스가 x86_64 전용이라 이 이미지는 반드시 linux/amd64로 빌드해야 한다.
# docker build --platform linux/amd64 -t gp-converter .
FROM python:3.11-slim-bookworm

ARG AUDIVERIS_VERSION=5.10.2
ARG AUDIVERIS_DEB=Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb

# Audiveris(jpackage 앱, 자체 JRE 동봉)의 AWT/Swing 헤드리스 구동에 필요한 네이티브 라이브러리.
# (deb 패키지 control 파일의 Depends 목록과 일치)
# fontconfig+폰트: Java AWT가 심볼 폰트를 그릴 때 fontconfig를 통해 시스템 폰트를
# 찾는다. 없으면 "Fontconfig head is null" 예외로 -batch 실행 자체가 죽는다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    libasound2 libbsd0 libc6 libmd0 \
    libx11-6 libxau6 libxcb1 libxdmcp6 libxext6 libxi6 libxrender1 libxtst6 \
    xdg-utils zlib1g \
    fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Audiveris 설치 (자체 런타임 동봉이라 별도 JRE 불필요).
# slim 베이스 이미지에는 데스크톱 환경의 표준 디렉토리(/usr/share/applications,
# desktop-directories, mime/packages)가 없어 deb의 postinst가 호출하는
# xdg-desktop-menu/xdg-mime install이 둘 자리를 못 찾아 exit 3으로 실패한다 → 미리 생성.
RUN mkdir -p /usr/share/applications /usr/share/desktop-directories /usr/share/mime/packages \
    && curl -fsSL -o /tmp/audiveris.deb \
      "https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/${AUDIVERIS_DEB}" \
    && dpkg -i /tmp/audiveris.deb || apt-get install -y -f \
    && rm -f /tmp/audiveris.deb

ENV GPC_AUDIVERIS_CMD=/opt/audiveris/bin/Audiveris

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

ENV GPC_JOBS_DIR=/srv/jobs
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
