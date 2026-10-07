# SIG Cup autonomous worker

This branch contains a single-process Python competition trader under `sig_cup/`.
The repository's existing coursework remains on its original branch.

The worker scans executable quotes, verifies mutually exclusive Party Winner
contracts against resolution metadata, sizes equal-quantity NO baskets, and
records order identities before submission. It reconciles fills, cash and
holdings, cancels unfilled remainders, and pauses after partial exposure or an
accounting disagreement. Poll observations are retained as research; directional
polling trades remain disabled pending calibration.

## Deployment

Apply the root `render.yaml` from branch `sig-cup-trader` in the intended Render
workspace. It specifies one Ohio background worker, 512 MB RAM, and a 1 GB disk.
Compute costs $7/month and disk costs $0.25/month before usage overages, according
to Render's October 2026 pricing. Set the existing participant credential as
`SIG_API_KEY` and the intended account UUID as `SIG_EXPECTED_PROFILE_ID` using
Render's secret environment variables. Neither belongs in this repository.

The service starts with `SIG_LIVE=false`. Set `SIG_STATE_BOOTSTRAP_B64` to the
base64-encoded private state backup at first startup. The importer validates the
participant identity and database integrity, atomically installs the three order
journal databases, and never overwrites existing cloud journals on restart. The
snapshot and its contents must never be committed. Verify successful authenticated
scans before activation.
Only one live process should operate the participant account. A confirmed live
activation uses `SIG_LIVE=true`; each basket is capped at 1,000 virtual SUSQies,
each race at 12,000, daily entry spending at 30,000, and total unsettled cost at
65% of marked equity. A 20% cash reserve and drawdown stop also apply. These are
implementation limits, not evidence of optimal performance.

The disk persists order journals across redeployments. `STOP` in the state
directory pauses entries. SIGTERM stops gracefully. An ambiguous placement
retains its original request identity; do not replace the journals or restart
from an empty directory to clear an execution problem.

New entries stop at November 4, 2026, 17:00 UTC. Suspend the service afterward;
the trading cutoff does not cancel Render hosting charges.

## Verification

From `sig_cup/`, install `requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
```

The deployment runs the same checks during its build. Examples contain fictional
inputs; local tests do not prove live profitability or competition performance.
