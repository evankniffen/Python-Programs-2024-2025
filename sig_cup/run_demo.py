"""Offline demonstration. No API requests and no real election predictions."""

from datetime import datetime, timedelta, timezone
import csv
import json
from pathlib import Path
from cupbot.model import fit_elections, utc_now
from cupbot.runtime import analysis, read_json, write_json

root = Path(__file__).resolve().parent
out = root / "work" / "demo"
out.mkdir(parents=True, exist_ok=True)
with (root / "examples/polls.example.csv").open(newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)
    fields = reader.fieldnames
for i, row in enumerate(rows):
    row["field_end"] = (datetime.now(timezone.utc) - timedelta(days=1 + i % 2)).isoformat()
with (out / "fictional_polls.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
mapping = read_json(root / "examples/mapping.example.json")
write_json(out / "fictional_mapping.json", mapping)
forecasts = fit_elections(out / "fictional_polls.csv", out / "fictional_mapping.json", out / "model", samples=20000)
config = read_json(root / "config.example.json")
config.update(tournament_slug="DEMO-NOT-A-LIVE-TOURNAMENT", tournament_id="00000000-0000-4000-8000-000000000000",
              expected_tournament_name="DEMO ONLY", live_enabled=False)
markets, books = [], {}
for i, forecast in enumerate(forecasts["forecasts"]):
    exchange, market = forecast["exchange_id"], str(99901 + i)
    markets.append({"id": market, "title": forecast["title"], "status": "open", "exchanges": [{"id": exchange}]})
    ask = [.35, .30, .15][i]
    stamp = utc_now()
    books[exchange] = {"exchangeId": exchange, "marketId": market, "received_at": stamp,
                       "asOf": {"sequence": 1, "at": stamp},
                       "asks": [{"price": ask, "quantity": 10000}],
                       "bids": [{"price": ask - .025, "quantity": 10000}]}
snapshot = {"captured_at": utc_now(), "tournament": {"id": config["tournament_id"], "name": "DEMO ONLY",
             "initialBalance": 100000, "myBalance": 100000}, "markets": markets, "books": books,
            "positions": {"positions": []}, "pnl": {"totalAccountValue": 100000}, "open_orders": [],
            "collateral": {"data": []}, "leaderboard": {"leaderboard": [{"pnl": 5000}]},
            "coverage": {"books_collected": len(books), "note": "FICTIONAL OFFLINE DATA"}}
write_json(out / "config.json", config)
write_json(out / "snapshot.json", snapshot)
result = analysis(snapshot, forecasts, out / "model/scenarios.npz", config)
write_json(out / "analysis.json", result)
print(json.dumps({"demo_only": True, "api_requests": 0, "trades": 0,
                  "contracts": len(forecasts["forecasts"]), "joint_scenarios": 20000,
                  "illustrative_candidates": len(result["candidates"]),
                  "output_directory": str(out)}, indent=2))
