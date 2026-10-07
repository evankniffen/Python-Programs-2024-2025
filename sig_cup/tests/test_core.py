"""Behavioral checks for execution/risk failures; all market data here is fictional."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from cupbot.api import API, APIError, RateBudget
from cupbot.model import fit_elections, score_forecasts, utc_now
from cupbot.runtime import (Journal, execute_once, inspect_and_cancel_remainder,
                            recover_pending, resolve_tournament, write_json)
from cupbot.strategy import buy_limit, entry_quote, load_scenarios, plan_entries, portfolio_wealth


ROOT = Path(__file__).resolve().parents[1]
TOURNAMENT_ID = "00000000-0000-4000-8000-000000000001"


def fixture(directory, probability=.8):
    directory = Path(directory)
    generation = utc_now()
    config = json.loads((ROOT / "config.example.json").read_text())
    config.update(tournament_id=TOURNAMENT_ID, tournament_slug="fictional-test",
                  expected_tournament_name="Fictional Midterm Test", live_enabled=True)
    tournament = {"id": TOURNAMENT_ID, "slug": "fictional-test", "name": "Fictional Midterm Test",
                  "initialBalance": 100000, "myBalance": 100000, "status": "active",
                  "startDate": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                  "endDate": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    title = "FICTIONAL: test candidate wins"
    book = {"exchangeId": "99001", "marketId": "99901", "asOf": {"at": generation, "sequence": 1},
            "received_at": generation, "asks": [{"price": .4, "quantity": 10000}],
            "bids": [{"price": .35, "quantity": 10000}]}
    if probability < .5:
        book["asks"][0]["price"] = .65
        book["bids"][0]["price"] = .60
    snapshot = {"captured_at": generation, "tournament": tournament,
                "markets": [{"id": "99901", "title": title, "status": "open", "exchanges": [{"id": "99001"}]}],
                "books": {"99001": book}, "positions": {"positions": []},
                "pnl": {"totalAccountValue": 100000}, "open_orders": [], "collateral": {"data": []},
                "leaderboard": {"leaderboard": [{"pnl": 20000}]}, "coverage": {"books_collected": 1}}
    y = np.zeros((2000, 1), dtype=np.int8)
    y[:int(probability * 2000), 0] = 1
    forecasts = {"generated_at": generation, "validated": True,
                 "forecasts": [{"exchange_id": "99001", "title": title, "p_yes": probability,
                                "p_low": probability - .05, "p_high": probability + .05,
                                "source": "Fictional test", "source_as_of": generation,
                                "resolution_reviewed": True, "approved": True}]}
    write_json(directory / "forecasts.json", forecasts)
    np.savez_compressed(directory / "scenarios.npz", outcomes=y,
                        exchange_ids=np.array(["99001"]), generated_at=np.array(generation))
    return config, snapshot, forecasts, directory / "scenarios.npz", y


class FakeTradingAPI:
    def __init__(self, snapshot, lost=False):
        self.snapshot = snapshot
        self.posts, self.deletes = [], []
        self.open = True
        self.lost = lost
        self.response = {"orderId": 1001, "open": True, "quantityTraded": 100,
                         "fillPrice": .4, "totalCost": 40, "all": None}

    def get(self, path, **params):
        if path.startswith("/tournaments/"):
            if path.endswith("/portfolio/positions"):
                return self.snapshot["positions"]
            if path.endswith("/portfolio/pnl"):
                return self.snapshot["pnl"]
            return self.snapshot["tournament"]
        if path.endswith("/orderbook"):
            return deepcopy(self.snapshot["books"]["99001"])
        if path.endswith("/fills"):
            return {"tournamentId": TOURNAMENT_ID, "data": [{"price": .4, "quantity": 100}],
                    "totalQuantityFilled": 100, "avgFillPrice": .4,
                    "pagination": {"hasMore": False}, "coverage": {"complete": True}}
        if path == "/orders/1001":
            return {"id": 1001, "open": self.open, "tournamentId": TOURNAMENT_ID}
        raise AssertionError(path)

    def post(self, path, body):
        self.posts.append(deepcopy(body))
        if self.lost:
            self.lost = False
            raise TimeoutError("Simulated lost response AFTER server acceptance")
        return deepcopy(self.response)

    def request(self, method, path, **kwargs):
        assert method == "DELETE" and path == "/orders/1001"
        self.deletes.append(path)
        self.open = False


class APIBehavior(unittest.TestCase):
    def test_no_secret_forwarding_or_unofficial_base(self):
        for url in ("http://sig.thesuper.market/api/v1", "https://evil.example/api/v1", "https://sig.thesuper.market/api/v1?token=x"):
            with self.assertRaises(ValueError):
                API(url, key="fictional")

    def test_transport_retry_keeps_exact_order_identity(self):
        seen = []
        body = {"idempotencyKey": "test-operation", "quantity": 10}
        def transport(method, url, payload):
            seen.append(deepcopy(payload))
            if len(seen) == 1:
                raise TimeoutError("Lost acknowledgement")
            return 200, {"orderId": 1}, {}
        api = API(key="fictional", transport=transport, sleep=lambda value: None)
        self.assertEqual(api.post("/orders", body)["orderId"], 1)
        self.assertEqual(seen, [body, body])

    def test_does_not_retry_terminal_permission_error(self):
        seen = []
        def transport(*args):
            seen.append(1)
            return 403, {"error": {"code": "TERMS_NOT_ACKNOWLEDGED"}}, {}
        with self.assertRaises(APIError):
            API(key="fictional", transport=transport).get("/account")
        self.assertEqual(len(seen), 1)

    def test_rate_budget_waits_before_exceeding_read_limit(self):
        clock = [0.0]
        waits = []
        def sleep(delay):
            waits.append(delay)
            clock[0] += delay
        budget = RateBudget(reads=2, writes=1, clock=lambda: clock[0], sleep=sleep)
        for _ in range(3):
            budget.acquire("GET")
        self.assertGreaterEqual(clock[0], 61)
        self.assertTrue(waits)

    def test_cursor_pagination_does_not_return_incomplete_rows(self):
        api = API(key="fictional", transport=lambda *args: (200, {"data": [1], "pagination": {"hasMore": True}}, {}))
        with self.assertRaises(RuntimeError):
            api.pages("/orders")


class ModelAndRisk(unittest.TestCase):
    def test_no_buy_price_uses_complement_of_yes_bid(self):
        book = {"bids": [{"price": .535, "quantity": 9.9}], "asks": [{"price": .55, "quantity": 20}]}
        self.assertEqual(entry_quote(book, "no"), (.465, 9))
        self.assertEqual(entry_quote(book, "yes"), (.55, 20))
        self.assertEqual(buy_limit(.421), .425)

    def test_positive_and_negative_position_payouts(self):
        with tempfile.TemporaryDirectory() as directory:
            _, snapshot, _, _, y = fixture(directory)
            snapshot["tournament"]["myBalance"] = 100
            snapshot["positions"]["positions"] = [{"exchangeId": "99001", "quantity": -10, "settled": False}]
            wealth = portfolio_wealth(snapshot, y, {"99001": 0})
            self.assertEqual(wealth[0], 100)
            self.assertEqual(wealth[-1], 110)

    def test_model_shared_errors_and_chamber_consistency(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = fit_elections(ROOT / "examples/polls.example.csv", ROOT / "examples/mapping.example.json", directory,
                                    samples=20000, seed=1, as_of="2026-10-07T00:00:00+00:00")
            with np.load(Path(directory) / "scenarios.npz") as data:
                y = data["outcomes"]
            self.assertGreater(np.corrcoef(y[:, 0], y[:, 1])[0, 1], .05)
            self.assertTrue(np.array_equal(y[:, 2], y[:, 0] & y[:, 1]))
            self.assertFalse(payload["validated"])
            self.assertGreater(payload["margin_covariance"][0][1], 0)

    def test_risk_sizing_respects_depth_notional_and_no_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, scenario_path, y = fixture(directory, .2)
            snapshot["books"]["99001"]["bids"][0]["quantity"] = 300
            candidate = plan_entries(snapshot, forecasts, scenario_path, config)["candidates"][0]
            self.assertEqual(candidate["side"], "no")
            self.assertLessEqual(candidate["quantity"], 300)
            self.assertLessEqual(candidate["notional_cap"], config["max_order_notional"])

    def test_stale_quotes_and_inconsistent_scenarios_cannot_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, path, y = fixture(directory)
            snapshot["books"]["99001"]["received_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            self.assertFalse(plan_entries(snapshot, forecasts, path, config)["candidates"])
            forecasts["forecasts"][0]["p_yes"] = .9
            with self.assertRaises(ValueError):
                load_scenarios(path, forecasts, config)

    def test_unmodeled_existing_holding_blocks_portfolio_sizing(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, path, y = fixture(directory)
            snapshot["positions"]["positions"] = [{"exchangeId": "777", "quantity": 10, "settled": False, "costBasis": 5}]
            with self.assertRaises(ValueError):
                plan_entries(snapshot, forecasts, path, config)

    def test_calibration_score_rejects_post_event_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "history.csv"
            history.write_text("forecast_as_of,event_date,event_id,p_yes,benchmark_p_yes,resolved_yes\n2022-12-01,2022-11-08,test,.9,.8,1\n")
            with self.assertRaises(ValueError):
                score_forecasts(history)

    def test_calibration_bin_boundaries_cover_every_observation(self):
        report = score_forecasts(ROOT / "examples/history.example.csv")
        self.assertEqual(sum(row["n"] for row in report["calibration"]), report["n"])


class ExecutionBehavior(unittest.TestCase):
    def test_wrong_tournament_identity_blocks_routing(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, _, _, _ = fixture(directory)
            snapshot["tournament"]["id"] = "some-other-tournament"
            with self.assertRaises(ValueError):
                resolve_tournament(FakeTradingAPI(snapshot), config)

    def test_partial_fill_remainder_cancelled_and_journal_reconciled(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, path, _ = fixture(directory)
            api = FakeTradingAPI(snapshot)
            with patch("cupbot.runtime.collect_snapshot", return_value=snapshot):
                result = execute_once(api, config, Path(directory) / "forecasts.json", path, directory)
            self.assertTrue(result["placed"])
            self.assertEqual(api.deletes, ["/orders/1001"])
            self.assertEqual(api.posts[0]["tournamentId"], TOURNAMENT_ID)
            self.assertEqual(api.posts[0]["price"], .4)
            journal = Journal(Path(directory) / "operations.sqlite3")
            self.assertFalse(journal.has_unreconciled())
            journal.close()

    def test_lost_response_requires_same_key_recovery_before_new_request(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, path, _ = fixture(directory)
            api = FakeTradingAPI(snapshot, lost=True)
            with patch("cupbot.runtime.collect_snapshot", return_value=snapshot):
                with self.assertRaises(TimeoutError):
                    execute_once(api, config, Path(directory) / "forecasts.json", path, directory)
                with self.assertRaises(ValueError):
                    execute_once(api, config, Path(directory) / "forecasts.json", path, directory)
            journal = Journal(Path(directory) / "operations.sqlite3")
            self.assertEqual(len(journal.pending()), 1)
            recover_pending(api, journal, config)
            self.assertEqual(api.posts[0], api.posts[1])
            self.assertFalse(journal.has_unreconciled())
            journal.close()

    def test_live_refuses_unvalidated_model_and_existing_open_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            config, snapshot, forecasts, path, _ = fixture(directory)
            forecasts["validated"] = False
            write_json(Path(directory) / "forecasts.json", forecasts)
            api = FakeTradingAPI(snapshot)
            with self.assertRaises(ValueError):
                execute_once(api, config, Path(directory) / "forecasts.json", path, directory)
            forecasts["validated"] = True
            write_json(Path(directory) / "forecasts.json", forecasts)
            snapshot["open_orders"] = [{"id": 10}]
            with patch("cupbot.runtime.collect_snapshot", return_value=snapshot):
                with self.assertRaises(ValueError):
                    execute_once(api, config, Path(directory) / "forecasts.json", path, directory)
            self.assertFalse(api.posts)


if __name__ == "__main__":
    unittest.main()
