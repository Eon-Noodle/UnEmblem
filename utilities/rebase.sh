#!/usr/bin/env bash
set -euo pipefail

git fetch --no-tags origin
git checkout base
git cherry-pick --empty=drop -m 1 "$(git rev-parse synced)"..origin/master
git tag -f synced origin/master

mapfile -t BRANCHES < <(git for-each-ref --format='%(refname:short)' 'refs/heads/engine-hack/*')

for b in "${BRANCHES[@]}"; do
    git checkout "$b"
    git rebase base
done

git checkout -B master base

for b in "${BRANCHES[@]}"; do
    git merge --no-ff "$b" -m "Merge $b into master"
done

for b in "${BRANCHES[@]}"; do
    name=${b#engine-hack/}
    git diff --binary base "$b" > "engine_hacks/$name.patch"
done
