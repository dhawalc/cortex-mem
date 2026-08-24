"""Score the A/B: does the guidance change what the model declares?"""

from __future__ import annotations

import json
import sys
from collections import Counter

SEED_TOPIC = "staging-deploy-target"
SEED_ID = "seed-staging-target"


def score(results):
    per_arm = {}
    for row in results:
        arm = row["arm"]
        bucket = per_arm.setdefault(
            arm,
            {
                "n": 0,
                "read_first": 0,
                "wrote": 0,
                "set_claim_key": 0,
                "claim_key_matched_seed": 0,
                "declared_supersedes": 0,
                "supersedes_correct": 0,
                "paired_key_and_supersedes": 0,
                "contested": 0,
                "two_current_values": 0,
                "keys": Counter(),
                "errors": 0,
            },
        )
        bucket["n"] += 1
        names = [c["name"] for c in row["tool_calls"]]
        writes = [c for c in row["calls"] if c.get("tool") == "remember"]
        bucket["errors"] += sum(1 for c in row["calls"] if "error" in c)
        if names and names[0] in {"recall", "search"}:
            bucket["read_first"] += 1
        if writes:
            bucket["wrote"] += 1
        keyed = [w for w in writes if w.get("claim_key")]
        superseding = [w for w in writes if w.get("supersedes")]
        if keyed:
            bucket["set_claim_key"] += 1
            for w in keyed:
                bucket["keys"][w["claim_key"]] += 1
            if any(w["claim_key"] == SEED_TOPIC for w in keyed):
                bucket["claim_key_matched_seed"] += 1
        if superseding:
            bucket["declared_supersedes"] += 1
            if any(w["supersedes"] == SEED_ID for w in superseding):
                bucket["supersedes_correct"] += 1
        if any(w.get("claim_key") and w.get("supersedes") for w in writes):
            bucket["paired_key_and_supersedes"] += 1
        if row["contested_records"]:
            bucket["contested"] += 1
        # Did the store end with both the old and the new claim current?
        current_texts = [
            c.get("content") if isinstance(c.get("content"), str) else ""
            for c in row["current"]
        ]
        old = any("cluster-west-2" in t for t in current_texts)
        new = any("cluster-east-1" in t for t in current_texts)
        if old and new:
            bucket["two_current_values"] += 1
    return per_arm


def main():
    document = json.load(open(sys.argv[1]))
    per_arm = score(document["results"])
    print("=" * 78)
    print(f"MODEL {document['model']}  temp {document['temperature']}  "
          f"condition {document['condition']}  n={document['trials_per_arm']}/arm  "
          f"{document['total_model_calls']} model calls")
    print("=" * 78)
    rows = [
        ("read before writing", "read_first"),
        ("wrote at all", "wrote"),
        ("(i)   set claim_key", "set_claim_key"),
        ("      ...matching the seed's key", "claim_key_matched_seed"),
        ("(ii)  declared supersedes", "declared_supersedes"),
        ("      ...with the correct id", "supersedes_correct"),
        ("      paired claim_key + supersedes", "paired_key_and_supersedes"),
        ("(iii) produced a contested write", "contested"),
        ("OUTCOME: two current values left", "two_current_values"),
        ("malformed tool calls", "errors"),
    ]
    arms = sorted(per_arm)
    print(f"  {'metric':<40}" + "".join(f"{a:>18}" for a in arms))
    for label, key in rows:
        cells = ""
        for arm in arms:
            bucket = per_arm[arm]
            value = bucket[key]
            if key == "errors":
                cells += f"{value:>18}"
            else:
                cells += f"{value:>8}/{bucket['n']:<3}{value / bucket['n']:>6.0%}"
        print(f"  {label:<40}{cells}")
    print()
    for arm in arms:
        keys = per_arm[arm]["keys"]
        if keys:
            print(f"  claim keys invented by {arm}:")
            for key, count in keys.most_common(6):
                marker = "  <-- matches seed" if key == SEED_TOPIC else ""
                print(f"    {count:>3}x  {key!r}{marker}")


main()
