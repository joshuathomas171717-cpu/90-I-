# Every finished wave is a GitHub and website release

Standing owner instruction, 6 October 2026: **commit, push and update the website after every wave.
Only a security risk is a reason to hold publication; explain the hold, fix the risk and rerun the checks.**
Do not treat pushing source code as proof that the website changed.

## Release checklist

1. Update the execution plan and tracker before starting the next wave. Keep missing-data acceptance
   checks open; a working fallback is not a successful accuracy measurement.
2. Rebuild and test: `python3 run_all.py`. This also runs the credential publication guard. Run browser
   checks after UI/scenario changes, including desktop/mobile layout, saved/shared round-trips and XSS.
3. Inspect the candidate: no real API key, private key, credential file, credentialed URL or raw secret
   belongs in source, a generated page, a public artifact or the downloadable ZIP. Keep `LICENSE`
   unchanged. The static site still has no database, accounts, ads or paid API requirement.
4. Restore git identity/modes if a workspace snapshot was restored, stage, then check the actual index:
   ```bash
   bash tools/restore_git_identity.sh
   git add -A
   python3 tools/publication_gate.py --staged
   git diff --cached --check
   ```
5. Commit and push. Vercel's GitHub integration publishes the committed `static/` tree. Local tests and
   the security guard must have passed **before** pushing; GitHub CI is an additional verification.
6. Wait for deployment and inspect production:
   ```bash
   python3 tools/verify_deployment.py --retries 6 --wait 30
   python3 check_live.py --url https://90plus-cyan.vercel.app/
   ```
   Compare the generated pages/report bytes for the new feature too. The verifier compares matchweek,
   results date, season, player-context hash and squad/digest UI hash. A matching results date alone
   cannot prove a context-only change landed. Check the actual GitHub CI result and leave a clean tree.
7. Rebuild `ninety-plus-pl-predictor.zip` from tracked files only. Test a clean extraction with keys,
   git metadata, raw caches and model artifacts absent. Present the main result and report the commit
   plus the actual live URL, not an unverified deployment promise.

## What the security guard covers

`tools/publication_gate.py` is stdlib-only, offline, and redacts matched values. It detects credential
files/private keys, common GitHub/AWS token formats, long literal football/API credential assignments,
Bearer strings and credentialed URLs. JSON strings are inspected after decoding too. It is **not a
complete DLP scan, penetration test or security certification**; schema checks, HTML-script-safe JSON,
DOM escaping, bounded profile validation and browser XSS probes are separate controls.

CI and the weekly job gate artifact uploads as well as publication. The weekly refresh checks staged
bytes before commit/push; raw/staging audit artifacts get a credential check before upload. A guard
failure must not result in publishing the unsafe page as a convenient debugging artifact.

If a real secret is found: hold commit/push/deploy, remove it from the candidate, ask the owner to
rotate/revoke it if it was exposed, and rerun. Never copy the value into logs or a status message. If
it is already public, removing the current file is not enough to make that credential safe.

## Data gaps are not a publication excuse

No key, missing international coverage, unavailable per-match trends and a closed player-model gate
are normal states. Publish their visible labels and keep the existing automatic forecasts unchanged.
User-selected What-If hypotheses are explicit input assumptions, not a claimed accuracy improvement.
Installing a schedule does not prove the first real refresh ran; P12.1 remains open until that dispatch
is actually verified. GitHub Pages errors are separate from the Vercel production deployment.
