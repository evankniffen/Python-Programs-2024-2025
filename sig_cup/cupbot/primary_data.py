"""Import sourced surveys and flag changes in original releases for review."""

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

from .api import NoRedirect
from .model import utc_now
from .runtime import write_json


PRIMARY_HOSTS = {
    "maristpoll.marist.edu", "emersoncollegepolling.com", "scri.siena.edu",
    "law.marquette.edu", "www.suffolk.edu", "suffolk.edu", "poll.qu.edu",
    "elections.alaska.gov", "www.elections.alaska.gov", "www.ohiosos.gov", "ohiosos.gov",
}


def source_url(value):
    url = urllib.parse.urlparse(value)
    if (url.scheme != "https" or url.hostname not in PRIMARY_HOSTS or url.username or url.password or
            url.port not in (None, 443) or url.fragment):
        raise ValueError("Polling monitor URLs must use an approved original-source HTTPS host.")
    return value


def normalize_research(payload, as_of=None):
    """Deduplicate identical populations; retain separate populations of one survey."""
    today = as_of or datetime.now(timezone.utc).date()
    observations, seen, warnings = [], {}, []
    for release in payload.get("poll_releases", []):
        survey = release.get("survey_id") or release.get("release_id")
        if not survey:
            raise ValueError("Every release needs a stable survey identifier.")
        races = []
        for original in release.get("races", []):
            races.append(original)
            population = original.get("population", release.get("population"))
            races.extend(dict(original, **variant) for variant in original.get("same_survey_population_results", [])
                         if variant.get("population") != population)
        for race in races:
            population = race.get("population", release.get("population"))
            key = (survey, race["race_label"], population)
            row = {"survey_id": survey, "race": race["race_label"], "pollster": release.get("pollster"),
                   "population": population, "field_start": release.get("field_start"),
                   "field_end": release.get("field_end"), "published_on": release.get("published_on"),
                   "sample_size": race.get("sample_size", release.get("sample_size")),
                   "reported_uncertainty": race.get("reported_uncertainty", release.get("reported_uncertainty")),
                   "candidate_support_percent": race.get("candidate_support_percent"),
                   "additional_response_percent": race.get("additional_response_percent"),
                   "observed_dem_minus_rep_margin_percentage_points": race.get("dem_minus_rep_margin_percentage_points"),
                   "margin_standard_error_percentage_points": race.get("margin_standard_error_percentage_points"),
                   "election_method": race.get("election_method"), "source": release.get("source"),
                   "sources": release.get("sources", []), "observation_type": race.get("observation_type"),
                   "contract_mapping_reviewed": False, "election_win_probability": None, "approved_for_trading": False,
                   "source_record": race,
                   "release_metadata": {k: v for k, v in release.items() if k != "races"}}
            row["missing_metadata"] = [name for name in ("population", "field_start", "field_end", "published_on", "sample_size", "reported_uncertainty", "source")
                                       if row[name] is None]
            for name in ("field_start", "field_end", "published_on"):
                value = row[name]
                if value and date.fromisoformat(value) > today:
                    raise ValueError("A research observation is dated after the as-of date.")
            if row["field_start"] and row["field_end"] and row["field_start"] > row["field_end"]:
                raise ValueError("Survey field dates are reversed.")
            if key in seen:
                if seen[key] != row:
                    raise ValueError("Conflicting observations share a survey, race, and population.")
                warnings.append({"survey_id": survey, "race": race["race_label"], "reason": "identical duplicate ignored"})
                continue
            seen[key] = row
            observations.append(row)
    return {"generated_at": utc_now(), "observation_count": len(observations), "observations": observations,
            "warnings": warnings, "validated_for_trading": False,
            "official_election_findings": payload.get("official_election_findings", []),
            "incomplete_release_packets": payload.get("incomplete_release_packets", []),
            "note": "Population variants stay grouped by survey_id; no undecided redistribution or win-probability conversion."}


def import_research(path, output):
    raw = Path(path).read_bytes()
    result = normalize_research(json.loads(raw))
    result["research_sha256"] = hashlib.sha256(raw).hexdigest()
    write_json(output, result)
    return result


def monitor_primary_sources(urls, state_path, transport=None, limit=6):
    """Bounded, credential-free checks; changed sources need extraction and review."""
    path = Path(state_path)
    previous = json.loads(path.read_text()) if path.exists() else {"sources": {}, "cursor": 0}
    unique = list(dict.fromkeys(source_url(url) for url in urls))
    cursor, checks = previous.get("cursor", 0), []
    opener = urllib.request.build_opener(NoRedirect())
    for i in range(min(len(unique), limit)):
        url = unique[(cursor + i) % len(unique)]
        try:
            if transport:
                body = transport(url)
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "EvanKniffen-PublicResearch/0.2", "Accept": "text/html,application/pdf"})
                with opener.open(request, timeout=10) as response:
                    body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ValueError("Primary release exceeds the bounded monitor download size.")
            digest = hashlib.sha256(body).hexdigest()
            old = previous["sources"].get(url)
            status = "baseline" if old is None else ("unchanged" if old["sha256"] == digest else "changed_requires_review")
            record = {"url": url, "sha256": digest, "checked_at": utc_now(), "status": status,
                      "approved_for_trading": False,
                      "needs_review": status == "changed_requires_review" or bool(old and old.get("needs_review"))}
            previous["sources"][url] = record
            checks.append(record)
        except Exception as error:
            checks.append({"url": url, "checked_at": utc_now(), "status": "unavailable", "error_type": type(error).__name__})
    previous.update(cursor=(cursor + len(checks)) % len(unique) if unique else 0, last_checks=checks, checked_at=utc_now())
    write_json(path, previous)
    return previous


def research_source_urls(payload):
    urls = []
    for release in payload.get("poll_releases", []):
        for value in [release.get("source"), *(row.get("url") for row in release.get("sources", []))]:
            if value:
                try:
                    urls.append(source_url(value))
                except ValueError:
                    continue
    return list(dict.fromkeys(urls))
