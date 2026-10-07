import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cupbot.api import API, APIError
from cupbot.autonomous import AutonomousWorker, acknowledge_partial, resume_worker, verify_state_disk
from cupbot.primary_data import monitor_primary_sources, normalize_research, source_url
from cupbot.runtime import read_json
from cupbot.structural import BasketJournal, plan_no_bundle, review_party_bundle
from test_structural import fixture, TID

ROOT = Path(__file__).parent.parent


def worker_config():
    config = read_json(ROOT / "config.autonomous.json")
    config.update(tournament_slug="example", expected_tournament_name="Example", tournament_id=TID,
                  trading_deadline_utc="2099-01-01T00:00:00Z", worker_research_path=None,
                  worker_source_monitor_enabled=False, worker_max_reviews_per_cycle=6)
    return config


class ElectionAPI:
    """Account-aware exchange fixture with durable server-side placement deduplication."""
    def __init__(self, fill_fraction=1, lost_response=False):
        candidate, self.nodes, self.books, _ = fixture()
        self.markets = [{"id": leg["market_id"], "title": leg["title"], "status": "open",
                         "exchanges": [{"id": leg["exchange_id"]}]} for leg in candidate["legs"]]
        self.cash, self.equity_override = 100000.0, None
        self.positions, self.orders, self.fills = {}, {}, {}
        self.posts, self.deletes, self.server_effects = [], [], 0
        self.saved, self.fill_fraction, self.lost_response = {}, fill_fraction, lost_response
        self.read_error, self.after_book = None, None
        self.profile_id = read_json(ROOT / "config.autonomous.json")["expected_profile_id"]

    def pages(self, path, **params):
        if path.endswith("/markets"):
            return copy.deepcopy(self.markets)
        if path == "/orders":
            return [dict(order, id=oid) for oid, order in self.orders.items() if order["open"]]
        raise AssertionError(path)

    def get(self, path, **params):
        if self.read_error:
            raise self.read_error
        if path == "/account":
            return {"id": self.profile_id}
        if path == "/tournaments/example":
            return {"id": TID, "name": "Example", "myBalance": self.cash, "status": "active",
                    "startDate": "2020-01-01T00:00:00Z", "endDate": "2099-01-01T00:00:00Z"}
        if path.endswith("/portfolio/positions"):
            return {"positions": [dict(p) for p in self.positions.values()]}
        if path.endswith("/portfolio/pnl"):
            equity = self.cash + sum(p["costBasis"] for p in self.positions.values())
            return {"totalAccountValue": self.equity_override if self.equity_override is not None else equity}
        if path == "/portfolio/collateral":
            return {"data": []}
        if path == "/exchanges/prices":
            return {"missingIds": [], "data": [{"exchangeId": eid, "marketId": self.books[eid]["marketId"],
                                                "bestBid": self.books[eid]["bids"][0]["price"], "bestAsk": None}
                                               for eid in params["ids"].split(",")]}
        if path.endswith("/nodes"):
            return copy.deepcopy(self.nodes[path.split("/")[2]])
        if path.endswith("/orderbook"):
            result = copy.deepcopy(self.books[path.split("/")[2]])
            if self.after_book:
                self.after_book()
            return result
        if path.endswith("/fills"):
            return copy.deepcopy(self.fills[int(path.split("/")[2])])
        if path.startswith("/orders/"):
            return copy.deepcopy(self.orders[int(path.split("/")[2])])
        raise AssertionError(path)

    def post(self, path, payload):
        self.posts.append((path, copy.deepcopy(payload)))
        if payload["idempotencyKey"] in self.saved:
            return copy.deepcopy(self.saved[payload["idempotencyKey"]])
        self.server_effects += 1
        results = []
        for i, leg in enumerate(payload["legs"]):
            oid = len(self.orders) + 1
            eid = str(leg["exchangeId"])
            quantity = int(leg["quantity"] * self.fill_fraction) if i == 0 else leg["quantity"]
            price, cost = leg["price"], quantity * leg["price"]
            self.cash -= cost
            previous = self.positions.get(eid, {"quantity": 0, "costBasis": 0})
            self.positions[eid] = {"exchangeId": eid, "marketId": self.books[eid]["marketId"], "settled": False,
                                   "quantity": previous["quantity"] - quantity, "costBasis": previous["costBasis"] + cost}
            self.orders[oid] = {"tournamentId": TID, "exchangeId": eid, "side": "no", "action": "buy",
                                "open": quantity < leg["quantity"]}
            self.fills[oid] = {"tournamentId": TID, "totalQuantityFilled": -quantity,
                               "avgFillPrice": price if quantity else None, "pagination": {"hasMore": False},
                               "data": [{"side": "no", "quantity": -quantity, "price": price}] if quantity else []}
            results.append({"index": i, "data": {"orderId": oid, "exchangeId": eid,
                                                   "open": quantity < leg["quantity"], "quantityTraded": quantity,
                                                   "totalCost": cost, "all": {"fullNotionalCost": cost}}})
        response = {"results": results}
        self.saved[payload["idempotencyKey"]] = response
        if self.lost_response:
            self.lost_response = False
            raise TimeoutError("Accepted placement response lost")
        return copy.deepcopy(response)

    def request(self, method, path):
        if method != "DELETE":
            raise AssertionError(method)
        self.deletes.append(path)
        self.orders[int(path.split("/")[2])]["open"] = False


class WorkerTests(unittest.TestCase):
    def make(self, directory, api=None, live=False, config=None):
        worker = AutonomousWorker(api or ElectionAPI(), config or worker_config(), directory, live)
        self.addCleanup(worker.close)
        return worker

    def test_read_only_scan_reviews_metadata_and_never_writes_to_exchange(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            result = self.make(directory, api).step()
            self.assertEqual(result["quote_count"], 3)
            self.assertTrue(result["eligible"])
            self.assertGreater(result["eligible"][0]["plan"]["normal_settlement_gain_floor_at_limits"], 0)
            self.assertEqual(api.posts + api.deletes, [])
            self.assertFalse(result["directional_trading_enabled"])

    def test_live_checks_account_cash_and_positions_before_clearing_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            result = self.make(directory, api, True).step()
            self.assertTrue(result["placed"])
            reconciliation = result["execution"]["reconciliation"]
            self.assertTrue(reconciliation["account_verification"]["position_deltas_match"])
            self.assertAlmostEqual(100000 - api.cash, reconciliation["nominal_entry_cost"])
            journal = BasketJournal(Path(directory) / "basket_operations.sqlite3")
            self.assertEqual(journal.unresolved(), [])
            journal.close()

    def test_lost_response_recovers_on_restart_with_no_duplicate_economic_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI(lost_response=True)
            config = dict(worker_config(), max_orders_per_day=1)
            first = AutonomousWorker(api, config, directory, True)
            uncertain = first.step()
            self.assertEqual(uncertain["state"], "retry_wait")
            self.assertIsNone(uncertain["placed"])
            first.close()
            second = self.make(directory, api, True, config)
            result = second.step()
            self.assertEqual(api.server_effects, 1)
            self.assertEqual(api.posts[0], api.posts[1])
            self.assertEqual(len(api.posts), 2)
            self.assertEqual(result["recovered_baskets"], 1)

    def test_partial_fills_cancel_remainders_and_halt_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI(fill_fraction=.5)
            first = AutonomousWorker(api, worker_config(), directory, True)
            result = first.step()
            self.assertEqual(result["state"], "halted")
            self.assertTrue(api.deletes)
            self.assertFalse(any(o["open"] for o in api.orders.values()))
            first.close()
            self.assertEqual(self.make(directory, api, True).step()["state"], "halted")
            self.assertEqual(len(api.posts), 1)
            with self.assertRaises(ValueError):
                resume_worker(directory)

    def test_operator_partial_review_records_exposure_without_new_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI(fill_fraction=.5)
            self.make(directory, api, True).step()
            journal = BasketJournal(Path(directory) / "basket_operations.sqlite3")
            key = journal.unresolved()[0][0]
            journal.close()
            acknowledge_partial(api, worker_config(), directory, key, "Residual exposure reviewed and accepted by operator")
            resume_worker(directory)
            self.assertEqual(len(api.posts), 1)
            self.assertFalse(Path(directory, "HALT.json").exists())

    def test_unresolved_pending_order_cannot_be_acknowledged_as_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI(lost_response=True)
            self.make(directory, api, True).step()
            key = api.posts[0][1]["idempotencyKey"]
            with self.assertRaises(ValueError):
                acknowledge_partial(api, worker_config(), directory, key, "cannot discard an unknown placement")
            self.assertEqual(len(api.posts), 1)

    def test_stop_file_and_shutdown_event_prevent_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            Path(directory, "STOP").touch()
            self.assertEqual(self.make(directory, api, True).step()["state"], "paused")
            self.assertFalse(api.posts)
        with tempfile.TemporaryDirectory() as directory:
            api, stop = ElectionAPI(), threading.Event()
            api.after_book = stop.set
            worker = AutonomousWorker(api, worker_config(), directory, True, stop)
            try:
                worker.step()
                self.assertFalse(api.posts)
            finally:
                worker.close()

    def test_permission_failure_latches_halt_without_attempting_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            api.read_error = APIError(403, {"error": {"code": "PERMISSION_DENIED"}})
            result = self.make(directory, api, True).step()
            self.assertEqual(result["state"], "halted")
            self.assertTrue(Path(directory, "HALT.json").exists())
            self.assertFalse(api.posts)

    def test_repeated_transport_failure_stops_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            api.read_error = TimeoutError("temporary outage")
            worker = self.make(directory, api, True)
            self.assertEqual(worker.step()["state"], "retry_wait")
            self.assertEqual(worker.step()["state"], "retry_wait")
            self.assertEqual(worker.step()["state"], "halted")

    def test_deadline_stops_without_new_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            config = dict(worker_config(), trading_deadline_utc="2020-01-01T00:00:00Z")
            self.assertEqual(self.make(directory, api, True, config).step()["state"], "finished")
            self.assertFalse(api.posts)

    def test_drawdown_high_water_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            first = AutonomousWorker(api, worker_config(), directory)
            first.step()
            first.close()
            api.equity_override = 79000
            result = self.make(directory, api).step()
            self.assertEqual(result["state"], "halted")

    def test_metadata_mismatch_and_stale_depth_cannot_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            for node in api.nodes.values():
                node["root"]["contract_details"]["stageId"] = node["market_id"]
            result = self.make(directory, api, True).step()
            self.assertEqual(result["eligible"], [])
            self.assertFalse(api.posts)
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            for book in api.books.values():
                book["asOf"] = {"at": "2020-01-01T00:00:00Z", "sequence": 1}
            result = self.make(directory, api, True).step()
            self.assertEqual(result["eligible"], [])
            self.assertFalse(api.posts)

    def test_paper_mode_does_not_replay_a_pending_live_request(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI(lost_response=True)
            first = AutonomousWorker(api, worker_config(), directory, True)
            first.step()
            first.close()
            result = self.make(directory, api).step()
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(len(api.posts), 1)

    def test_state_directory_cannot_switch_tournaments(self):
        with tempfile.TemporaryDirectory() as directory:
            first = AutonomousWorker(ElectionAPI(), worker_config(), directory)
            first.close()
            config = dict(worker_config(), tournament_id="550e8400-e29b-41d4-a716-446655440000")
            with self.assertRaises(ValueError):
                AutonomousWorker(ElectionAPI(), config, directory)

    def test_another_participants_api_key_cannot_access_the_order_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            api.profile_id = "550e8400-e29b-41d4-a716-446655440000"
            result = self.make(directory, api, True).step()
            self.assertEqual(result["state"], "halted")
            self.assertFalse(api.posts)

    def test_render_live_refuses_ephemeral_disk(self):
        with patch.dict("os.environ", {"RENDER": "true", "RENDER_INSTANCE_ID": "test"}), patch("os.path.ismount", return_value=False):
            with self.assertRaises(RuntimeError):
                verify_state_disk("/var/data/sig-cup")

    def test_overlapping_subset_counts_entire_existing_race_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            api.positions["11"] = {"exchangeId": "11", "marketId": "1", "quantity": -100,
                                    "costBasis": 11990, "settled": False}
            config = dict(worker_config(), structural_min_edge=.001)
            worker = self.make(directory, api, True, config)
            result = worker.step()
            if result["placed"]:
                self.assertLessEqual(result["execution"]["plan"]["limit_notional"], 10)
            for item in result["eligible"]:
                self.assertIn("11", item["race_ids"])
                self.assertLessEqual(item["plan"]["limit_notional"], 10)

    def test_account_disagreement_leaves_confirmed_journal_for_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            api = ElectionAPI()
            original = api.post
            def inconsistent(path, payload):
                response = original(path, payload)
                api.cash -= 1
                return response
            api.post = inconsistent
            result = self.make(directory, api, True).step()
            self.assertEqual(result["state"], "halted")
            journal = BasketJournal(Path(directory) / "basket_operations.sqlite3")
            self.assertEqual(journal.unresolved()[0][3], "confirmed")
            journal.close()


class DepthAndDataTests(unittest.TestCase):
    def test_incomplete_projection_read_is_retried_then_fails_closed(self):
        api = API(key="fake-not-a-credential", sleep=lambda _: None,
                  transport=lambda *_: (200, {"coverage": {"complete": False}, "data": []}, {}))
        with self.assertRaises(APIError) as raised:
            api.get("/orders")
        self.assertEqual(raised.exception.code, "INCOMPLETE_READ_COVERAGE")
    def test_depth_optimizer_can_use_more_than_the_best_price_level(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        books["13"]["bids"] = [{"price": .05, "quantity": 100}, {"price": .03, "quantity": 400}]
        config.update(structural_depth_enabled=True)
        plan = plan_no_bundle(reviewed, books, 100000, config, max_notional=1000, max_shares=500)
        self.assertEqual(plan["quantity_per_leg"], 500)
        self.assertAlmostEqual(plan["limit_notional"], 960)
        self.assertAlmostEqual(plan["normal_settlement_gain_floor_at_limits"], 40)

    def test_depth_optimizer_respects_budget_and_blocks_nonfinite_levels(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        config.update(structural_depth_enabled=True)
        plan = plan_no_bundle(reviewed, books, 100000, config, max_notional=20, max_shares=500)
        self.assertLessEqual(plan["limit_notional"], 20)
        books["11"]["bids"][0]["quantity"] = float("nan")
        with self.assertRaises(ValueError):
            plan_no_bundle(reviewed, books, 100000, config, max_notional=20, max_shares=500)

    def test_source_change_requires_review_even_on_later_unchanged_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.json"
            url = "https://maristpoll.marist.edu/polls/example/"
            a = monitor_primary_sources([url], path, lambda _: b"initial")
            b = monitor_primary_sources([url], path, lambda _: b"updated")
            c = monitor_primary_sources([url], path, lambda _: b"updated")
            self.assertEqual(a["last_checks"][0]["status"], "baseline")
            self.assertEqual(b["last_checks"][0]["status"], "changed_requires_review")
            self.assertTrue(c["last_checks"][0]["needs_review"])
            self.assertFalse(c["last_checks"][0]["approved_for_trading"])

    def test_source_monitor_rejects_credentials_http_and_nonprimary_hosts(self):
        for url in ["http://maristpoll.marist.edu/", "https://secret@maristpoll.marist.edu/", "https://example.com/"]:
            with self.assertRaises(ValueError):
                source_url(url)

    def test_real_research_preserves_nested_populations_and_full_tables(self):
        payload = read_json(ROOT / "data/polling_research.json")
        result = normalize_research(payload)
        wisconsin = [r for r in result["observations"] if r["race"] == "Wisconsin Governor"]
        self.assertEqual({r["population"] for r in wisconsin}, {"likely voters", "registered voters"})
        self.assertEqual(len({r["survey_id"] for r in wisconsin}), 1)
        self.assertTrue(all(r["election_win_probability"] is None for r in result["observations"]))
        self.assertTrue(all("source_record" in r for r in result["observations"]))

    def test_poll_duplicates_are_not_independent_observations(self):
        base = {"survey_id": "one", "release_id": "one", "population": "likely voters", "published_on": "2026-10-01",
                "races": [{"race_label": "Example", "candidate_support_percent": [{"name": "A", "support": 51}],
                           "additional_response_percent": {"Refused": "<1"}}]}
        result = normalize_research({"poll_releases": [base, copy.deepcopy(base)]}, date(2026,10,7))
        self.assertEqual(result["observation_count"], 1)
        self.assertEqual(result["observations"][0]["additional_response_percent"]["Refused"], "<1")
        changed = copy.deepcopy(base)
        changed["races"][0]["candidate_support_percent"][0]["support"] = 52
        with self.assertRaises(ValueError):
            normalize_research({"poll_releases": [base, changed]}, date(2026,10,7))


if __name__ == "__main__":
    unittest.main()
