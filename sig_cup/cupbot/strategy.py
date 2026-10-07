"""Conservative limit-entry sizing and scenario-based portfolio diagnostics."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import math
import numpy as np
from .model import parse_time


def buy_limit(value):
    tick = Decimal("0.005")
    result = (Decimal(str(value)) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if not Decimal("0.005") <= result <= Decimal("0.995"):
        raise ValueError("Entry price is outside the limit-order grid.")
    return float(result)


def entry_quote(book, side):
    if side not in ("yes", "no"):
        raise ValueError("Unknown outcome side.")
    # REST books are YES-normalized; order inputs and live order fills are side-relative.
    source = book["asks"] if side == "yes" else book["bids"]
    levels = [(float(row["price"]) if side == "yes" else 1 - float(row["price"]),
               float(row["quantity"])) for row in source]
    levels = sorted((round(price, 10), quantity) for price, quantity in levels if quantity >= 1)
    if not levels:
        return None
    price, quantity = levels[0]
    if not math.isfinite(price) or not math.isfinite(quantity) or not 0 < price < 1:
        raise ValueError("Invalid executable book level.")
    return buy_limit(price), min(2147483647, math.floor(quantity))


def age_seconds(value, now=None):
    reference = now or datetime.now(timezone.utc)
    return (reference - parse_time(value)).total_seconds()


def check_book(book, config, now=None):
    received_age = age_seconds(book["received_at"], now)
    maximum = float(config.get("max_quote_age_seconds", 120))
    if received_age < -10 or received_age > maximum:
        raise ValueError("REST quote is stale or dated in the future.")
    version = book.get("asOf")
    if version:
        version_age = age_seconds(version["at"], now)
        if version_age < -10 or version_age > maximum:
            raise ValueError("Engine book version is stale or dated in the future.")


def load_scenarios(path, forecasts, config, now=None):
    with np.load(path, allow_pickle=False) as data:
        ids = [str(value) for value in data["exchange_ids"]]
        raw_outcomes = np.asarray(data["outcomes"])
        if not np.isin(raw_outcomes, [0, 1]).all():
            raise ValueError("Joint scenarios contain nonbinary outcomes.")
        y = np.asarray(raw_outcomes, dtype=np.int8)
        generated = str(data["generated_at"].item())
    if generated != forecasts["generated_at"]:
        raise ValueError("Scenario and forecast generation timestamps differ.")
    if not (0 <= age_seconds(generated, now) <= config.get("max_forecast_age_hours", 6) * 3600):
        raise ValueError("Scenario/forecast generation is stale or future-dated.")
    if y.ndim != 2 or y.shape[1] != len(ids) or y.shape[0] < 1000 or len(set(ids)) != len(ids) or not np.isin(y, [0, 1]).all():
        raise ValueError("Malformed joint-outcome scenarios.")
    f_by_id = {str(row["exchange_id"]): row for row in forecasts["forecasts"]}
    if len(f_by_id) != len(forecasts["forecasts"]) or set(ids) != set(f_by_id):
        raise ValueError("Scenario and forecast exchange universes must match exactly.")
    probabilities = y.mean(axis=0)
    for i, exchange in enumerate(ids):
        if abs(probabilities[i] - float(f_by_id[exchange]["p_yes"])) > 1e-6:
            raise ValueError("Scenarios disagree with forecast probabilities.")
    return y, {exchange: i for i, exchange in enumerate(ids)}


def portfolio_wealth(snapshot, y, index):
    advances = sum(float(row["outstandingAdvance"]) for row in snapshot.get("collateral", {}).get("data", []))
    wealth = np.full(y.shape[0], float(snapshot["tournament"]["myBalance"]) - advances)
    for position in snapshot["positions"]["positions"]:
        quantity = float(position["quantity"])
        if position["settled"] or quantity == 0:
            continue
        exchange = str(position["exchangeId"])
        if exchange not in index:
            raise ValueError(f"Existing holding {exchange} lacks joint scenarios; cannot assess portfolio risk.")
        yes = y[:, index[exchange]]
        wealth += quantity * yes if quantity > 0 else -quantity * (1 - yes)
    return wealth


def wealth_report(wealth, equity, hurdle=None):
    ordered = np.sort(wealth)
    tail_size = max(1, math.ceil(len(ordered) * 0.05))
    result = {"expected_terminal_wealth": float(wealth.mean()),
              "terminal_wealth_5th_percentile": float(np.quantile(wealth, 0.05)),
              "worst_5pct_mean_terminal_wealth": float(ordered[:tail_size].mean()),
              "worst_5pct_mean_loss_fraction": float((equity - ordered[:tail_size].mean()) / equity)}
    if hurdle is not None:
        result["fixed_hurdle"] = float(hurdle)
        result["probability_exceeding_fixed_hurdle"] = float((wealth > hurdle).mean())
        result["hurdle_note"] = "Conditional on this model and a fixed target; this is not probability of winning."
    return result


def plan_entries(snapshot, forecasts, scenario_path, config, now=None):
    y, index = load_scenarios(scenario_path, forecasts, config, now)
    equity = float(snapshot["pnl"]["totalAccountValue"])
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("Account value must be positive and finite.")
    cash = float(snapshot["tournament"]["myBalance"])
    holdings = [p for p in snapshot["positions"]["positions"] if not p["settled"] and float(p["quantity"]) != 0]
    held = {str(p["exchangeId"]): p for p in holdings}
    risk_used = sum(max(0, float(p["costBasis"])) for p in holdings)
    baseline = portfolio_wealth(snapshot, y, index)
    if (baseline <= 0).any():
        raise ValueError("Portfolio can reach nonpositive terminal wealth under supplied scenarios.")
    baseline_log = float(np.log(baseline).mean())
    leaders = snapshot.get("leaderboard", {}).get("leaderboard", [])
    hurdle = config.get("fixed_wealth_hurdle")
    if hurdle is None and leaders:
        hurdle = float(snapshot["tournament"]["initialBalance"]) + max(float(row["pnl"]) for row in leaders)
    markets = {str(ex["id"]): market for market in snapshot["markets"] for ex in market["exchanges"]}
    candidates, skipped = [], []
    for forecast in forecasts["forecasts"]:
        exchange = str(forecast["exchange_id"])
        try:
            if exchange not in snapshot["books"] or exchange not in markets:
                raise ValueError("Exchange not included in this snapshot's covered book universe.")
            if forecast["title"] != markets[exchange]["title"] or markets[exchange]["status"] != "open":
                raise ValueError("Reviewed title does not match, or market is no longer open.")
            source_age = age_seconds(forecast["source_as_of"], now)
            if not 0 <= source_age <= float(config.get("max_input_age_hours", 168)) * 3600:
                raise ValueError("Underlying forecast inputs are stale or future-dated.")
            p, low, high = (float(forecast[key]) for key in ("p_yes", "p_low", "p_high"))
            if not all(math.isfinite(value) for value in (p, low, high)) or not 0 <= low <= p <= high <= 1:
                raise ValueError("Forecast probability/sensitivity bounds are invalid.")
            if not str(forecast.get("source", "")).strip():
                raise ValueError("No documented forecast source.")
            book = snapshot["books"][exchange]
            check_book(book, config, now)
            options = []
            for side, probability, robust_probability in (("yes", p, low), ("no", 1 - p, 1 - high)):
                quote = entry_quote(book, side)
                if quote:
                    price, depth = quote
                    edge = robust_probability - price - float(config.get("execution_buffer", 0.005))
                    options.append((edge, side, probability, robust_probability, price, depth))
            if not options:
                raise ValueError("No executable top-of-book liquidity.")
            edge, side, probability, robust_probability, price, depth = max(options)
            if edge < float(config.get("min_robust_edge", 0.03)):
                raise ValueError("No positive conservative edge above the configured threshold.")
            existing = held.get(exchange)
            if existing and ((float(existing["quantity"]) > 0) != (side == "yes")):
                raise ValueError("Opposite existing position: manage its close before adding a new side.")
            position_risk = 0 if existing is None else max(0, float(existing["costBasis"]))
            kelly = max(0, (robust_probability - price) / (1 - price))
            budget = min(equity * float(config.get("kelly_fraction", 0.15)) * kelly,
                         float(config.get("max_order_notional", 2000)),
                         equity * float(config.get("max_exchange_at_risk", 0.10)) - position_risk,
                         equity * float(config.get("max_total_at_risk", 0.45)) - risk_used,
                         cash - equity * float(config.get("cash_reserve_fraction", 0.20)))
            maximum = min(depth, max(0, math.floor(budget / price)))
            if maximum < 1:
                raise ValueError("No capacity after liquidity, cash, Kelly and position caps.")
            payout = y[:, index[exchange]] if side == "yes" else 1 - y[:, index[exchange]]
            best = None
            for quantity in sorted({max(1, math.floor(maximum * fraction)) for fraction in (0.25, 0.5, 0.75, 1)}):
                proposed = baseline + quantity * (payout - price)
                if (proposed <= 0).any():
                    continue
                report = wealth_report(proposed, equity, hurdle)
                if report["worst_5pct_mean_loss_fraction"] > config.get("max_tail_loss_fraction", 0.35):
                    continue
                log_gain = float(np.log(proposed).mean()) - baseline_log
                if log_gain > 0 and (best is None or log_gain > best["expected_log_wealth_gain"]):
                    best = {"exchange_id": exchange, "market_id": str(markets[exchange]["id"]),
                            "title": forecast["title"], "side": side, "action": "buy",
                            "quantity": quantity, "limit_price": price, "notional_cap": quantity * price,
                            "forecast_probability": probability, "robust_probability": robust_probability,
                            "robust_edge_after_buffer": edge, "expected_log_wealth_gain": log_gain,
                            "portfolio_if_fully_filled": report,
                            "resolution_reviewed": forecast.get("resolution_reviewed", False),
                            "forecast_approved": forecast.get("approved", False),
                            "model_validated": forecasts.get("validated", False)}
            if best:
                candidates.append(best)
            else:
                raise ValueError("Candidate fails terminal portfolio risk/log-growth checks.")
        except (ValueError, KeyError) as error:
            skipped.append({"exchange_id": exchange, "reason": str(error)})
    candidates.sort(key=lambda row: row["expected_log_wealth_gain"], reverse=True)
    return {"baseline_portfolio": wealth_report(baseline, equity, hurdle),
            "candidates": candidates, "skipped": skipped,
            "note": "Each candidate is sized separately against the current portfolio; execute one, then reconcile."}


def bundle_alerts(snapshot, groups, config, now=None):
    alerts = []
    for group in groups:
        try:
            if not group.get("settlement_reviewed"):
                continue
            legs = group["legs"]
            if not legs or len(legs) > 10 or not group["allowed_outcomes"]:
                raise ValueError("Bundle requires 1-10 legs and explicit exhaustive allowed outcomes.")
            quotes = []
            for leg in legs:
                book = snapshot["books"][str(leg["exchange_id"])]
                check_book(book, config, now)
                quote = entry_quote(book, leg["side"])
                if quote is None:
                    raise ValueError("Bundle leg has no executable top-of-book liquidity.")
                quotes.append(quote)
            floor = math.inf
            for outcome in group["allowed_outcomes"]:
                payout = 0
                for leg in legs:
                    value = outcome[str(leg["exchange_id"])]
                    if value not in (0, 1):
                        raise ValueError("Allowed outcomes must be binary.")
                    payout += value if leg["side"] == "yes" else 1 - value
                floor = min(floor, payout)
            cost = sum(price for price, quantity in quotes)
            buffer = len(legs) * float(config.get("execution_buffer", 0.005))
            if floor > cost + buffer:
                alerts.append({"group_id": group["group_id"], "cost_per_bundle_limit": cost,
                               "payout_floor_under_declared_outcomes": floor,
                               "edge_after_buffer": floor - cost - buffer,
                               "top_level_quantity": min(quantity for price, quantity in quotes),
                               "legs": legs, "auto_execution_enabled": False,
                               "note": "Conditional on correct settlement enumeration and every leg filling. Atomic placement does not guarantee matched fills."})
        except (ValueError, KeyError) as error:
            alerts.append({"group_id": group.get("group_id"), "error": str(error), "auto_execution_enabled": False})
    return alerts
