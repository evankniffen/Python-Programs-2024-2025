"""Explicit correlated election-error model; parameters require historical calibration."""

from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import numpy as np


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def outcomes_from_margins(margins, race_ids, mapping):
    race_index = {race: i for i, race in enumerate(race_ids)}
    results = []
    for contract in mapping["contracts"]:
        kind = contract.get("type", "race")
        if kind == "race":
            dem_wins = margins[:, race_index[contract["race_id"]]] > 0
            if contract["yes_party"] not in ("D", "R"):
                raise ValueError("Race contracts currently support D/R two-party outcomes only.")
            outcome = dem_wins if contract["yes_party"] == "D" else ~dem_wins
        elif kind == "chamber":
            members = contract["race_ids"]
            if not members or len(set(members)) != len(members):
                raise ValueError("Chamber constituent races must be nonempty and unique.")
            needed = int(contract["dem_wins_needed"])
            if not 0 <= needed <= len(members):
                raise ValueError("Chamber threshold must be specified after fixed seats/tie rules.")
            count = sum((margins[:, race_index[race]] > 0).astype(int) for race in members)
            outcome = count >= needed
            if contract["yes_party"] == "R":
                outcome = ~outcome
            elif contract["yes_party"] != "D":
                raise ValueError("Specify D/R chamber-control semantics.")
        else:
            raise ValueError(f"Unsupported contract type: {kind}")
        results.append(np.asarray(outcome, dtype=np.int8))
    return np.column_stack(results)


def fit_elections(polls_path, mapping_path, output_dir, samples=50000, seed=20261007, as_of=None):
    now = parse_time(as_of) if as_of else datetime.now(timezone.utc)
    with open(mapping_path, encoding="utf-8") as handle:
        mapping = json.load(handle)
    with open(polls_path, newline="", encoding="utf-8") as handle:
        polls = list(csv.DictReader(handle))
    if samples < 1000:
        raise ValueError("Use at least 1,000 Monte Carlo scenarios.")
    if not polls or not mapping.get("contracts"):
        raise ValueError("Polls and contract mappings must be nonempty.")
    ids = [str(row["exchange_id"]) for row in mapping["contracts"]]
    if len(set(ids)) != len(ids) or not all(i.isdigit() and int(i) > 0 for i in ids):
        raise ValueError("Each mapped exchange ID must be a unique positive numeric string.")
    seen = set()
    for row in polls:
        identity = (row["race_id"], row["poll_id"])
        if identity in seen:
            raise ValueError("Duplicate poll_id within a race; do not double-count samples.")
        seen.add(identity)
        if parse_time(row["field_end"]) > now:
            raise ValueError("A poll is dated after the model's as-of date.")
    params = mapping.get("model_parameters", {})
    half_life = float(params.get("poll_half_life_days", 14))
    house_sd = float(params.get("pollster_error_sd", 1.5))
    national_sd = float(params.get("national_error_sd", 2.5))
    region_sd = float(params.get("regional_error_sd", 1.5))
    race_sd = float(params.get("race_error_sd", 2.5))
    stress_shift = float(params.get("stress_margin_shift", 2.0))
    if half_life <= 0 or min(house_sd, national_sd, region_sd, race_sd, stress_shift) < 0:
        raise ValueError("Invalid error-model parameters.")
    if race_sd == 0:
        raise ValueError("A positive residual race-error scale is required.")
    races = mapping["races"]
    race_ids = sorted(races)
    pollsters = sorted({row["pollster"] for row in polls})
    regions = sorted({races[race]["region"] for race in race_ids})
    pollster_index = {name: i for i, name in enumerate(pollsters)}
    region_index = {name: i for i, name in enumerate(regions)}
    house_loadings = np.zeros((len(race_ids), len(pollsters)))
    region_loadings = np.zeros((len(race_ids), len(regions)))
    national_loadings = np.zeros(len(race_ids))
    means, independent_variances, diagnostics = [], [], []
    for i, race in enumerate(race_ids):
        rows = [row for row in polls if row["race_id"] == race]
        if not rows:
            raise ValueError(f"No polls supplied for {race}; provide a documented prior/model instead.")
        values = np.array([float(row["dem_margin"]) for row in rows])
        ses = np.array([float(row["standard_error"]) for row in rows])
        ages = np.array([(now - parse_time(row["field_end"])).total_seconds() / 86400 for row in rows])
        if not np.isfinite(values).all() or not np.isfinite(ses).all() or (ses <= 0).any():
            raise ValueError("Poll margins must be finite and standard errors positive.")
        if (np.abs(values) > 100).any():
            raise ValueError("Margins and errors must be measured in percentage points.")
        variances = ses ** 2 * 2 ** (ages / half_life)
        same_house = np.equal.outer([row["pollster"] for row in rows],
                                    [row["pollster"] for row in rows])
        covariance = np.diag(variances) + house_sd ** 2 * same_house
        precision = np.linalg.solve(covariance, np.ones(len(rows)))
        weights = precision / precision.sum()
        mean = float(weights @ values)
        independent_var = float(np.sum(weights ** 2 * variances))
        means.append(mean)
        independent_variances.append(independent_var)
        for row, weight in zip(rows, weights):
            house_loadings[i, pollster_index[row["pollster"]]] += weight
        region_loadings[i, region_index[races[race]["region"]]] = float(races[race].get("regional_loading", 1))
        national_loadings[i] = float(races[race].get("national_loading", 1))
        diagnostics.append({"race_id": race, "poll_count": len(rows), "mean_dem_margin": mean,
                            "most_recent_poll": max(row["field_end"] for row in rows),
                            "oldest_poll": min(row["field_end"] for row in rows)})
    covariance = (np.diag(np.array(independent_variances) + race_sd ** 2) +
                  house_sd ** 2 * house_loadings @ house_loadings.T +
                  region_sd ** 2 * region_loadings @ region_loadings.T +
                  national_sd ** 2 * np.outer(national_loadings, national_loadings))
    rng = np.random.default_rng(seed)
    margins = rng.multivariate_normal(means, covariance, size=samples)
    outcomes = outcomes_from_margins(margins, race_ids, mapping)
    shifted_down = outcomes_from_margins(margins - stress_shift, race_ids, mapping)
    shifted_up = outcomes_from_margins(margins + stress_shift, race_ids, mapping)
    forecasts = []
    for i, contract in enumerate(mapping["contracts"]):
        affected = [contract["race_id"]] if contract.get("type", "race") == "race" else contract["race_ids"]
        source_date = min(max(row["field_end"] for row in polls if row["race_id"] == race) for race in affected)
        p = float(outcomes[:, i].mean())
        low = min(p, float(shifted_down[:, i].mean()), float(shifted_up[:, i].mean()))
        high = max(p, float(shifted_down[:, i].mean()), float(shifted_up[:, i].mean()))
        forecasts.append({"exchange_id": str(contract["exchange_id"]), "title": contract["title"],
                          "p_yes": p, "p_low": low, "p_high": high,
                          "source_as_of": source_date, "source": contract["source"],
                          "resolution_reviewed": bool(contract.get("resolution_reviewed", False)),
                          "approved": bool(contract.get("approved", False))})
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    generation = now.isoformat()
    np.savez_compressed(destination / "scenarios.npz", outcomes=outcomes,
                        exchange_ids=np.array(ids), generated_at=np.array(generation),
                        forecast_probabilities=outcomes.mean(axis=0))
    payload = {"generated_at": generation, "model": "correlated-polling-errors-v0.1",
               "validated": bool(mapping.get("model_validated", False)),
               "note": "Default error scales are illustrative. Stress bounds are sensitivity ranges, not confidence intervals.",
               "forecasts": forecasts, "race_diagnostics": diagnostics,
               "margin_covariance": covariance.tolist(), "race_ids": race_ids}
    (destination / "forecasts.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    return payload


def score_forecasts(path):
    """Offline historical scores; caller must establish a time-ordered held-out dataset."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("No historical validation observations.")
    seen = set()
    for row in rows:
        if parse_time(row["forecast_as_of"]) >= parse_time(row["event_date"]):
            raise ValueError("Historical forecast must precede the event date.")
        key = (row["event_id"], row["forecast_as_of"])
        if key in seen:
            raise ValueError("Duplicate historical event/cutoff observation.")
        seen.add(key)
    p = np.array([float(row["p_yes"]) for row in rows])
    benchmark = np.array([float(row["benchmark_p_yes"]) for row in rows])
    y = np.array([int(row["resolved_yes"]) for row in rows])
    if not np.isfinite(p).all() or not np.isfinite(benchmark).all() or ((p < 0) | (p > 1)).any() or ((benchmark < 0) | (benchmark > 1)).any() or not np.isin(y, [0, 1]).all():
        raise ValueError("Historical probabilities/outcomes are invalid.")
    def metrics(probability):
        clipped = np.clip(probability, 1e-9, 1 - 1e-9)
        return {"brier": float(np.mean((probability - y) ** 2)),
                "log_loss": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))}
    bins = []
    bin_index = np.minimum(9, np.floor(p * 10 + 1e-12).astype(int))
    for number in range(10):
        left = number / 10
        chosen = bin_index == number
        if chosen.any():
            bins.append({"range": [round(float(left), 2), round(float(left + 0.1), 2)],
                         "n": int(chosen.sum()), "mean_forecast": float(p[chosen].mean()),
                         "observed_frequency": float(y[chosen].mean())})
    return {"n": len(rows), "model": metrics(p), "benchmark": metrics(benchmark),
            "calibration": bins, "note": "Scores alone do not establish out-of-sample validity or tradable profit."}
