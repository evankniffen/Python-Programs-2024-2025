"""Scoped REST collection, durable order journal, and guarded live operation."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.parse
import uuid

from .api import API
from .model import parse_time, utc_now
from .strategy import bundle_alerts, check_book, entry_quote, plan_entries


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(destination)


def validate_config(config):
    uuid.UUID(config["tournament_id"])
    slug = config["tournament_slug"]
    if not slug or "/" in slug or slug.startswith("REPLACE"):
        raise ValueError("Set the exact tournament slug returned by discover.")
    if not config.get("expected_tournament_name"):
        raise ValueError("Pin expected_tournament_name to the exact discovery result.")
    for key, default in (("kelly_fraction", .15), ("cash_reserve_fraction", .20),
                         ("max_exchange_at_risk", .10), ("max_total_at_risk", .45),
                         ("max_tail_loss_fraction", .35)):
        value = float(config.get(key, default))
        if not 0 < value < 1:
            raise ValueError(f"{key} must be strictly between zero and one.")
    if not 0 <= float(config.get("execution_buffer", .005)) < .2:
        raise ValueError("Invalid execution buffer.")
    if not 0 < float(config.get("min_robust_edge", .03)) < 1:
        raise ValueError("Invalid minimum edge.")
    for key, default in (("max_quote_age_seconds", 120), ("max_forecast_age_hours", 6),
                         ("max_input_age_hours", 168), ("max_order_notional", 2000),
                         ("loop_interval_seconds", 60), ("max_orders_per_day", 100),
                         ("daily_entry_notional_cap", 20000)):
        if not 0 < float(config.get(key, default)) < float("inf"):
            raise ValueError(f"{key} must be positive and finite.")
    if not 1 <= int(config.get("order_expiry_seconds", 30)) <= 300:
        raise ValueError("Order expiration must be between 1 and 300 seconds.")


def resolve_tournament(api, config):
    validate_config(config)
    slug = urllib.parse.quote(config["tournament_slug"], safe="")
    tournament = api.get(f"/tournaments/{slug}")
    if str(tournament["id"]) != config["tournament_id"] or tournament["name"] != config["expected_tournament_name"]:
        raise ValueError("Tournament identity mismatch; refusing default/global routing.")
    return tournament


def require_active(tournament):
    now = datetime.now(timezone.utc)
    if tournament["status"] != "active" or (tournament.get("startDate") and now < parse_time(tournament["startDate"])) or (tournament.get("endDate") and now >= parse_time(tournament["endDate"])):
        raise ValueError("Tournament is not in its live trading window.")


def collect_snapshot(api, config, forecast_payload=None):
    tournament = resolve_tournament(api, config)
    slug = urllib.parse.quote(config["tournament_slug"], safe="")
    tournament_id = tournament["id"]
    markets = api.pages(f"/tournaments/{slug}/markets", status="any", limit=100)
    exchanges = {str(ex["id"]): market for market in markets for ex in market["exchanges"] if market["status"] == "open"}
    watch = [str(exchange) for exchange in config.get("watch_exchange_ids", [])]
    if not watch and forecast_payload:
        watch = [str(row["exchange_id"]) for row in forecast_payload["forecasts"]]
    if not watch:
        watch = sorted(exchanges, key=int)[:int(config.get("discovery_book_limit", 20))]
    watch = list(dict.fromkeys(watch))
    books, details = {}, {}
    for exchange in watch:
        if exchange not in exchanges:
            continue
        book = api.get(f"/exchanges/{exchange}/orderbook", depth=20, tournamentId=tournament_id)
        if str(book["exchangeId"]) != exchange:
            raise ValueError("Book exchange identity mismatch.")
        book["received_at"] = utc_now()
        books[exchange] = book
        market_id = str(exchanges[exchange]["id"])
        if market_id not in details:
            details[market_id] = api.get(f"/tournaments/{slug}/markets/{market_id}")
    # Fetch portfolio after book collection so risk data is recent.
    tournament = resolve_tournament(api, config)
    positions = api.get(f"/tournaments/{slug}/portfolio/positions")
    pnl = api.get(f"/tournaments/{slug}/portfolio/pnl", period="all")
    orders = api.pages("/orders", status="open", tournamentId=tournament_id, limit=200)
    if any(str(order["tournamentId"]) != tournament_id for order in orders):
        raise ValueError("Order response mixed tournament scopes.")
    collateral = api.get("/portfolio/collateral", tournamentId=tournament_id)
    if any(str(row["tournamentId"]) != tournament_id for row in collateral["data"]):
        raise ValueError("Collateral response mixed tournament scopes.")
    leaderboard = api.get(f"/tournaments/{slug}/leaderboard", period="all", sort="pnl", limit=100)
    constraints = api.get("/relationships/constraints", tournamentId=tournament_id, violationsOnly="true", minViolation=0.005)
    return {"captured_at": utc_now(), "tournament": tournament, "markets": markets,
            "market_details": details, "books": books, "positions": positions, "pnl": pnl,
            "open_orders": orders, "collateral": collateral, "leaderboard": leaderboard,
            "relationship_constraints": constraints,
            "coverage": {"open_exchanges": len(exchanges), "books_collected": len(books),
                         "watched_exchange_ids": watch, "note": "REST collection is sequential, not an atomic snapshot."}}


class Journal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, response TEXT, created_at TEXT NOT NULL, error TEXT)")
        self.db.commit()

    def create(self, payload):
        key = payload["idempotencyKey"]
        self.db.execute("INSERT INTO operations VALUES (?,?, 'pending',NULL,?,NULL)",
                        (key, json.dumps(payload, sort_keys=True, allow_nan=False), utc_now()))
        self.db.commit()

    def pending(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM operations WHERE state='pending' ORDER BY created_at")]

    def confirmed(self, key, response):
        self.db.execute("UPDATE operations SET state='confirmed',response=?,error=NULL WHERE id=?",
                        (json.dumps(response, allow_nan=False), key))
        self.db.commit()

    def record_error(self, key, error):
        self.db.execute("UPDATE operations SET error=? WHERE id=?", (str(error), key))
        self.db.commit()

    def reconciled(self, key):
        self.db.execute("UPDATE operations SET state='reconciled' WHERE id=? AND state='confirmed'", (key,))
        self.db.commit()

    def has_unreconciled(self):
        return self.db.execute("SELECT 1 FROM operations WHERE state IN ('pending','confirmed') LIMIT 1").fetchone() is not None

    def responses(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT response FROM operations WHERE state='confirmed' AND response IS NOT NULL")]

    def daily_usage(self, tournament_id):
        today = datetime.now(timezone.utc).date().isoformat()
        count, notional = 0, 0.0
        for raw, in self.db.execute("SELECT payload FROM operations WHERE substr(created_at,1,10)=?", (today,)):
            payload = json.loads(raw)
            if payload["tournamentId"] == tournament_id:
                count += 1
                notional += payload["quantity"] * payload["price"]
        return count, notional

    def close(self):
        self.db.close()


@contextmanager
def process_lock(work_dir):
    destination = Path(work_dir)
    destination.mkdir(parents=True, exist_ok=True)
    handle = (destination / "bot.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Another bot owns this work directory.")
    try:
        yield
    finally:
        handle.close()


def inspect_and_cancel_remainder(api, response, tournament_id):
    order_id = response.get("orderId")
    if order_id is None:
        if response.get("open"):
            raise RuntimeError("Response reports an open order without an orderId; inspect the account.")
        return {"response": response, "order": None, "fills": None}
    order = api.get(f"/orders/{order_id}")
    if str(order["tournamentId"]) != tournament_id:
        raise ValueError("Journal order is outside the configured tournament.")
    if order["open"]:
        api.request("DELETE", f"/orders/{order_id}")
        order = api.get(f"/orders/{order_id}")
        if order["open"]:
            raise RuntimeError("Cancellation is not confirmed; stop before placing another order.")
    fills = api.get(f"/orders/{order_id}/fills", limit=200)
    if str(fills["tournamentId"]) != tournament_id:
        raise ValueError("Fill response is outside the configured tournament.")
    if abs(float(fills["totalQuantityFilled"])) + 1e-8 < abs(float(response.get("quantityTraded", 0))):
        raise RuntimeError("Fill reporting has not caught up to the order acknowledgement; reconcile before proceeding.")
    if fills["pagination"].get("hasMore"):
        fills["data"] = api.pages(f"/orders/{order_id}/fills", limit=200)
        fills["pagination"] = {"hasMore": False, "nextCursor": None}
    return {"response": response, "order": order, "fills": fills}


def recover_pending(api, journal, config):
    results = []
    for payload in journal.pending():
        if payload["tournamentId"] != config["tournament_id"]:
            raise ValueError("Unresolved operation belongs to another tournament; inspect that journal first.")
        try:
            response = api.post("/orders", payload)  # Exactly the same durable key and payload.
            journal.confirmed(payload["idempotencyKey"], response)
            results.append(inspect_and_cancel_remainder(api, response, config["tournament_id"]))
            journal.reconciled(payload["idempotencyKey"])
        except Exception as error:
            journal.record_error(payload["idempotencyKey"], error)
            raise
    # A process may have stopped after committing its response but before cancelling.
    for key, raw in list(journal.db.execute("SELECT id,response FROM operations WHERE state='confirmed'")):
        response = json.loads(raw)
        order_id = response.get("orderId")
        if order_id is not None:
            results.append(inspect_and_cancel_remainder(api, response, config["tournament_id"]))
        journal.reconciled(key)
    return results


def analysis(snapshot, forecasts, scenario_path, config, groups_path=None):
    result = plan_entries(snapshot, forecasts, scenario_path, config)
    result["bundle_alerts"] = bundle_alerts(snapshot, read_json(groups_path), config) if groups_path else []
    result["engine_relationship_alerts"] = snapshot.get("relationship_constraints", {})
    result["snapshot_coverage"] = snapshot["coverage"]
    return result


def execute_once(api, config, forecast_path, scenario_path, work_dir):
    if not config.get("live_enabled", False):
        raise ValueError("live_enabled is false; use snapshot/scan until calibrated inputs are ready.")
    if (Path(work_dir) / "STOP").exists():
        raise ValueError("STOP file is present.")
    forecasts = read_json(forecast_path)
    if not forecasts.get("validated", False):
        raise ValueError("The forecast model has not been marked historically validated.")
    journal = Journal(Path(work_dir) / "operations.sqlite3")
    try:
        resolve_tournament(api, config)
        if journal.has_unreconciled():
            raise ValueError("Unresolved order request or reconciliation exists. Run recover before submitting another operation.")
        count, used = journal.daily_usage(config["tournament_id"])
        if count >= int(config.get("max_orders_per_day", 100)):
            raise ValueError("Daily submission cap reached.")
        snapshot = collect_snapshot(api, config, forecasts)
        require_active(snapshot["tournament"])
        if snapshot["open_orders"]:
            raise ValueError("Open orders exist; reconcile/cancel their exposure before this entry-only bot runs.")
        if any(float(row["outstandingAdvance"]) > 1e-9 for row in snapshot["collateral"]["data"]):
            raise ValueError("Existing ALL collateral advance requires a separate collateral-aware execution policy.")
        result = plan_entries(snapshot, forecasts, scenario_path, config)
        eligible = [row for row in result["candidates"] if row["resolution_reviewed"] and row["forecast_approved"]]
        if not eligible:
            write_json(Path(work_dir) / "last_scan.json", result)
            return {"placed": False, "reason": "No approved, reviewed candidate passed the edge/risk checks.", "analysis": result}
        candidate = eligible[0]
        # Re-read the selected book immediately before submission, then resize against that quote.
        exchange = candidate["exchange_id"]
        fresh = api.get(f"/exchanges/{exchange}/orderbook", depth=20, tournamentId=config["tournament_id"])
        if str(fresh["exchangeId"]) != exchange:
            raise ValueError("Fresh book exchange identity mismatch.")
        fresh["received_at"] = utc_now()
        snapshot["books"][exchange] = fresh
        refreshed = plan_entries(snapshot, forecasts, scenario_path, config)
        choices = [row for row in refreshed["candidates"] if row["exchange_id"] == exchange and row["resolution_reviewed"] and row["forecast_approved"]]
        if not choices:
            return {"placed": False, "reason": "Edge/risk check no longer passes on the refreshed book."}
        candidate = choices[0]
        if used + candidate["notional_cap"] > float(config.get("daily_entry_notional_cap", 20000)):
            raise ValueError("Daily entry-notional cap would be exceeded.")
        check_book(fresh, config)
        expiration = min(datetime.now(timezone.utc) + timedelta(seconds=int(config.get("order_expiry_seconds", 30))),
                         parse_time(snapshot["tournament"]["endDate"]))
        payload = {"idempotencyKey": "evan-cup-" + uuid.uuid4().hex, "exchangeId": exchange,
                   "side": candidate["side"], "action": "buy", "quantity": candidate["quantity"],
                   "price": candidate["limit_price"], "tournamentId": config["tournament_id"],
                   "expirationDate": expiration.isoformat()}
        if (Path(work_dir) / "STOP").exists():
            raise ValueError("STOP appeared before submission.")
        require_active(snapshot["tournament"])
        journal.create(payload)  # Commit identity BEFORE the first request can reach the server.
        try:
            response = api.post("/orders", payload)
            journal.confirmed(payload["idempotencyKey"], response)
        except Exception as error:
            journal.record_error(payload["idempotencyKey"], error)
            raise
        reconciled = inspect_and_cancel_remainder(api, response, config["tournament_id"])
        slug = urllib.parse.quote(config["tournament_slug"], safe="")
        reconciled["positions_after"] = api.get(f"/tournaments/{slug}/portfolio/positions")
        reconciled["pnl_after"] = api.get(f"/tournaments/{slug}/portfolio/pnl", period="all")
        journal.reconciled(payload["idempotencyKey"])
        report = {"placed": True, "candidate": candidate, "request": payload, "execution": reconciled,
                  "forecast_sha256": hashlib.sha256(Path(forecast_path).read_bytes()).hexdigest()}
        write_json(Path(work_dir) / (payload["idempotencyKey"] + ".json"), report)
        return report
    finally:
        journal.close()


def run_loop(api, config, forecast_path, scenario_path, work_dir, live=False, cycles=None):
    with process_lock(work_dir):
        completed = 0
        while cycles is None or completed < cycles:
            if (Path(work_dir) / "STOP").exists():
                return
            if live:
                result = execute_once(api, config, forecast_path, scenario_path, work_dir)
            else:
                forecasts = read_json(forecast_path)
                snapshot = collect_snapshot(api, config, forecasts)
                require_active(snapshot["tournament"])
                write_json(Path(work_dir) / "latest_snapshot.json", snapshot)
                result = analysis(snapshot, forecasts, scenario_path, config)
            write_json(Path(work_dir) / "last_cycle.json", result)
            print(json.dumps({"cycle": completed + 1, "at": utc_now(), "placed": result.get("placed", False),
                              "candidate_count": len(result.get("candidates", []))}), flush=True)
            completed += 1
            if cycles is not None and completed >= cycles:
                return
            until = time.monotonic() + max(30, float(config.get("loop_interval_seconds", 60)))
            while time.monotonic() < until:
                if (Path(work_dir) / "STOP").exists():
                    return
                time.sleep(min(1, max(0, until - time.monotonic())))
