import argparse
import json
from pathlib import Path
import sys

from .api import API
from .model import fit_elections, score_forecasts
from .runtime import (Journal, analysis, collect_snapshot, execute_once, process_lock,
                      read_json, recover_pending, resolve_tournament, run_loop, write_json)
from .structural import (collect_quotes, execute_no_bundle, recover_baskets,
                         review_party_bundle, screen_party_bundles)
from .autonomous import acknowledge_partial, resume_worker, run_worker
from .primary_data import import_research, monitor_primary_sources, research_source_urls


def main():
    parser = argparse.ArgumentParser(description="SIG Predictions Cup research and scoped limit execution")
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker", help="Run the restartable full-market structural strategy")
    worker.add_argument("--config", default="config.autonomous.json")
    worker.add_argument("--work", default="work/autonomous")
    worker.add_argument("--live", action="store_true", help="Enable virtual orders; default is read-only")
    worker.add_argument("--cycles", type=int)
    resume = commands.add_parser("worker-resume", help="Clear a halt after all order journals are reconciled")
    resume.add_argument("--work", default="work/autonomous")
    disposition = commands.add_parser("basket-acknowledge", help="Record explicit operator review of residual partial exposure")
    disposition.add_argument("--config", default="config.autonomous.json")
    disposition.add_argument("--work", default="work/autonomous")
    disposition.add_argument("--key", required=True)
    disposition.add_argument("--reason", required=True)
    research = commands.add_parser("research-import", help="Normalize sourced polling observations without forecasting")
    research.add_argument("--research", default="data/polling_research.json")
    research.add_argument("--out", default="work/poll_observations.json")
    sources = commands.add_parser("source-check", help="Check a bounded batch of original polling releases")
    sources.add_argument("--research", default="data/polling_research.json")
    sources.add_argument("--out", default="work/primary_source_monitor.json")
    discover = commands.add_parser("discover", help="Verify API key and list active tournaments")
    discover.add_argument("--base", default="https://sig.thesuper.market/api/v1")
    discover.add_argument("--out", default="work/discovery.json")
    initialize = commands.add_parser("init", help="Pin an existing active tournament's identity in config")
    initialize.add_argument("--slug", required=True)
    initialize.add_argument("--out", default="config.json")
    initialize.add_argument("--template", default="config.example.json")
    snapshot = commands.add_parser("snapshot", help="Collect a read-only tournament snapshot")
    snapshot.add_argument("--config", default="config.json")
    snapshot.add_argument("--forecasts")
    snapshot.add_argument("--out", default="work/snapshot.json")
    quotes = commands.add_parser("quotes", help="Screen the entire tournament with scoped bulk executable quotes")
    quotes.add_argument("--config", default="config.json")
    quotes.add_argument("--out", default="work/structural_screen.json")
    review = commands.add_parser("basket-review", help="Review one title-screened candidate against API resolution trees")
    review.add_argument("--config", default="config.json")
    review.add_argument("--candidates", default="work/structural_screen.json")
    review.add_argument("--index", type=int, default=0)
    review.add_argument("--out", default="work/basket_review.json")
    basket = commands.add_parser("basket", help="Execute one explicitly allowlisted, reviewed NO basket")
    basket.add_argument("--config", default="config.json")
    basket.add_argument("--reviewed", default="work/basket_review.json")
    basket.add_argument("--work", default="work")
    basket.add_argument("--max-notional", type=float, default=200)
    basket.add_argument("--max-shares", type=int, default=100)
    basket_recover = commands.add_parser("basket-recover", help="Reconcile or identically retry a journalled basket")
    basket_recover.add_argument("--config", default="config.json")
    basket_recover.add_argument("--work", default="work")
    fit = commands.add_parser("fit", help="Fit the explicit polling-error model and generate joint scenarios")
    fit.add_argument("--polls", required=True)
    fit.add_argument("--mapping", required=True)
    fit.add_argument("--out", default="work/model")
    fit.add_argument("--samples", type=int, default=50000)
    fit.add_argument("--seed", type=int, default=20261007)
    fit.add_argument("--as-of", help="Explicit historical model cutoff for validation")
    score = commands.add_parser("score", help="Score time-ordered held-out historical forecasts")
    score.add_argument("--history", required=True)
    score.add_argument("--out", default="work/validation.json")
    scan = commands.add_parser("scan", help="Offline analysis of an existing snapshot and forecasts")
    scan.add_argument("--config", default="config.json")
    scan.add_argument("--snapshot", default="work/snapshot.json")
    scan.add_argument("--forecasts", default="work/model/forecasts.json")
    scan.add_argument("--scenarios", default="work/model/scenarios.npz")
    scan.add_argument("--groups")
    scan.add_argument("--out", default="work/analysis.json")
    for name in ("execute", "loop", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--config", default="config.json")
        command.add_argument("--work", default="work")
        if name != "recover":
            command.add_argument("--forecasts", default="work/model/forecasts.json")
            command.add_argument("--scenarios", default="work/model/scenarios.npz")
        if name == "loop":
            command.add_argument("--live", action="store_true", help="Submit entries; default is read-only")
            command.add_argument("--cycles", type=int)
    args = parser.parse_args()
    try:
        if args.command == "worker-resume":
            resume_worker(args.work)
            print(json.dumps({"state": "halt_cleared", "work": args.work}))
        elif args.command == "research-import":
            result = import_research(args.research, args.out)
            print(json.dumps({"observations": result["observation_count"], "validated_for_trading": False, "saved": args.out}))
        elif args.command == "source-check":
            result = monitor_primary_sources(research_source_urls(read_json(args.research)), args.out)
            print(json.dumps({"checked": len(result["last_checks"]), "saved": args.out}))
        elif args.command == "discover":
            api = API(base=args.base)
            account = api.get("/account")
            result = {"account": account, "active_tournaments": api.tournaments()}
            write_json(args.out, result)
            print(json.dumps({"saved": args.out, "active_tournaments": result["active_tournaments"]}, indent=2))
        elif args.command == "init":
            config = read_json(args.template)
            api = API(config["api_base"])
            matches = [row for row in api.tournaments() if row["slug"] == args.slug]
            if len(matches) != 1:
                raise ValueError("Exact active tournament slug was not found.")
            row = matches[0]
            if row["initialBalance"] != 100000 or "midterm" not in row["name"].lower():
                raise ValueError("This is not the expected 100,000-SUSQie Midterm tournament.")
            config.update(tournament_slug=row["slug"], tournament_id=row["id"], expected_tournament_name=row["name"], live_enabled=False)
            if Path(args.out).exists():
                raise ValueError("Output config already exists; preserve it or choose another path.")
            write_json(args.out, config)
            print(json.dumps({"saved": args.out, "tournament": row["name"], "live_enabled": False}))
        elif args.command == "fit":
            result = fit_elections(args.polls, args.mapping, args.out, args.samples, args.seed, args.as_of)
            print(json.dumps({"saved": args.out, "contracts": len(result["forecasts"]), "validated": result["validated"]}))
        elif args.command == "score":
            result = score_forecasts(args.history)
            write_json(args.out, result)
            print(json.dumps(result, indent=2))
        elif args.command == "scan":
            result = analysis(read_json(args.snapshot), read_json(args.forecasts), args.scenarios, read_json(args.config), args.groups)
            write_json(args.out, result)
            print(json.dumps(result, indent=2))
        else:
            config = read_json(args.config)
            api = API(config["api_base"])
            if args.command == "basket-acknowledge":
                result = acknowledge_partial(api, config, args.work, args.key, args.reason)
                print(json.dumps({"state": "partial_exposure_reviewed", "key": args.key, "at": result["operator_reviewed_at"]}))
            elif args.command == "worker":
                run_worker(api, config, args.work, args.live, args.cycles)
            elif args.command == "snapshot":
                forecasts = read_json(args.forecasts) if args.forecasts else None
                result = collect_snapshot(api, config, forecasts)
                write_json(args.out, result)
                print(json.dumps({"saved": args.out, "coverage": result["coverage"], "account_value": result["pnl"]["totalAccountValue"]}))
            elif args.command == "quotes":
                tournament = resolve_tournament(api, config)
                markets = api.pages(f'/tournaments/{config["tournament_slug"]}/markets', status="any", limit=100)
                quote_payload = collect_quotes(api, tournament["id"], markets)
                candidates = screen_party_bundles(markets, quote_payload)
                result = {"tournament": tournament, "markets": markets, "quotes": quote_payload,
                          "candidates": candidates,
                          "note": "Title screening is provisional. Review resolution metadata and refresh full depth before execution."}
                write_json(args.out, result)
                print(json.dumps({"saved": args.out, "quotes": len(quote_payload["data"]), "provisional_candidates": len(candidates)}))
            elif args.command == "basket-review":
                resolve_tournament(api, config)
                candidate = read_json(args.candidates)["candidates"][args.index]
                nodes = {str(l["market_id"]): api.get(f'/markets/{l["market_id"]}/nodes', tournamentId=config["tournament_id"])
                         for l in candidate["legs"]}
                result = review_party_bundle(candidate, nodes, config["tournament_id"])
                write_json(args.out, result)
                print(json.dumps({"saved": args.out, "race": result["race"], "metadata_reviewed": True}))
            elif args.command == "basket":
                with process_lock(args.work):
                    result = execute_no_bundle(api, config, read_json(args.reviewed), args.work,
                                               args.max_notional, args.max_shares)
                write_json(Path(args.work) / "last_basket_execution.json", result)
                print(json.dumps({k: v for k, v in result["reconciliation"].items() if k != "legs"}))
            elif args.command == "basket-recover":
                with process_lock(args.work):
                    result = recover_baskets(api, config, args.work)
                write_json(Path(args.work) / "basket_recovery.json", result)
                print(json.dumps({"saved": str(Path(args.work) / "basket_recovery.json"), "recovered": len(result)}))
            elif args.command == "execute":
                with process_lock(args.work):
                    result = execute_once(api, config, args.forecasts, args.scenarios, args.work)
                print(json.dumps(result, indent=2))
            elif args.command == "recover":
                with process_lock(args.work):
                    resolve_tournament(api, config)
                    journal = Journal(Path(args.work) / "operations.sqlite3")
                    try:
                        result = recover_pending(api, journal, config)
                    finally:
                        journal.close()
                write_json(Path(args.work) / "recovery.json", result)
                print(json.dumps({"saved": str(Path(args.work) / "recovery.json"), "recovered": len(result)}))
            elif args.command == "loop":
                if args.cycles is not None and args.cycles < 1:
                    raise ValueError("cycles must be positive.")
                run_loop(api, config, args.forecasts, args.scenarios, args.work, args.live, args.cycles)
        return 0
    except Exception as error:
        # Never print the credential, Authorization header or raw HTTP request.
        print(f"Stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
