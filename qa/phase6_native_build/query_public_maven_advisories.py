"""Bounded official OSV lookup of explicitly reviewed public Maven coordinates."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected_advisory_redirect")


def checked_coordinates(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("coordinate_count")
    out = []
    for row in rows:
        if set(row) != {"name", "version", "public_reviewed"} or row["public_reviewed"] is not True:
            raise ValueError("only_reviewed_public_metadata")
        name, version = row["name"], row["version"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", name):
            raise ValueError("coordinate_name")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+~-]{1,160}", version):
            raise ValueError("coordinate_version")
        if any(x in name.lower() for x in ("wainek", "chatenu", "invalid.example")):
            raise ValueError("private_coordinate")
        pair = (name, version)
        if pair not in out:
            out.append(pair)
    return sorted(out)


def query(rows, fetch):
    coordinates = checked_coordinates(rows)
    result = {pair: {} for pair in coordinates}
    pending = [(pair, None) for pair in coordinates]
    pages, records = 0, []
    response_bytes = 0
    seen_tokens = {pair: set() for pair in coordinates}
    start = time.monotonic()
    while pending:
        if pages >= 100 or time.monotonic() - start > 300:
            raise ValueError("incomplete_advisory_bound")
        batch, pending = pending[:50], pending[50:]
        queries = []
        for (name, version), token in batch:
            item = {"package": {"ecosystem": "Maven", "name": name}, "version": version}
            if token:
                item["page_token"] = token
            queries.append(item)
        payload = {"queries": queries}
        response = fetch(payload)
        response_bytes += len(json.dumps(response).encode())
        if response_bytes > 16 * 1024 * 1024:
            raise ValueError("total_advisory_response_bound")
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise ValueError("invalid_advisory_response")
        if len(response["results"]) != len(batch):
            raise ValueError("advisory_result_count")
        records.append({"request": payload, "response": response})
        for (pair, previous), answer in zip(batch, response["results"]):
            if not isinstance(answer, dict) or "error" in answer:
                raise ValueError("advisory_query_error")
            for vulnerability in answer.get("vulns", []):
                identifier = vulnerability.get("id")
                if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", identifier):
                    raise ValueError("advisory_identifier")
                result[pair][identifier] = vulnerability
            token = answer.get("next_page_token")
            if token:
                if not isinstance(token, str) or len(token) > 8192 or token in seen_tokens[pair]:
                    raise ValueError("advisory_pagination")
                seen_tokens[pair].add(token)
                pending.append((pair, token))
        pages += 1
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "endpoint": "https://api.osv.dev/v1/querybatch", "ecosystem": "Maven",
            "query_count": len(coordinates), "requests": pages, "pagination_complete": True,
            "total_response_bytes": response_bytes,
            "results": [{"name": name, "version": version,
                         "vulnerabilities": sorted(result[(name, version)].values(), key=lambda x: x["id"])}
                        for name, version in coordinates], "raw_public_exchanges": records,
            "limits": "Known public version advisories only; no source, binary, reachability or absence-of-vulnerabilities guarantee. An empty result does not establish database coverage."}


def fetch(payload):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request("https://api.osv.dev/v1/querybatch",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != request.full_url:
            raise ValueError("advisory_http_status")
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("advisory_response_bound")
    return json.loads(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("coordinates", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    raw = args.coordinates.read_bytes()
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != args.expected_sha256:
        raise ValueError("reviewed_coordinate_file_mismatch")
    print(json.dumps(query(json.loads(raw), fetch), indent=2, sort_keys=True))
