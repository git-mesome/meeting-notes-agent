#!/usr/bin/env bash
# GitLab의 배포 작업(.gitlab-ci.yml)이 서버에서 root로 실행한다. 지금 받은 코드와 company/ 폴더로 앱을 바꾼다.
#
# APP_ROOT(러너 설정의 환경 변수) 아래 구조:
#   app/       지금 도는 앱. 서버의 .env가 여기 있다.
#   company/   회사 폴더. 컨테이너에 읽기 전용으로 붙는다.
#   jobs/      처리 결과. 처리 중인 회의가 있으면 끝날 때까지 기다린다.
#   *.prev/    바로 앞 버전. 새 앱이 응답하지 않으면 이걸로 되돌린다.
set -euo pipefail

: "${APP_ROOT:?러너 설정에 APP_ROOT를 넣어 주세요}"
SOURCE=$(pwd)
IMAGE=meeting-notes-agent
APP_UID=10001  # Dockerfile의 app 사용자
WAIT_SECONDS=${WAIT_SECONDS:-7200}

cd "$APP_ROOT"
port=$(sed -n 's/^PORT=//p' app/.env)
compose() { (cd app && docker compose -p app "$@"); }

# 1. 새 앱과 회사 폴더를 .next에 준비하고 이미지를 만든다. 지금 도는 앱은 아직 그대로다.
rm -rf app.next company.next
mkdir app.next
git -C "$SOURCE" archive HEAD -- . ':(exclude)company' | tar -x -C app.next
cp -p app/.env app.next/.env
docker build -t "$IMAGE:next" app.next
if [ -d "$SOURCE/company" ]; then
  rsync -a --delete --exclude .git "$SOURCE/company/" company.next/
  chown -R "$APP_UID" company.next
  chmod -R go-rwx company.next
fi

# 2. 처리 중인 회의가 끝나기를 기다린다. 처리 도중에 재시작하면 처음부터 다시 처리한다.
busy() { jq -r .status jobs/*/meta.json 2>/dev/null | grep -cE '^(transcribing|writing)$' || true; }
waited=0
while [ "$(busy)" -gt 0 ]; do
  if [ "$waited" -ge "$WAIT_SECONDS" ]; then
    echo "처리 중인 회의가 ${WAIT_SECONDS}초 넘게 끝나지 않아 배포하지 않았다. 나중에 이 작업을 다시 실행한다." >&2
    exit 1
  fi
  echo "처리 중인 회의 $(busy)건이 끝나기를 기다린다"
  sleep 30
  waited=$((waited + 30))
done

# 3. 바꿔 끼우고 다시 띄운다. 회사 폴더만 바뀌어도 새로 붙도록 컨테이너를 항상 다시 만든다.
swap() { rm -rf "$1.prev"; mv "$1" "$1.prev"; mv "$1.next" "$1"; }
restore() { rm -rf "$1.failed"; mv "$1" "$1.failed"; mv "$1.prev" "$1"; }
docker tag "$IMAGE" "$IMAGE:prev"
docker tag "$IMAGE:next" "$IMAGE"
swap app
[ -d company.next ] && swap company
compose up -d --force-recreate || echo "새 앱을 띄우지 못했다" >&2

# 4. 응답하지 않으면 앞 버전으로 되돌린다. sw.js는 로그인을 켜도 열려 있다.
for _ in $(seq 30); do
  if curl -fs -o /dev/null "http://127.0.0.1:${port:-8000}/sw.js"; then
    echo "배포했다: $(git -C "$SOURCE" log -1 --format='%h %s')"
    docker image prune -f --filter "label=app=$IMAGE" >/dev/null
    exit 0
  fi
  sleep 2
done
echo "새 앱이 1분 안에 응답하지 않아 앞 버전으로 되돌린다. 실패한 버전은 *.failed에 남긴다." >&2
compose logs --tail 50 >&2 || true
docker tag "$IMAGE:prev" "$IMAGE"
restore app
[ -d company.prev ] && [ -d "$SOURCE/company" ] && restore company
compose up -d --force-recreate
exit 1
