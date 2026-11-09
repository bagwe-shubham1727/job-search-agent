#!/usr/bin/env bash
# Builds the JS2 course folder and the Canvas zip from the committed HEAD (nothing uncommitted).
# It refuses while the sign-off is unsigned. It does not commit, push or upload anything.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
course_repo="$repo/../info-7375-prompt-engineering-for-generative-ai"
folder="$course_repo/fall-2026/shubham-b/js2-loop-tools-diff"
zip_path="$repo/../Bagwe_Shubham_INFO7375_JS2.zip"

cd "$repo"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing: commit or discard local changes first" >&2; exit 1
fi
if grep -q "Signed or withheld: ____" README.md || grep -q "\[Shubham" README.md FRICTIONAL.md; then
  echo "refusing: README.md or FRICTIONAL.md still has [Shubham ...] placeholders or an unsigned sign-off" >&2
  exit 1
fi

commit="$(git rev-parse HEAD)"
rm -rf "$folder"
mkdir -p "$folder"
git archive HEAD | tar -x -C "$folder"
rm -f "$zip_path"
(cd "$folder/.." && zip -qr "$zip_path" "$(basename "$folder")")

echo "folder: $folder"
echo "zip:    $zip_path"
echo "commit: $commit"
echo "Next, by hand: cd \"$course_repo\" && git add fall-2026/shubham-b/js2-loop-tools-diff && git commit && git push"
