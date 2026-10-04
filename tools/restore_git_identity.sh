#!/usr/bin/env bash
# Restore the git identity, remote and key permissions for this repository.
#
# Why this file exists: `.git/config` is excluded from the workspace snapshot (it can hold
# credentials), so in a fresh session this checkout has no committer name and no `origin`. The first
# `git commit` then fails with "Author identity unknown" and the push with "does not appear to be a
# git repository" — neither of which says anything about the real cause.
#
# Same story for the deploy key: it survives, but its mode does not, and ssh refuses a private key
# that the world can read ("Permissions 0644 ... too open"). Both are one command.
#
#   bash tools/restore_git_identity.sh          # set identity + remote, fix key mode, report
#
# Safe to run repeatedly. It never touches the working tree or the history.
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${NT90_REMOTE:-git@github.com:joshuathomas171717-cpu/90-I-.git}"
KEY="${NT90_SSH_KEY:-$HOME/.ssh/ninety_plus_deploy}"

cd "$REPO" || exit 1

# The identity comes from the history rather than from a guess, so a commit made here is attributed
# to whoever made the last one.
name="$(git log -1 --format='%an' 2>/dev/null || echo '')"
email="$(git log -1 --format='%ae' 2>/dev/null || echo '')"
[ -n "$name" ] || name="Joshua Thomas"
[ -n "$email" ] || email="joshuathomas171717-cpu@users.noreply.github.com"
git config user.name "$name"
git config user.email "$email"
printf '  identity: %s <%s>\n' "$name" "$email"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi
printf '  remote:   %s\n' "$(git remote get-url origin)"

if [ -f "$KEY" ]; then
  chmod 600 "$KEY"
  if ssh-keygen -y -f "$KEY" >/dev/null 2>&1; then
    printf '  key:      %s (mode 600, readable)\n' "$KEY"
  else
    printf '  key:      %s cannot be read — is it a valid private key?\n' "$KEY"
  fi
  # The deploy key is used explicitly, because the default ssh would offer every key in the agent
  # and GitHub rejects the wrong one rather than falling through.
  git config core.sshCommand "ssh -i $KEY -o StrictHostKeyChecking=no"
  printf '  ssh:      core.sshCommand set to use the deploy key\n'
else
  printf '  key:      %s is MISSING — pushes will fail until it is restored\n' "$KEY"
fi
