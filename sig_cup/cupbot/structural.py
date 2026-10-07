"""Scoped quote screening and small, reviewed election-basket execution.

The logical payout bound is conditional on consistent normal settlement.
Multi-leg placement does not guarantee simultaneous or complete fills.
"""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from .model import parse_time, utc_now
from .runtime import (inspect_and_cancel_remainder, require_active,
                      resolve_tournament, write_json)
from .strategy import buy_limit, check_book, entry_quote


def collect_quotes(api, tournament_id, markets, workers=1):
    expected = {str(e["id"]): str(m["id"]) for m in markets for e in m["exchanges"]}
    ids, quotes = list(expected), []
    batches = [ids[start:start + 100] for start in range(0, len(ids), 100)]
    def fetch(batch):
        response = api.get("/exchanges/prices", ids=",".join(batch), tournamentId=tournament_id)
        received_at = utc_now()
        return batch, response, received_at
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as pool:
        responses = list(pool.map(fetch, batches))
    for batch, response, received_at in responses:
        returned = [str(q["exchangeId"]) for q in response["data"]]
        if response["missingIds"] or returned != batch:
            raise ValueError("Bulk quotes have missing, duplicated, reordered, or out-of-scope exchanges.")
        for quote in response["data"]:
            if str(quote["marketId"]) != expected[str(quote["exchangeId"])]:
                raise ValueError("Bulk quote market identity mismatch.")
            quote = dict(quote, received_at=received_at)
            quotes.append(quote)
    return {"tournament_id": tournament_id, "captured_at": utc_now(), "data": quotes}


def screen_party_bundles(markets, quote_payload, minimum_edge=.005):
    """Titles discover candidates only; they never establish a tradable relationship."""
    quotes = {str(q["exchangeId"]): q for q in quote_payload["data"]}
    groups = {}
    for market in markets:
        match = re.fullmatch(r"Will the (.+?) Party win the (.+)\?", market["title"])
        if not match or market["status"] != "open" or len(market["exchanges"]) != 1:
            continue
        exchange = str(market["exchanges"][0]["id"])
        quote = quotes.get(exchange)
        if quote is None or quote["bestBid"] is None:
            continue
        bid = float(quote["bestBid"])
        if not math.isfinite(bid) or not 0 < bid < 1:
            raise ValueError("Invalid bulk bid.")
        groups.setdefault(match.group(2), []).append({
            "party": match.group(1), "market_id": str(market["id"]),
            "exchange_id": exchange, "title": market["title"], "best_bid": bid})
    candidates = []
    for race, members in groups.items():
        if len(members) > 10:
            continue
        for size in range(2, len(members) + 1):
            for legs in itertools.combinations(members, size):
                cost = sum(1 - leg["best_bid"] for leg in legs)
                edge = size - 1 - cost
                if edge + 1e-9 >= minimum_edge:
                    candidates.append({"race": race, "legs": list(legs),
                                       "screened_cost_per_bundle": round(cost, 10),
                                       "screened_edge_per_bundle": round(edge, 10),
                                       "metadata_reviewed": False})
    return sorted(candidates, key=lambda row: row["screened_edge_per_bundle"], reverse=True)


def review_party_bundle(candidate, node_map, tournament_id):
    legs = candidate["legs"]
    if not 2 <= len(legs) <= 10 or len({str(x["exchange_id"]) for x in legs}) != len(legs):
        raise ValueError("A basket needs 2–10 distinct exchanges.")
    identity, winners, dates = None, set(), set()
    identity_fields = ("raceId", "stageId", "raceName", "raceStage", "electionDate",
                       "usState", "officeLevel", "resolutionType")
    reviewed_legs = []
    for leg in legs:
        tree = node_map[str(leg["market_id"])]
        root = tree["root"]
        details = root.get("contract_details") or {}
        if (str(tree["market_id"]) != str(leg["market_id"]) or
                root["node_type"] != "contract" or root["contract_type"] != "Election Outcome" or
                root["title"] != leg["title"] or root["settled_with"] is not None or
                details.get("resolutionType") != "Party Winner"):
            raise ValueError("Basket resolution is not an unsettled matching Party Winner contract.")
        if not any(c["type"] == "tournament" and c["tournament"]["id"] == tournament_id
                   for c in tree["contexts"]):
            raise ValueError("Resolution tree lacks the explicit tournament context.")
        values = tuple(str(details.get(k) or "") for k in identity_fields)
        if not all(values) or (identity is not None and identity != values):
            raise ValueError("Basket legs do not resolve the same race, stage, date, and rule.")
        identity = values
        expected_winner = leg["party"] if leg["party"] == "Independent" else leg["party"] + " Party"
        winner = details.get("winnerName")
        if winner != expected_winner or winner in winners:
            raise ValueError("Basket winner labels differ or repeat.")
        winners.add(winner)
        dates.add(parse_time(root["settlement_date"]))
        reviewed_legs.append(dict(leg, winner=winner))
    if len(dates) != 1:
        raise ValueError("Settlement dates differ across the basket.")
    return dict(candidate, legs=reviewed_legs, metadata_reviewed=True,
                tournament_id=tournament_id, race_identity=dict(zip(identity_fields, identity)),
                settlement_date=next(iter(dates)).isoformat(),
                settlement_condition="At most one listed party wins this race and stage; normal YES/NO settlement.")


def no_payout_floor(quantities):
    quantities = [float(q) for q in quantities]
    if not quantities or any(not math.isfinite(q) or q < 0 for q in quantities):
        raise ValueError("NO share counts must be finite and nonnegative.")
    return sum(quantities) - max(quantities)


def plan_no_bundle(reviewed, books, cash, config, max_notional=200, max_shares=100):
    if not reviewed.get("metadata_reviewed"):
        raise ValueError("Resolution metadata has not been reviewed.")
    if not math.isfinite(cash) or cash <= 0 or not 0 < max_notional <= config["max_order_notional"]:
        raise ValueError("Invalid cash or structural notional cap.")
    if not 1 <= max_shares <= 2147483647:
        raise ValueError("Invalid maximum shares.")
    if config.get("structural_depth_enabled", False):
        return plan_no_bundle_depth(reviewed, books, cash, config, max_notional, max_shares)
    legs, depth = [], []
    for leg in reviewed["legs"]:
        book = books[str(leg["exchange_id"])]
        if (str(book["exchangeId"]) != str(leg["exchange_id"]) or
                str(book["marketId"]) != str(leg["market_id"])):
            raise ValueError("Structural book identity mismatch.")
        check_book(book, config)
        quote = entry_quote(book, "no")
        if quote is None:
            raise ValueError("A basket leg has no executable depth.")
        price, available = quote
        legs.append(dict(leg, side="no", action="buy", limit_price=price))
        depth.append(available)
    cost, floor = sum(x["limit_price"] for x in legs), len(legs) - 1
    edge = floor - cost
    if edge + 1e-9 < float(config.get("structural_min_edge", .02)):
        raise ValueError("Fresh basket prices fail the structural minimum edge.")
    budget = min(max_notional, cash * (1 - config["cash_reserve_fraction"]))
    quantity = min(max_shares, min(depth), math.floor(budget / cost))
    if quantity < 1:
        raise ValueError("Basket cash or depth is insufficient.")
    return {"race": reviewed["race"], "tournament_id": reviewed["tournament_id"],
            "legs": legs, "quantity_per_leg": quantity,
            "limit_notional": round(quantity * cost, 10),
            "normal_settlement_payout_floor": quantity * floor,
            "normal_settlement_gain_floor_at_limits": round(quantity * edge, 10),
            "max_loss_if_only_some_legs_fill": round(quantity * cost, 10),
            "note": "Payout bound requires consistent normal settlement and the planned balanced fills. Placement is atomic; fills are not."}


def plan_no_bundle_depth(reviewed, books, cash, config, max_notional, max_shares):
    """Maximize the gain floor at submitted limits over book-depth breakpoints.

    Every leg requests the same number of NO shares. All shares are charged at
    their leg's worst allowed price for sizing, even when shallower fills are
    cheaper. This bounds spending and payout without forecasting the winner.
    """
    ladders, boundaries = [], {1}
    for leg in reviewed["legs"]:
        book = books[str(leg["exchange_id"])]
        if (str(book["exchangeId"]) != str(leg["exchange_id"]) or
                str(book["marketId"]) != str(leg["market_id"])):
            raise ValueError("Structural book identity mismatch.")
        check_book(book, config)
        levels = {}
        for row in book["bids"]:
            bid, amount = float(row["price"]), float(row["quantity"])
            if not math.isfinite(bid) or not 0 < bid < 1 or not math.isfinite(amount) or amount < 0:
                raise ValueError("Invalid structural book depth.")
            price = buy_limit(round(1 - bid, 10))
            levels[price] = levels.get(price, 0.0) + amount
        cumulative, ladder = 0.0, []
        for price, amount in sorted(levels.items()):
            previous = math.floor(cumulative)
            cumulative += amount
            capacity = min(max_shares, math.floor(cumulative))
            if capacity > previous:
                ladder.append((capacity, price))
                boundaries.add(capacity)
                boundaries.add(capacity + 1)
            if capacity >= max_shares:
                break
        if not ladder:
            raise ValueError("A basket leg has no executable depth.")
        ladders.append(ladder)
    maximum = min(max_shares, *(ladder[-1][0] for ladder in ladders))
    budget = min(max_notional, cash * (1 - config["cash_reserve_fraction"]))
    points = sorted(q for q in boundaries if 1 <= q <= maximum) + [maximum + 1]
    best, floor = None, len(ladders) - 1
    for start, next_start in zip(points, points[1:]):
        prices = [next(price for capacity, price in ladder if capacity >= start) for ladder in ladders]
        cost = sum(prices)
        edge = floor - cost
        if (edge + 1e-9 < float(config.get("structural_min_edge", .02)) or
                edge / cost + 1e-9 < float(config.get("structural_min_return", 0))):
            continue
        quantity = min(next_start - 1, math.floor((budget + 1e-8) / cost))
        if quantity < start:
            continue
        gain = quantity * edge
        if best is None or gain > best[0] + 1e-8:
            best = (gain, quantity, prices, cost)
    if best is None:
        raise ValueError("Fresh depth, prices, or cash fail the structural entry limits.")
    gain, quantity, prices, cost = best
    return {"race": reviewed["race"], "tournament_id": reviewed["tournament_id"],
            "race_identity": reviewed.get("race_identity"),
            "legs": [dict(leg, side="no", action="buy", limit_price=price)
                     for leg, price in zip(reviewed["legs"], prices)],
            "quantity_per_leg": quantity, "limit_notional": round(quantity * cost, 10),
            "normal_settlement_payout_floor": quantity * floor,
            "normal_settlement_gain_floor_at_limits": round(gain, 10),
            "gain_floor_return_on_limit_cost": round((floor - cost) / cost, 10),
            "max_loss_if_only_some_legs_fill": round(quantity * cost, 10),
            "note": "Equal quantities; spending bounded at worst leg limits. Partial fills can lose money."}


class BasketJournal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS baskets (id TEXT PRIMARY KEY, payload TEXT NOT NULL, plan TEXT NOT NULL, state TEXT NOT NULL, response TEXT, reconciliation TEXT, created_at TEXT NOT NULL, error TEXT)")
        self.db.commit()

    def create(self, payload, plan):
        self.db.execute("INSERT INTO baskets VALUES (?,?,?,'pending',NULL,NULL,?,NULL)",
                        (payload["idempotencyKey"], json.dumps(payload), json.dumps(plan), utc_now()))
        self.db.commit()

    def confirmed(self, key, response):
        self.db.execute("UPDATE baskets SET state='confirmed',response=?,error=NULL WHERE id=?",
                        (json.dumps(response), key))
        self.db.commit()

    def finish(self, key, result):
        no_fills = result.get("quantities_filled") and all(q == 0 for q in result["quantities_filled"])
        state = "reconciled" if result["balanced_full_fill"] or no_fills else "partial"
        self.db.execute("UPDATE baskets SET state=?,reconciliation=?,error=NULL WHERE id=?",
                        (state, json.dumps(result), key))
        self.db.commit()

    def error(self, key, error):
        self.db.execute("UPDATE baskets SET error=? WHERE id=?", (str(error), key))
        self.db.commit()

    def unresolved(self):
        return list(self.db.execute("SELECT id,payload,plan,state,response FROM baskets WHERE state IN ('pending','confirmed','partial') ORDER BY created_at"))

    def acknowledge_partial(self, key, disposition):
        updated = self.db.execute("UPDATE baskets SET state='reviewed_partial',reconciliation=?,error=NULL WHERE id=? AND state='partial'",
                                  (json.dumps(disposition, allow_nan=False), key))
        if updated.rowcount != 1:
            raise ValueError("Only a known partial basket can receive an operator disposition.")
        self.db.commit()

    def daily_notional(self):
        today = datetime.now(timezone.utc).date().isoformat()
        rows = self.db.execute("SELECT payload FROM baskets WHERE substr(created_at,1,10)=?", (today,))
        payloads = [json.loads(row[0]) for row in rows]
        return len(payloads), sum(sum(l["price"] * l["quantity"] for l in p["legs"]) for p in payloads)

    def close(self):
        self.db.close()


def reconcile_basket(api, payload, response, tournament_id):
    results = response["results"]
    if sorted(x["index"] for x in results) != list(range(len(payload["legs"]))):
        raise ValueError("Basket acknowledgement is incomplete or duplicated.")
    reconciliations, errors, quantities, nominal_cost = [], [], [], 0.0
    for result in sorted(results, key=lambda x: x["index"]):
        data, requested = result["data"], payload["legs"][result["index"]]
        if str(data["exchangeId"]) != str(requested["exchangeId"]):
            raise ValueError("Basket acknowledgement exchange mismatch.")
        try:
            item = inspect_and_cancel_remainder(api, data, tournament_id)
            fills = item["fills"]
            if fills is None:
                if abs(float(data["quantityTraded"])) > 1e-9:
                    raise ValueError("A filled leg lacks an order ID and fill history.")
                quantity, cost = 0, 0
            else:
                quantity = -float(fills["totalQuantityFilled"])
                if quantity < 0 or quantity > requested["quantity"] + 1e-8:
                    raise ValueError("Unexpected fill side or excess basket quantity.")
                order = item["order"]
                if (str(order["exchangeId"]) != str(requested["exchangeId"]) or
                        order["side"] != "no" or order["action"] != "buy"):
                    raise ValueError("Confirmed basket order is not the requested NO buy.")
                if quantity and fills["avgFillPrice"] is None:
                    raise ValueError("A filled leg lacks its average outcome-relative price.")
                average = float(fills["avgFillPrice"]) if quantity else 0
                if not math.isfinite(average) or not 0 <= average <= 1:
                    raise ValueError("Invalid average fill price.")
                # Live v1 order fill prices are outcome-relative, unlike YES-normalized books.
                cost = quantity * average
                if any(row["side"] != "no" for row in fills["data"]):
                    raise ValueError("Unexpected outcome side in basket fills.")
                if cost > requested["price"] * quantity + 1e-7:
                    raise ValueError("NO fills exceed the submitted price limit.")
                if abs(quantity - abs(float(data["quantityTraded"]))) < 1e-8:
                    economics = data.get("all")
                    receipt_cost = float(economics["fullNotionalCost"] if economics else data["totalCost"])
                    if not math.isfinite(receipt_cost) or abs(cost - receipt_cost) > 1e-6:
                        raise ValueError("Fill prices disagree with the authoritative nominal-cost receipt.")
            quantities.append(quantity)
            nominal_cost += cost
            reconciliations.append(item)
        except Exception as error:
            # Try to cancel/reconcile the other journal-owned legs even if one reporting view lags.
            errors.append(str(error))
    if errors:
        raise RuntimeError("Basket reconciliation incomplete: " + "; ".join(errors))
    balanced = all(abs(q - leg["quantity"]) < 1e-8 for q, leg in zip(quantities, payload["legs"]))
    floor = no_payout_floor(quantities)
    return {"balanced_full_fill": balanced, "quantities_filled": quantities,
            "nominal_entry_cost": round(nominal_cost, 10),
            "fill_price_convention": "outcome_relative",
            "normal_settlement_payout_floor": floor,
            "normal_settlement_gain_floor": round(floor - nominal_cost, 10),
            "legs": reconciliations,
            "note": "Conditional on the reviewed mutually exclusive race resolving normally. Partial fills halt further execution."}


def execute_no_bundle(api, config, reviewed, work_dir, max_notional=200, max_shares=100, stop_check=None):
    if not config.get("structural_live_enabled", False):
        raise ValueError("structural_live_enabled is false.")
    allowed = [set(map(str, group)) for group in config.get("structural_allowed_exchange_sets", [])]
    selected = {str(x["exchange_id"]) for x in reviewed["legs"]}
    if selected not in allowed or reviewed["tournament_id"] != config["tournament_id"]:
        raise ValueError("Basket is not in the explicitly configured tournament/exchange allowlist.")
    stop = Path(work_dir) / "STOP"
    if stop.exists():
        raise ValueError("STOP file is present.")
    if stop_check and stop_check():
        raise ValueError("Shutdown was requested.")
    journal = BasketJournal(Path(work_dir) / "basket_operations.sqlite3")
    key = None
    try:
        if journal.unresolved():
            raise ValueError("An earlier basket is unresolved; run basket-recover first.")
        if config.get("autonomous_live_enabled"):
            from .runtime import Journal
            singles = Journal(Path(work_dir) / "operations.sqlite3")
            try:
                if singles.has_unreconciled():
                    raise ValueError("An earlier single order is unresolved.")
                single_count, single_notional = singles.daily_usage(config["tournament_id"])
            finally:
                singles.close()
        else:
            single_count, single_notional = 0, 0
        count, used = journal.daily_notional()
        count += single_count
        used += single_notional
        if count >= config["max_orders_per_day"]:
            raise ValueError("Daily basket submission cap reached.")
        tournament = resolve_tournament(api, config)
        require_active(tournament)
        nodes = {str(l["market_id"]): api.get(f'/markets/{l["market_id"]}/nodes',
                                              tournamentId=config["tournament_id"])
                 for l in reviewed["legs"]}
        reviewed = review_party_bundle(reviewed, nodes, config["tournament_id"])
        slug, tid = config["tournament_slug"], config["tournament_id"]
        orders = api.pages("/orders", status="open", tournamentId=tid, limit=200)
        if orders:
            raise ValueError("Open orders must be reconciled before a structural basket.")
        positions = api.get(f"/tournaments/{slug}/portfolio/positions")["positions"]
        collateral = api.get("/portfolio/collateral", tournamentId=tid)["data"]
        if any(float(x["outstandingAdvance"]) > 1e-9 for x in collateral):
            raise ValueError("Existing collateral advances require a separate execution policy.")
        active = [p for p in positions if not p["settled"] and float(p["quantity"])]
        if any(str(p["exchangeId"]) in selected and float(p["quantity"]) > 0 for p in active):
            raise ValueError("Opposite YES holdings would net basket legs.")
        race_ids = selected | set(map(str, config.get("structural_race_exchange_ids", [])))
        race_cost = sum(max(0, float(p["costBasis"])) for p in active if str(p["exchangeId"]) in race_ids)
        total_cost = sum(max(0, float(p["costBasis"])) for p in active)
        tournament = resolve_tournament(api, config)
        cash = float(tournament["myBalance"])
        pnl = api.get(f"/tournaments/{slug}/portfolio/pnl", period="all")
        equity = float(pnl["totalAccountValue"])
        if not math.isfinite(equity) or equity <= 0 or not math.isfinite(cash):
            raise ValueError("Invalid account cash or equity.")
        books = {}
        for leg in reviewed["legs"]:
            eid = str(leg["exchange_id"])
            books[eid] = api.get(f"/exchanges/{eid}/orderbook", depth=20, tournamentId=tid)
            books[eid]["received_at"] = utc_now()
        capacity = min(max_notional, config["daily_entry_notional_cap"] - used,
                       equity * config["max_total_at_risk"] - total_cost,
                       config.get("structural_max_race_notional", 10000) - race_cost,
                       cash - equity * config["cash_reserve_fraction"])
        if capacity <= 0:
            raise ValueError("No capacity remains after portfolio and daily limits.")
        plan = plan_no_bundle(reviewed, books, cash, config, capacity, max_shares)
        plan["account_before"] = {"cash": cash, "positions": positions}
        plan["participant_id"] = config.get("expected_profile_id")
        notional = plan["limit_notional"]
        if (used + notional > config["daily_entry_notional_cap"] or
                total_cost + notional > float(pnl["totalAccountValue"]) * config["max_total_at_risk"] or
                race_cost + notional > float(config.get("structural_max_race_notional", 10000))):
            raise ValueError("Daily, total portfolio, or race notional cap would be exceeded.")
        cutoff = parse_time(tournament["endDate"])
        if config.get("trading_deadline_utc"):
            cutoff = min(cutoff, parse_time(config["trading_deadline_utc"]))
        expiration = min(datetime.now(timezone.utc) + timedelta(seconds=config["order_expiry_seconds"]),
                         cutoff).isoformat()
        key = "evan-cup-basket-" + uuid.uuid4().hex
        payload = {"idempotencyKey": key, "legs": [
            {"exchangeId": leg["exchange_id"], "side": "no", "action": "buy",
             "quantity": plan["quantity_per_leg"], "price": leg["limit_price"],
             "tournamentId": tid, "expirationDate": expiration} for leg in plan["legs"]]}
        write_json(Path(work_dir) / "last_basket_plan.json", plan)
        if stop.exists() or (stop_check and stop_check()):
            raise ValueError("STOP appeared before submission.")
        require_active(tournament)
        if datetime.now(timezone.utc) >= cutoff:
            raise ValueError("Pinned trading deadline has passed.")
        journal.create(payload, plan)
        response = api.post("/orders/multi-leg", payload)
        journal.confirmed(key, response)
        reconciliation = reconcile_basket(api, payload, response, tid)
        if config.get("verify_account_after_trade"):
            reconciliation["account_verification"] = verify_basket_account(api, config, plan, payload, reconciliation)
        journal.finish(key, reconciliation)
        return {"placed": True, "plan": plan, "reconciliation": reconciliation}
    except Exception as error:
        if key is not None:
            journal.error(key, error)
        raise
    finally:
        journal.close()


def verify_basket_account(api, config, plan, payload, result):
    """Verify position deltas and nominal cash debit before clearing the journal."""
    before = plan.get("account_before")
    if before is None:
        raise ValueError("Basket lacks the durable pre-trade account snapshot.")
    expected = {str(p["exchangeId"]): float(p["quantity"]) for p in before["positions"] if not p["settled"]}
    for leg, quantity in zip(payload["legs"], result["quantities_filled"]):
        eid = str(leg["exchangeId"])
        expected[eid] = expected.get(eid, 0.0) - quantity
    current = api.get(f'/tournaments/{config["tournament_slug"]}/portfolio/positions')["positions"]
    actual = {str(p["exchangeId"]): float(p["quantity"]) for p in current if not p["settled"]}
    if any(abs(expected.get(eid, 0) - actual.get(eid, 0)) > 1e-7 for eid in expected.keys() | actual.keys()):
        raise RuntimeError("Post-trade positions do not yet match the reconciled fills.")
    cash = float(resolve_tournament(api, config)["myBalance"])
    collateral = api.get("/portfolio/collateral", tournamentId=config["tournament_id"])["data"]
    if any(float(p["outstandingAdvance"]) > 1e-9 for p in collateral):
        raise RuntimeError("A collateral advance appeared; the worker cannot reconcile this policy.")
    if abs(before["cash"] - cash - result["nominal_entry_cost"]) > 1e-6:
        raise RuntimeError("Post-trade cash does not match the nominal fill costs.")
    return {"verified_at": utc_now(), "cash": cash, "position_deltas_match": True, "cash_debit_matches": True}


def recover_baskets(api, config, work_dir, allow_replay=True):
    resolve_tournament(api, config)
    journal = BasketJournal(Path(work_dir) / "basket_operations.sqlite3")
    recovered = []
    try:
        for key, raw, plan_raw, state, response_raw in journal.unresolved():
            payload = json.loads(raw)
            plan = json.loads(plan_raw)
            if any(l["tournamentId"] != config["tournament_id"] for l in payload["legs"]):
                raise ValueError("Unresolved basket has a different tournament scope.")
            if config.get("autonomous_live_enabled") and plan.get("participant_id") != config.get("expected_profile_id"):
                raise ValueError("Unresolved basket lacks this participant's identity evidence.")
            if state == "pending" and not allow_replay:
                raise RuntimeError("Pending basket needs replay; trading is paused.")
            # Same endpoint, key, legs, prices and expirations; never create a second placement.
            response = api.post("/orders/multi-leg", payload) if state == "pending" else json.loads(response_raw)
            journal.confirmed(key, response)
            result = reconcile_basket(api, payload, response, config["tournament_id"])
            if config.get("verify_account_after_trade"):
                if plan.get("account_before"):
                    result["account_verification"] = verify_basket_account(api, config, plan, payload, result)
            journal.finish(key, result)
            recovered.append(result)
        return recovered
    finally:
        journal.close()
