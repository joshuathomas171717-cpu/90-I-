#!/usr/bin/env bash
# push.sh — publish this repository to GitHub.
#
#   ./push.sh git@github.com:YOUR-USERNAME/ninety-plus-pl-predictor.git
#   ./push.sh --check                    # just report the current state, change nothing
#   ./push.sh --https USERNAME           # use HTTPS instead of SSH
#
# Safe to re-run: it re-creates the remote, re-sets the identity, and a failed push leaves the
# commit untouched (nothing has been written anywhere but this folder).
set -euo pipefail

say() { printf '  %s\n' "$*"; }
die() { printf '\n  ✗ %s\n\n' "$*" >&2; exit 1; }

cd "$(dirname "$0")"

# ── --check: what is the state of things? ────────────────────────────────────
if [ "${1:-}" = "--check" ]; then
  echo "repo:      $(pwd)"
  echo "branch:    $(git branch --show-current 2>/dev/null || echo '(not a git repo)')"
  echo "commits:   $(git rev-list --count HEAD 2>/dev/null || echo 0)"
  echo "files:     $(git ls-files | wc -l)"
  echo "remote:    $(git remote get-url origin 2>/dev/null || echo '(none set)')"
  echo "identity:  $(git log -1 --format='%an <%ae>' 2>/dev/null || echo '(no commits)')"
  echo "working:   $(git status --porcelain | wc -l) uncommitted change(s)"
  exit 0
fi

REMOTE_URL="${1:-}"
[ -n "$REMOTE_URL" ] || die "usage: ./push.sh git@github.com:USER/ninety-plus-pl-predictor.git"

case "$REMOTE_URL" in
  --https)
    USERNAME="${2:-}"
    [ -n "$USERNAME" ] || die "usage: ./push.sh --https USERNAME"
    REMOTE_URL="https://github.com/$USERNAME/ninety-plus-pl-predictor.git"
    ;;
esac

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository — run this from the extracted project folder"

# ── identity, scoped to this repository only ─────────────────────────────────
# A commit needs an author. This sets it locally (never --global) so nothing on your machine changes.
git config user.name  >/dev/null 2>&1 || git config user.name  "NINETY+"
git config user.email >/dev/null 2>&1 || git config user.email "ninety-plus@users.noreply.github.com"
say "author: $(git config user.name) <$(git config user.email)>   (change: git config user.email 'you@example.com')"

# ── nothing uncommitted left behind ─────────────────────────────────────────
if [ -n "$(git status --porcelain)" ]; then
  say "uncommitted changes found — committing them first"
  git add -A
  git commit -q -m "chore: local changes before push"
fi

# ── does the repository exist, and can we reach it? ──────────────────────────
say "checking $REMOTE_URL"
if ! git ls-remote "$REMOTE_URL" >/dev/null 2>&1; then
  cat <<MSG

  ✗ Could not read that repository. The usual causes, in order:

      1. The repository does not exist yet.
         Create it: github.com → New repository → name it "ninety-plus-pl-predictor",
         and do NOT let GitHub add a README, .gitignore or licence (this project has all three,
         and adding them creates a merge conflict on the first push).

      2. The URL is wrong. SSH form is  git@github.com:USER/REPO.git
                          HTTPS form is  https://github.com/USER/REPO.git

      3. You have not authorised this machine yet:
           SSH key  → repo → Settings → Deploy keys → Add deploy key → paste the public key,
                      and TICK "Allow write access".
           HTTPS    → you will be prompted for a username and a Personal Access Token.

MSG
  exit 1
fi

# ── push ─────────────────────────────────────────────────────────────────────
git remote remove origin >/dev/null 2>&1 || true
git remote add origin "$REMOTE_URL"
say "pushing main → origin"
if git push -u origin main; then
  echo
  say "✓ pushed. $(git rev-list --count HEAD) commit(s), $(git ls-files | wc -l) files."
  say "  view it: $(echo "$REMOTE_URL" | sed -E 's#git@github.com:#https://github.com/#; s#\.git$##')"
  echo
  cat <<'NEXT'
  Next, if you want it live (both optional):
    * Settings → Pages → Source: "GitHub Actions"      → a public URL for the dashboard
    * Settings → Secrets and variables → Actions       → FOOTBALL_DATA_ORG_TOKEN, NT90_ALERT_WEBHOOK
  Then check the Actions tab: CI runs the whole pipeline on that first push.

  Security note: if you added a deploy key, delete it now (repo → Settings → Deploy keys → Remove).
  The push is done; the key has no further purpose.
NEXT
else
  die "push failed — nothing was changed on GitHub, and the local commit is untouched"
fi
