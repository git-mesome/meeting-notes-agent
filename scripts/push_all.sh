#!/usr/bin/env bash
# 코드와 회사 폴더를 각자의 GitHub 저장소에 올리고, 둘을 합쳐 GitLab에 올린다. GitLab은 받으면 테스트하고 main이면 배포한다.
#
#   GitHub(공개)    ← 이 저장소의 브랜치(인자, 없으면 지금 브랜치)
#   GitHub(비공개)  ← 회사 폴더 저장소($COMPANY_DIR)의 main
#   GitLab          ← 둘을 합친 커밋. 회사 폴더는 company/ 아래에 들어간다.
#
# 합치기는 .git/gitlab-mirror.git(따로 둔 bare 저장소)에서만 하므로 이 저장소에는 회사 파일이 들어오지 않는다.
# GitLab에서 직접 고치거나 머지하지 않는다. 다음에 올릴 때 이 저장소의 내용으로 덮인다.
#
# 공개 저장소에 올리기 전에 아직 안 올린 커밋을 회사 폴더의 scan-patterns.txt로 검사하고, 하나라도 걸리면 멈춘다.
# 처음 한 번: git config meeting-notes.gitlab <GitLab 저장소 SSH 주소>
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
branch=${1:-$(git branch --show-current)}
gitlab=$(git config meeting-notes.gitlab) || { echo "git config meeting-notes.gitlab <주소>로 GitLab 저장소를 먼저 정해 주세요." >&2; exit 1; }
company_dir=${COMPANY_DIR:-$(sed -n 's/^COMPANY_DIR=//p' .env 2>/dev/null)}
[ -d "$company_dir/.git" ] || { echo "회사 폴더 저장소를 찾을 수 없어요: '$company_dir' (.env의 COMPANY_DIR)" >&2; exit 1; }

for repo in . "$company_dir"; do
  [ -z "$(git -C "$repo" status --porcelain)" ] || echo "알림: $repo에 커밋하지 않은 변경이 있어요. 커밋한 것만 올라가요." >&2
done

# 1. 공개 저장소: 아직 안 올린 커밋에 사내 정보가 없을 때만 올린다. 작성자 줄은 검사하지 않는다.
patterns=$(grep -vE '^\s*(#|$)' "$company_dir/scan-patterns.txt")
if git rev-parse -q --verify "origin/$branch" >/dev/null; then range="origin/$branch..$branch"; else range=$branch; fi
hits=$(git log -p --format='%s%n%b' "$range" | grep -inE -f <(printf '%s\n' "$patterns") || true)
if [ -n "$hits" ]; then
  echo "사내 정보로 보이는 줄이 있어 올리지 않았어요($range):" >&2
  echo "$hits" | head -20 >&2
  exit 1
fi
git push -u origin "$branch"

# 2. 회사 폴더 저장소(비공개)
git -C "$company_dir" push origin main

# 3. GitLab: 코드 트리에 회사 폴더를 company/로 얹은 커밋을 만들어 GitLab 브랜치 위에 쌓는다.
#    원래 커밋을 부모로 이어 두어 GitLab에서도 양쪽 이력이 보인다.
mirror="$(git rev-parse --absolute-git-dir)/gitlab-mirror.git"
[ -d "$mirror" ] || git init -q --bare "$mirror"
g() { git --git-dir="$mirror" "$@"; }
g fetch -q "$PWD" "+refs/heads/$branch:refs/code/$branch"
g fetch -q "$company_dir" "+refs/heads/main:refs/company/main"
g update-ref -d "refs/gitlab/$branch" 2>/dev/null || true
if git ls-remote --exit-code --heads "$gitlab" "$branch" >/dev/null 2>&1; then
  g fetch -q "$gitlab" "+refs/heads/$branch:refs/gitlab/$branch"
fi
code=$(g rev-parse "refs/code/$branch")
company=$(g rev-parse refs/company/main)
prev=$(g rev-parse -q --verify "refs/gitlab/$branch" || true)

tree=$({
  g ls-tree "$code" | awk -F'\t' '$2 != "company"'
  printf '040000 tree %s\tcompany\n' "$(g rev-parse "$company^{tree}")"
} | g mktree)
if [ -n "$prev" ] && [ "$(g rev-parse "$prev^{tree}")" = "$tree" ]; then
  echo "GitLab $branch은 이미 최신이에요."
  exit 0
fi

is_new() { [ -z "$prev" ] || ! g merge-base --is-ancestor "$1" "$prev"; }
parents=()
[ -n "$prev" ] && parents+=(-p "$prev")
title=""
if is_new "$code"; then
  parents+=(-p "$code")
  title=$(g log -1 --format=%s "$code")
fi
if is_new "$company"; then
  parents+=(-p "$company")
  [ -n "$title" ] || title="회사 폴더: $(g log -1 --format=%s "$company")"
fi
message=$(printf '%s\n\n코드 %s, 회사 폴더 %s' "${title:-코드와 회사 폴더 합침}" "$(g rev-parse --short "$code")" "$(g rev-parse --short "$company")")
commit=$(g commit-tree "$tree" "${parents[@]}" -m "$message")
g push -q "$gitlab" "$commit:refs/heads/$branch"
echo "GitLab $branch에 올렸어요: $(g log -1 --format='%h %s' "$commit")"
