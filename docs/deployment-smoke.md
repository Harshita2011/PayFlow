# Post-deployment smoke checklist

Public deployment has not been performed. Execute this checklist only after approval and on the actual authorized demo URLs. Use disposable fictional accounts, keep every balance simulated, and record step outcomes without credentials or sensitive screenshots. Local `tools/deployment_smoke.py` deliberately refuses public targets and validates only the separate Compose project.

- [ ] HTTPS frontend loads and displays fictional-money labels; browser has no mixed-content errors.
- [ ] Live and ready probes return 200; PostgreSQL is persistent, encrypted and at the approved Alembic revision.
- [ ] Exact production CORS origin works; an unrelated origin is rejected. Documentation/metrics follow the intended access policy.
- [ ] Register and log in as two new fictional users. Configure strong payment PINs with their current account passwords.
- [ ] Create demo accounts and a second owned account; inspect masked identifiers and primary selection.
- [ ] Add funds within the existing three-action allowance. Adding an account must not reset that allowance.
- [ ] Resolve the other user's exact UPI ID and review a transfer. Verify missing PIN authorization and unauthorized account access are rejected.
- [ ] Confirm one simulated transfer; record its receipt ID privately, verify both balances and participant history.
- [ ] Retry the original key/payload and recover the same receipt without a second movement. Never invent a new key for an unknown outcome.
- [ ] Display/upload a PayFlow QR, verify the backend-resolved recipient and explicitly confirm before any payment.
- [ ] Create/pay a money request, decline/cancel another pending request, and verify only participants have access.
- [ ] Create an equal/custom expense split, check rounding, pay contributions and verify one settled obligation/receipt per share.
- [ ] Transfer between two owned accounts and verify total user funds are conserved.
- [ ] Recharge a fictional mobile plan and pay a synthetic utility bill at server-authoritative prices; replay without double posting.
- [ ] Inspect receipts/history and verify no real service activation is implied.
- [ ] Verify PIN error/lockout, limits and fraud warnings; do not intentionally spam other users or disable security controls.
- [ ] Confirm the separate worker delivers participant activity; delayed delivery must not change financial success.
- [ ] Check redacted logs, correlation IDs, private metrics, queue age/dead letters and worker process health.
- [ ] Run operator reconciliation and preserve the result. Do not repair mismatches by changing balances.
- [ ] Verify logout, expired-session handling, mobile layouts and uncertain-outcome recovery.
- [ ] Document actual URLs, environment/revision, timestamp and any failures. Never describe unexecuted checks as passed.

For the locally verified Compose stack, run `python tools/deployment_smoke.py` from the repository root after startup. It creates only new synthetic data in `payflow_demo`, exercises the principal payment workflows and checks database privileges/reconciliation. See [deployment](deployment.md) for scope and [backup/recovery](backup-recovery.md) before any restore.
