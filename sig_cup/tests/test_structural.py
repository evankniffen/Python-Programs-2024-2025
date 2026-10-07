import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from cupbot.runtime import read_json
from cupbot.structural import (BasketJournal, collect_quotes, execute_no_bundle, no_payout_floor,
                              plan_no_bundle, reconcile_basket, review_party_bundle,
                              screen_party_bundles, recover_baskets)

TID = "bda92870-621e-47b0-bc3c-3602c5c26f55"


def fixture():
    legs, nodes, books = [], {}, {}
    for index, (party, bid) in enumerate([("Democratic", .92), ("Republican", .13), ("Independent", .05)]):
        mid, eid = str(index + 1), str(index + 11)
        title = f"Will the {party} Party win the Example Governor?"
        legs.append({"party": party, "market_id": mid, "exchange_id": eid, "title": title, "best_bid": bid})
        nodes[mid] = {"market_id": mid, "contexts": [{"type": "tournament", "tournament": {"id": TID}}],
                      "root": {"node_type": "contract", "contract_type": "Election Outcome",
                               "title": title, "settled_with": None, "settlement_date": "2026-11-04T17:00:00Z",
                               "contract_details": {"raceId": "1", "stageId": "2", "raceName": "Example Governor",
                                                    "raceStage": "General", "electionDate": "2026-11-03",
                                                    "usState": "RI", "officeLevel": "State", "resolutionType": "Party Winner",
                                                    "winnerName": party if party == "Independent" else party + " Party"}}}
        books[eid] = {"exchangeId": eid, "marketId": mid,
                      "received_at": datetime.now(timezone.utc).isoformat(), "asOf": None,
                      "bids": [{"price": bid, "quantity": 1000}], "asks": []}
    candidate = {"race": "Example Governor", "legs": legs, "metadata_reviewed": False}
    config = read_json(Path(__file__).parent.parent / "config.example.json")
    return candidate, nodes, books, config


class StructuralTests(unittest.TestCase):
    def test_same_race_metadata_and_price_floor(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        plan = plan_no_bundle(reviewed, books, 100000, config)
        self.assertEqual(plan["quantity_per_leg"], 100)
        self.assertAlmostEqual(plan["limit_notional"], 190)
        self.assertAlmostEqual(plan["normal_settlement_gain_floor_at_limits"], 10)

    def test_titles_cannot_authorize_execution(self):
        candidate, nodes, books, config = fixture()
        with self.assertRaises(ValueError):
            plan_no_bundle(candidate, books, 100000, config)

    def test_different_race_stage_rejected(self):
        candidate, nodes, _, _ = fixture()
        nodes["2"]["root"]["contract_details"]["stageId"] = "another-stage"
        with self.assertRaises(ValueError):
            review_party_bundle(candidate, nodes, TID)

    def test_out_of_scope_resolution_rejected(self):
        candidate, nodes, _, _ = fixture()
        nodes["2"]["contexts"] = []
        with self.assertRaises(ValueError):
            review_party_bundle(candidate, nodes, TID)

    def test_duplicate_winner_rejected(self):
        candidate, nodes, _, _ = fixture()
        candidate["legs"][1]["party"] = "Democratic"
        nodes["2"]["root"]["contract_details"]["winnerName"] = "Democratic Party"
        with self.assertRaises(ValueError):
            review_party_bundle(candidate, nodes, TID)

    def test_book_identity_and_depth_caps(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        books["13"]["bids"][0]["quantity"] = 7
        self.assertEqual(plan_no_bundle(reviewed, books, 100000, config)["quantity_per_leg"], 7)
        books["13"]["marketId"] = "other"
        with self.assertRaises(ValueError):
            plan_no_bundle(reviewed, books, 100000, config)

    def test_edge_disappears_before_execution(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        books["11"]["bids"][0]["price"] = .80
        with self.assertRaises(ValueError):
            plan_no_bundle(reviewed, books, 100000, config)

    def test_partial_fill_payout_floor(self):
        self.assertEqual(no_payout_floor([100, 100, 0]), 100)
        self.assertEqual(no_payout_floor([100, 0, 0]), 0)
        self.assertEqual(no_payout_floor([100, 80, 40]), 120)
        with self.assertRaises(ValueError):
            no_payout_floor([100, -1, 0])

    def test_journal_is_durable_and_partial_is_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "basket.sqlite3"
            payload = {"idempotencyKey": "same-key", "legs": [{"quantity": 100, "price": .95}]}
            journal = BasketJournal(path);journal.create(payload, {"race": "example"});journal.close()
            journal = BasketJournal(path)
            self.assertEqual(json.loads(journal.unresolved()[0][1]), payload)
            journal.confirmed("same-key", {"results": []})
            journal.finish("same-key", {"balanced_full_fill": False})
            self.assertEqual(journal.unresolved()[0][3], "partial")
            journal.close()

    def test_reconciliation_uses_outcome_relative_no_fills_and_detects_partial(self):
        payload = {"legs": [{"exchangeId": "11", "quantity": 100, "price": .08},
                            {"exchangeId": "12", "quantity": 100, "price": .87},
                            {"exchangeId": "13", "quantity": 100, "price": .95}]}
        response = {"results": [{"index": i, "data": {"orderId": i + 1, "exchangeId": leg["exchangeId"],
                                                       "open": False, "quantityTraded": 100 if i < 2 else 0,
                                                       "totalCost": leg["price"] * 100 if i < 2 else 0}}
                                for i, leg in enumerate(payload["legs"])]}

        class FilledAPI:
            def get(self, path, **params):
                index = int(path.split("/")[2]) - 1
                if path.endswith("/fills"):
                    q = -100 if index < 2 else 0
                    price = payload["legs"][index]["price"]
                    return {"tournamentId": TID, "totalQuantityFilled": q, "avgFillPrice": price if q else None,
                            "pagination": {"hasMore": False}, "data": [{"side": "no"}] if q else []}
                return {"tournamentId": TID, "open": False, "exchangeId": payload["legs"][index]["exchangeId"],
                        "side": "no", "action": "buy"}

        result = reconcile_basket(FilledAPI(), payload, response, TID)
        self.assertFalse(result["balanced_full_fill"])
        self.assertAlmostEqual(result["nominal_entry_cost"], 95)
        self.assertAlmostEqual(result["normal_settlement_gain_floor"], 5)

    def test_bulk_quotes_require_exact_scoped_coverage(self):
        class MissingAPI:
            def get(self, *args, **kwargs):
                return {"data": [], "missingIds": ["11"]}
        with self.assertRaises(ValueError):
            collect_quotes(MissingAPI(), TID, [{"id": "1", "exchanges": [{"id": "11"}]}])

    def test_screen_uses_bid_instead_of_latest_trade(self):
        candidate, _, _, _ = fixture()
        markets = [{"id": l["market_id"], "title": l["title"], "status": "open",
                    "exchanges": [{"id": l["exchange_id"], "latestPrice": .5}]} for l in candidate["legs"]]
        quotes = {"data": [{"exchangeId": l["exchange_id"], "bestBid": l["best_bid"]} for l in candidate["legs"]]}
        alerts = screen_party_bundles(markets, quotes)
        self.assertEqual(len(alerts[0]["legs"]), 3)
        self.assertAlmostEqual(alerts[0]["screened_edge_per_bundle"], .1)
        self.assertFalse(alerts[0]["metadata_reviewed"])

    def test_lost_basket_response_recovery_reuses_exact_endpoint_and_payload(self):
        candidate, nodes, books, config = fixture()
        reviewed = review_party_bundle(candidate, nodes, TID)
        config.update(tournament_id=TID, tournament_slug="example", expected_tournament_name="Example",
                      structural_live_enabled=True, structural_allowed_exchange_sets=[["11", "12", "13"]])

        class FakeAPI:
            def __init__(self):
                self.calls = []
            def pages(self, *args, **kwargs):
                return []
            def get(self, path, **params):
                if path == "/tournaments/example":
                    return {"id": TID, "name": "Example", "myBalance": 100000, "status": "active",
                            "startDate": "2020-01-01T00:00:00Z", "endDate": "2099-01-01T00:00:00Z"}
                if path.endswith("/nodes"):
                    return nodes[path.split("/")[2]]
                if path.endswith("/portfolio/positions"):
                    return {"positions": []}
                if path == "/portfolio/collateral":
                    return {"data": []}
                if path.endswith("/portfolio/pnl"):
                    return {"totalAccountValue": 100000}
                if path.endswith("/orderbook"):
                    return copy.deepcopy(books[path.split("/")[2]])
                index = int(path.split("/")[2]) - 1
                if path.endswith("/fills"):
                    leg = self.calls[0][1]["legs"][index]
                    return {"tournamentId": TID, "totalQuantityFilled": -100, "avgFillPrice": leg["price"],
                            "pagination": {"hasMore": False}, "data": [{"side": "no"}]}
                return {"tournamentId": TID, "open": False, "exchangeId": self.calls[0][1]["legs"][index]["exchangeId"],
                        "side": "no", "action": "buy"}
            def post(self, path, payload):
                self.calls.append((path, copy.deepcopy(payload)))
                if len(self.calls) == 1:
                    raise TimeoutError("Response lost after submission")
                return {"results": [{"index": i, "data": {"orderId": i+1, "exchangeId": leg["exchangeId"],
                                                           "open": False, "quantityTraded": 100,
                                                           "totalCost": leg["quantity"] * leg["price"]}}
                                    for i, leg in enumerate(payload["legs"])]}

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TimeoutError):
                execute_no_bundle(api, config, reviewed, directory)
            result = recover_baskets(api, config, directory)
            self.assertEqual(api.calls[0], api.calls[1])
            self.assertEqual(api.calls[0][0], "/orders/multi-leg")
            self.assertTrue(result[0]["balanced_full_fill"])
            self.assertAlmostEqual(result[0]["normal_settlement_gain_floor"], 10)

    def test_actual_no_fill_prices_match_nominal_cost_receipts(self):
        payload = {"legs": [{"exchangeId": "1074", "quantity": 100, "price": .875},
                            {"exchangeId": "1073", "quantity": 100, "price": .08},
                            {"exchangeId": "880", "quantity": 100, "price": .96}]}
        prices = [.87, .08, .96]
        response = {"results": [{"index": i, "data": {"orderId": i+1, "exchangeId": leg["exchangeId"],
                                                       "open": False, "quantityTraded": 100,
                                                       "all": {"fullNotionalCost": prices[i]*100}}}
                                for i, leg in enumerate(payload["legs"])]}
        class LiveShapeAPI:
            def get(self, path, **params):
                index = int(path.split("/")[2]) - 1
                if path.endswith("/fills"):
                    return {"tournamentId": TID, "totalQuantityFilled": -100, "avgFillPrice": prices[index],
                            "pagination": {"hasMore": False}, "data": [{"side": "no"}]}
                return {"tournamentId": TID, "open": False, "exchangeId": payload["legs"][index]["exchangeId"],
                        "side": "no", "action": "buy"}
        result = reconcile_basket(LiveShapeAPI(), payload, response, TID)
        self.assertTrue(result["balanced_full_fill"])
        self.assertEqual(result["nominal_entry_cost"], 191)
        self.assertEqual(result["normal_settlement_gain_floor"], 9)
        broken = copy.deepcopy(response)
        broken["results"][1]["data"]["all"]["fullNotionalCost"] = 92
        with self.assertRaises(RuntimeError):
            reconcile_basket(LiveShapeAPI(), payload, broken, TID)


if __name__ == "__main__":
    unittest.main()
