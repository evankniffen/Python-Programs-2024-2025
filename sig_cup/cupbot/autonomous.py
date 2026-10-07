"""A single-instance, restartable competition worker.

The live strategy is limited to metadata-verified mutually exclusive Party
Winner NO baskets. Polling observations do not authorize directional entries.
"""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import threading
import urllib.error
import uuid

from .api import APIError
from .model import parse_time, utc_now
from .runtime import Journal, process_lock, read_json, recover_pending, resolve_tournament, write_json
from .structural import (BasketJournal, collect_quotes, execute_no_bundle, plan_no_bundle,
                         recover_baskets, review_party_bundle, screen_party_bundles, reconcile_basket)


class EntryBlocked(ValueError):
    """A known entry gate; no order was submitted."""


def validate_worker_config(config):
    from .runtime import validate_config
    validate_config(config)
    if not config.get("trading_deadline_utc"):
        raise ValueError("Pin trading_deadline_utc before running an autonomous worker.")
    parse_time(config["trading_deadline_utc"])
    uuid.UUID(config["expected_profile_id"])
    for key, default in (("worker_max_basket_notional", 1000), ("worker_max_shares", 5000),
                         ("worker_max_reviews_per_cycle", 6), ("worker_catalog_refresh_seconds", 600),
                         ("worker_node_cache_seconds", 300), ("worker_error_limit", 3)):
        value = float(config.get(key, default))
        if not math.isfinite(value) or value < 1:
            raise ValueError(f"Invalid {key}.")
    if config.get("worker_max_basket_notional", 1000) > config["max_order_notional"]:
        raise ValueError("Worker basket size exceeds the hard order-notional cap.")
    if not 0 < float(config.get("worker_max_drawdown_fraction", .2)) < 1:
        raise ValueError("Invalid drawdown fraction.")
    if not 0 < float(config.get("structural_min_edge", .02)) < 1:
        raise ValueError("Invalid structural minimum edge.")
    if not 0 <= float(config.get("structural_min_return", .005)) < 1:
        raise ValueError("Invalid structural minimum return.")
    for key in ("autonomous_live_enabled", "structural_live_enabled", "verify_account_after_trade"):
        if not isinstance(config.get(key), bool):
            raise ValueError(f"{key} must be an explicit boolean.")
    if not config["verify_account_after_trade"]:
        raise ValueError("Autonomous operation requires post-trade account verification.")
    if not config.get("structural_depth_enabled"):
        raise ValueError("Autonomous operation requires depth-aware sizing.")


def verify_state_disk(work_dir):
    """Refuse live Render operation if the state directory is ephemeral."""
    if os.environ.get("RENDER", "").lower() != "true":
        return
    mount = Path("/var/data")
    destination = Path(work_dir).resolve()
    if not os.path.ismount(mount) or not destination.is_relative_to(mount):
        raise RuntimeError("Render must attach /var/data as a persistent disk for the order journal.")
    if os.environ.get("RENDER_INSTANCE_ID") is None:
        raise RuntimeError("Render runtime identity is missing.")


class WorkerState:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, allow_nan=False)))
        self.db.commit()

    def event(self, kind, payload):
        self.db.execute("INSERT INTO events(at,kind,payload) VALUES (?,?,?)",
                        (utc_now(), kind, json.dumps(payload, allow_nan=False)))
        self.db.execute("DELETE FROM events WHERE id < (SELECT MAX(id)-5000 FROM events)")
        self.db.commit()

    def close(self):
        self.db.close()


def race_key(reviewed):
    identity = reviewed["race_identity"]
    return (identity["raceId"], identity["stageId"], identity["electionDate"])


def read_portfolio(api, config, tournament=None):
    tournament = tournament or resolve_tournament(api, config)
    slug, tid = config["tournament_slug"], config["tournament_id"]
    positions = api.get(f"/tournaments/{slug}/portfolio/positions")["positions"]
    pnl = api.get(f"/tournaments/{slug}/portfolio/pnl", period="all")
    orders = api.pages("/orders", status="open", tournamentId=tid, limit=200)
    if any(str(row["tournamentId"]) != tid for row in orders):
        raise ValueError("Open-order read mixed tournament scopes.")
    collateral = api.get("/portfolio/collateral", tournamentId=tid)["data"]
    if any(str(row["tournamentId"]) != tid for row in collateral):
        raise ValueError("Collateral read mixed tournament scopes.")
    active = [p for p in positions if not p["settled"] and float(p["quantity"])]
    for p in active:
        if not math.isfinite(float(p["quantity"])) or not math.isfinite(float(p["costBasis"])):
            raise ValueError("Invalid live position quantity or cost basis.")
    cash, equity = float(tournament["myBalance"]), float(pnl["totalAccountValue"])
    if not math.isfinite(cash) or cash < 0 or not math.isfinite(equity) or equity <= 0:
        raise ValueError("Invalid cash or equity.")
    return {"cash": cash, "equity": equity, "positions": active, "open_orders": orders,
            "collateral": collateral, "captured_at": utc_now(),
            "cost_at_risk": sum(max(0, float(p["costBasis"])) for p in active)}


class AutonomousWorker:
    def __init__(self, api, config, work_dir, live=False, stop_event=None):
        validate_worker_config(config)
        if live and not (config["autonomous_live_enabled"] and config["structural_live_enabled"]):
            raise ValueError("Both autonomous and structural live switches must be enabled.")
        if live:
            verify_state_disk(work_dir)
        self.api, self.config = api, dict(config)
        self.work = Path(work_dir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.live = live
        self.stop_event = stop_event or threading.Event()
        self.state = WorkerState(self.work / "worker.sqlite3")
        identity = {k: config[k] for k in ("api_base", "tournament_id", "tournament_slug", "expected_tournament_name")}
        previous = self.state.get("identity")
        if previous is not None and previous != identity:
            self.state.close()
            raise ValueError("This state directory belongs to another account routing context.")
        self.state.put("identity", identity)
        self.config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        self.catalog, self.catalog_time = None, None
        self.node_cache = {}
        self.account_verified = False
        self.cycles = 0
        self.transient_errors = 0

    def close(self):
        self.state.close()

    def stopped(self):
        return self.stop_event.is_set() or (self.work / "STOP").exists()

    def halted(self):
        return self.state.get("halt") is not None or (self.work / "HALT.json").exists()

    def latch_halt(self, reason):
        payload = {"at": utc_now(), "reason": reason,
                   "resume": "Review the account and journals, then use worker-resume. Restarting does not clear this halt."}
        self.state.put("halt", payload)
        self.state.event("halt", payload)
        write_json(self.work / "HALT.json", payload)

    def unresolved(self):
        baskets = BasketJournal(self.work / "basket_operations.sqlite3")
        singles = Journal(self.work / "operations.sqlite3")
        try:
            return baskets.unresolved(), singles.has_unreconciled()
        finally:
            baskets.close()
            singles.close()

    def recover(self):
        baskets, single_pending = self.unresolved()
        if not baskets and not single_pending:
            return []
        if not self.live:
            raise EntryBlocked("Read-only mode found unresolved orders; it will not replay or cancel them.")
        if single_pending:
            if self.stopped() or self.halted():
                raise EntryBlocked("Single-order recovery is pending while trading is paused.")
            journal = Journal(self.work / "operations.sqlite3")
            try:
                recover_pending(self.api, journal, self.config)
            finally:
                journal.close()
        recovered = recover_baskets(self.api, self.config, self.work,
                                    allow_replay=not self.stopped() and not self.halted()) if baskets else []
        for row in recovered:
            if not row["balanced_full_fill"] and any(row["quantities_filled"]):
                self.latch_halt("A recovered basket has partial fills. Its remaining orders were cancelled.")
        self.state.event("recovery", {"basket_count": len(recovered), "single_order_recovery": single_pending})
        return recovered

    def verify_account(self):
        if not self.account_verified:
            account = self.api.get("/account")
            if str(account["id"]) != self.config["expected_profile_id"]:
                raise ValueError("The API key belongs to another participant account.")
            previous = self.state.get("profile_id")
            if previous is not None and previous != str(account["id"]):
                raise ValueError("The order journal belongs to another participant account.")
            self.state.put("profile_id", str(account["id"]))
            self.account_verified = True

    def node(self, market_id):
        now = datetime.now(timezone.utc)
        cached = self.node_cache.get(str(market_id))
        if cached and (now - cached[0]).total_seconds() < self.config.get("worker_node_cache_seconds", 300):
            return cached[1]
        data = self.api.get(f"/markets/{market_id}/nodes", tournamentId=self.config["tournament_id"])
        self.node_cache[str(market_id)] = (now, data)
        return data

    def markets(self):
        now = datetime.now(timezone.utc)
        if (self.catalog is None or
                (now - self.catalog_time).total_seconds() >= self.config.get("worker_catalog_refresh_seconds", 600)):
            self.catalog = self.api.pages(f'/tournaments/{self.config["tournament_slug"]}/markets', status="any", limit=100)
            self.catalog_time = now
        return self.catalog

    def review(self, candidate):
        ids = [str(leg["market_id"]) for leg in candidate["legs"]]
        with ThreadPoolExecutor(max_workers=4) as pool:
            nodes = dict(zip(ids, pool.map(self.node, ids)))
        return review_party_bundle(candidate, nodes, self.config["tournament_id"])

    def race_exchanges(self, reviewed, portfolio):
        """Include all existing holdings in this race, even across overlapping subsets."""
        ids = {str(leg["exchange_id"]) for leg in reviewed["legs"]}
        wanted = race_key(reviewed)
        for p in portfolio["positions"]:
            eid = str(p["exchangeId"])
            if eid in ids:
                continue
            mid = p.get("marketId")
            if mid is None:
                matches = [m for m in self.markets() if any(str(e["id"]) == eid for e in m["exchanges"])]
                if len(matches) != 1:
                    raise ValueError("An existing holding cannot be mapped to its race metadata.")
                mid = matches[0]["id"]
            tree = self.node(mid)
            if not any(c["type"] == "tournament" and str(c["tournament"]["id"]) == self.config["tournament_id"]
                       for c in tree["contexts"]):
                raise ValueError("A held market has no matching tournament context.")
            details = tree["root"].get("contract_details") or {}
            actual = tuple(str(details.get(k) or "") for k in ("raceId", "stageId", "electionDate"))
            if actual == wanted:
                ids.add(eid)
        return ids

    def capacity(self, reviewed, portfolio, race_ids):
        selected = {str(leg["exchange_id"]) for leg in reviewed["legs"]}
        if any(str(p["exchangeId"]) in selected and float(p["quantity"]) > 0 for p in portfolio["positions"]):
            raise EntryBlocked("Opposite holdings would net a basket leg.")
        race_cost = sum(max(0, float(p["costBasis"])) for p in portfolio["positions"] if str(p["exchangeId"]) in race_ids)
        baskets = BasketJournal(self.work / "basket_operations.sqlite3")
        singles = Journal(self.work / "operations.sqlite3")
        try:
            count, used = baskets.daily_notional()
            extra_count, extra_used = singles.daily_usage(self.config["tournament_id"])
        finally:
            baskets.close()
            singles.close()
        if count + extra_count >= self.config["max_orders_per_day"]:
            raise EntryBlocked("Daily submission cap reached.")
        budget = min(self.config.get("worker_max_basket_notional", 1000),
                     self.config["daily_entry_notional_cap"] - used - extra_used,
                     self.config["structural_max_race_notional"] - race_cost,
                     portfolio["equity"] * self.config["max_total_at_risk"] - portfolio["cost_at_risk"],
                     portfolio["cash"] - portfolio["equity"] * self.config["cash_reserve_fraction"])
        if budget <= 0:
            raise EntryBlocked("No cash or risk capacity remains.")
        return budget

    def update_research(self):
        from .primary_data import import_research, monitor_primary_sources, research_source_urls
        relative = self.config.get("worker_research_path")
        if not relative:
            return {"state": "not_configured", "directional_trading_enabled": False}
        path = Path(relative)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        if not path.is_file():
            return {"state": "missing", "directional_trading_enabled": False}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.state.get("research_sha256") != digest:
            result = import_research(path, self.work / "poll_observations.json")
            self.state.put("research_sha256", digest)
            self.state.put("research_observation_count", result["observation_count"])
        summary = {"state": "observations_only", "research_sha256": digest,
                   "observation_count": self.state.get("research_observation_count"), "directional_trading_enabled": False}
        if self.config.get("worker_source_monitor_enabled", False):
            previous = self.state.get("source_monitor_at")
            now = datetime.now(timezone.utc)
            if previous is None or (now - parse_time(previous)).total_seconds() >= self.config.get("worker_source_check_interval_seconds", 21600):
                urls = research_source_urls(read_json(path)) + self.config.get("worker_source_index_urls", [])
                result = monitor_primary_sources(urls, self.work / "primary_source_monitor.json")
                self.state.put("source_monitor_at", result["checked_at"])
                summary["source_checks"] = [{"url": row["url"], "status": row["status"]} for row in result["last_checks"]]
        return summary

    def tick(self):
        self.verify_account()
        recovered = self.recover()
        if self.halted():
            return {"state": "halted", "halt": self.state.get("halt"), "placed": False}
        if self.stopped():
            return {"state": "paused", "placed": False}
        tournament = resolve_tournament(self.api, self.config)
        cutoff = min(parse_time(tournament["endDate"]), parse_time(self.config["trading_deadline_utc"]))
        now = datetime.now(timezone.utc)
        if now >= cutoff or tournament["status"] != "active":
            return {"state": "finished", "placed": False, "cutoff": cutoff.isoformat()}
        if tournament.get("startDate") and now < parse_time(tournament["startDate"]):
            return {"state": "waiting_for_start", "placed": False}
        try:
            research = self.update_research()
        except Exception as error:
            research = {"state": "unavailable", "error_type": type(error).__name__, "directional_trading_enabled": False}
            self.state.event("research_unavailable", research)
        portfolio = read_portfolio(self.api, self.config, tournament)
        high = max(portfolio["equity"], self.state.get("high_water_equity", portfolio["equity"]))
        self.state.put("high_water_equity", high)
        if portfolio["equity"] < high * (1 - self.config.get("worker_max_drawdown_fraction", .2)):
            self.latch_halt("Account equity breached the configured drawdown limit.")
            return {"state": "halted", "placed": False}
        if portfolio["open_orders"]:
            self.latch_halt("Unjournaled open orders exist. Review their exposure before resuming.")
            return {"state": "halted", "placed": False}
        if any(float(row["outstandingAdvance"]) > 1e-9 for row in portfolio["collateral"]):
            self.latch_halt("Collateral advances are present; the current worker does not model their liquidation rules.")
            return {"state": "halted", "placed": False}
        markets = self.markets()
        quotes = collect_quotes(self.api, self.config["tournament_id"], markets, workers=3)
        candidates = screen_party_bundles(markets, quotes, self.config["structural_min_edge"])
        # Rotate through candidates with a durable cursor, so deep review does not
        # repeatedly starve smaller races when headline opportunities lack depth.
        fingerprint = hashlib.sha256(json.dumps([sorted(l["exchange_id"] for l in c["legs"]) for c in candidates]).encode()).hexdigest()
        cursor = self.state.get("review_cursor", 0) if self.state.get("candidate_fingerprint") == fingerprint else 0
        self.state.put("candidate_fingerprint", fingerprint)
        limit = min(len(candidates), int(self.config.get("worker_max_reviews_per_cycle", 6)))
        batch = [candidates[(cursor + i) % len(candidates)] for i in range(limit)] if candidates else []
        self.state.put("review_cursor", (cursor + limit) % len(candidates) if candidates else 0)
        books, eligible, skipped = {}, [], []
        for candidate in batch:
            try:
                reviewed = self.review(candidate)
                race_ids = self.race_exchanges(reviewed, portfolio)
                budget = self.capacity(reviewed, portfolio, race_ids)
                missing = [str(leg["exchange_id"]) for leg in reviewed["legs"] if str(leg["exchange_id"]) not in books]
                def fetch_book(eid):
                    book = self.api.get(f"/exchanges/{eid}/orderbook", depth=20, tournamentId=self.config["tournament_id"])
                    return eid, dict(book, received_at=utc_now())
                with ThreadPoolExecutor(max_workers=4) as pool:
                    books.update(pool.map(fetch_book, missing))
                plan = plan_no_bundle(reviewed, books, portfolio["cash"], self.config, budget,
                                      int(self.config.get("worker_max_shares", 5000)))
                eligible.append({"reviewed": reviewed, "plan": plan, "race_ids": sorted(race_ids), "budget": budget})
            except ValueError as error:
                skipped.append({"race": candidate["race"], "reason": str(error)})
        eligible.sort(key=lambda item: item["plan"]["normal_settlement_gain_floor_at_limits"], reverse=True)
        report = {"state": "live_scan" if self.live else "read_only_scan", "placed": False,
                  "captured_at": utc_now(), "market_count": len(markets), "quote_count": len(quotes["data"]),
                  "provisional_candidates": len(candidates), "reviewed_this_cycle": len(batch),
                  "eligible": eligible, "skipped": skipped, "portfolio": portfolio,
                  "recovered_baskets": len(recovered), "config_sha256": self.config_hash,
                  "directional_trading_enabled": False, "research": research}
        write_json(self.work / "latest_quotes.json", quotes)
        if not self.live or not eligible or self.stopped():
            return report
        selected = eligible[0]
        execution_config = dict(self.config, structural_race_exchange_ids=selected["race_ids"],
                                structural_allowed_exchange_sets=[[l["exchange_id"] for l in selected["reviewed"]["legs"]]])
        # execute_no_bundle rereads metadata, portfolio, and all selected books.
        try:
            result = execute_no_bundle(self.api, execution_config, selected["reviewed"], self.work,
                                       selected["budget"], int(self.config.get("worker_max_shares", 5000)), self.stopped)
        except ValueError as error:
            if self.unresolved()[0]:
                raise
            report["entry_blocked"] = str(error)
            return report
        report["placed"], report["execution"] = True, result
        fills = result["reconciliation"]
        if not fills["balanced_full_fill"] and any(fills["quantities_filled"]):
            self.latch_halt("Basket partially filled. Remaining journal-owned orders were cancelled; review before resuming.")
            report["state"] = "halted"
        self.state.event("execution", {"race": selected["reviewed"]["race"],
                                       "cost": fills["nominal_entry_cost"],
                                       "conditional_gain_floor": fills["normal_settlement_gain_floor"],
                                       "balanced_full_fill": fills["balanced_full_fill"]})
        return report

    def step(self):
        try:
            result = self.tick()
            self.transient_errors = 0
        except EntryBlocked as error:
            result = {"state": "blocked", "placed": False, "reason": str(error)}
        except (OSError, TimeoutError, urllib.error.URLError, APIError) as error:
            retryable = not isinstance(error, APIError) or error.status in (409, 429, 500, 502, 503, 504)
            self.transient_errors += 1
            if not retryable or self.transient_errors >= int(self.config.get("worker_error_limit", 3)):
                self.latch_halt(f"API access or repeated transport failure: {type(error).__name__}: {error}")
            result = {"state": "halted" if self.halted() else "retry_wait", "placed": False,
                      "error_type": type(error).__name__, "error": str(error), "consecutive_errors": self.transient_errors}
        except Exception as error:
            self.latch_halt(f"Reconciliation or invariant failure: {type(error).__name__}: {error}")
            result = {"state": "halted", "placed": False, "error_type": type(error).__name__, "error": str(error)}
        if "error_type" in result:
            baskets, single_pending = self.unresolved()
            if baskets or single_pending:
                result["placed"] = None
                result["order_status"] = "recovery_required; exchange effect is not yet fully reconciled"
        self.cycles += 1
        result.update(cycle=self.cycles, finished_at=utc_now(), live=self.live)
        write_json(self.work / "last_cycle.json", result)
        write_json(self.work / "heartbeat.json", {k: result[k] for k in ("cycle", "state", "placed", "finished_at", "live")})
        print(json.dumps({k: result[k] for k in ("cycle", "state", "placed", "finished_at", "live")}), flush=True)
        return result


def run_worker(api, config, work_dir, live=False, cycles=None, stop_event=None):
    if cycles is not None and cycles < 1:
        raise ValueError("cycles must be positive.")
    shutdown = stop_event or threading.Event()
    previous_signals = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_signals[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda _signum, _frame: shutdown.set())
    try:
        with process_lock(work_dir):
            worker = AutonomousWorker(api, config, work_dir, live, shutdown)
            try:
                while not shutdown.is_set():
                    write_json(Path(work_dir) / "heartbeat.json", {"state": "scanning", "at": utc_now(), "live": live})
                    result = worker.step()
                    if result["state"] == "finished" or (cycles is not None and worker.cycles >= cycles):
                        return result
                    shutdown.wait(max(10, float(config.get("loop_interval_seconds", 60))))
            finally:
                write_json(Path(work_dir) / "heartbeat.json", {"state": "stopped", "at": utc_now(), "live": live})
                worker.close()
    finally:
        for signum, previous in previous_signals.items():
            signal.signal(signum, previous)


def resume_worker(work_dir):
    """Explicit local operator action after reviewing partial fills or a halt."""
    with process_lock(work_dir):
        baskets = BasketJournal(Path(work_dir) / "basket_operations.sqlite3")
        singles = Journal(Path(work_dir) / "operations.sqlite3")
        try:
            if baskets.unresolved() or singles.has_unreconciled():
                raise ValueError("Recovery or manual position repair is still required; halt cannot be cleared.")
        finally:
            baskets.close()
            singles.close()
        state = WorkerState(Path(work_dir) / "worker.sqlite3")
        try:
            state.put("halt", None)
            state.event("operator_resume", {"at": utc_now()})
            (Path(work_dir) / "HALT.json").unlink(missing_ok=True)
        finally:
            state.close()


def acknowledge_partial(api, config, work_dir, key, reason):
    """Explicit operator review of residual exposure; never a new placement."""
    if not reason.strip():
        raise ValueError("An operator disposition requires a written reason.")
    with process_lock(work_dir):
        account = api.get("/account")
        if str(account["id"]) != config["expected_profile_id"]:
            raise ValueError("Participant identity mismatch.")
        portfolio = read_portfolio(api, config)
        if portfolio["open_orders"]:
            raise ValueError("Open orders must be reconciled before acknowledging residual exposure.")
        journal = BasketJournal(Path(work_dir) / "basket_operations.sqlite3")
        try:
            matches = [row for row in journal.unresolved() if row[0] == key]
            if len(matches) != 1 or matches[0][3] != "partial":
                raise ValueError("This key is not an already reconciled partial basket.")
            _, raw, plan_raw, _, response_raw = matches[0]
            plan, payload, response = json.loads(plan_raw), json.loads(raw), json.loads(response_raw)
            if plan.get("participant_id") != config["expected_profile_id"]:
                raise ValueError("Basket participant identity mismatch.")
            for leg in response["results"]:
                oid = leg["data"].get("orderId")
                if oid is not None and api.get(f"/orders/{oid}")["open"]:
                    raise ValueError("A journal-owned leg is still open.")
            fills = reconcile_basket(api, payload, response, config["tournament_id"])
            disposition = {"operator_reviewed_at": utc_now(), "reason": reason, "fills": fills,
                           "current_portfolio": portfolio,
                           "note": "Operator accepts or has managed residual holdings. This records a review, not a repair or a new trade."}
            journal.acknowledge_partial(key, disposition)
            return disposition
        finally:
            journal.close()
