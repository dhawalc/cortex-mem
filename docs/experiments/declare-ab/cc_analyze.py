"""Score the Claude Code trials from the resulting scratch stores."""

from __future__ import annotations

import json
import pathlib
import sqlite3

SEED_ID = "seed-staging-target"
SEED_KEY = "staging-deploy-target"
ROOT = pathlib.Path("/tmp/decl/cc")


def score_store(path: pathlib.Path) -> dict | None:
    db = path / "aoms.sqlite3"
    if not db.is_file():
        return None
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in connection.execute(
            "SELECT id, claim_key, contested, record_json FROM memories "
            "ORDER BY created_at, id"
        )
    ]
    contests = [
        dict(r) for r in connection.execute("SELECT * FROM contest_entries")
    ]
    connection.close()

    written = [r for r in rows if r["id"] != SEED_ID]
    parsed = []
    for row in written:
        record = json.loads(row["record_json"])
        parsed.append(
            {
                "id": row["id"],
                "claim_key": row["claim_key"],
                "contested": bool(row["contested"]),
                "supersedes": record.get("supersedes"),
                "derived_from": record.get("provenance", {}).get("derived_from") or [],
                "content": record.get("content", ""),
            }
        )
    return {
        "writes": len(parsed),
        "set_claim_key": any(p["claim_key"] for p in parsed),
        "key_matched": any(p["claim_key"] == SEED_KEY for p in parsed),
        "declared_supersedes": any(p["supersedes"] for p in parsed),
        "supersedes_correct": any(p["supersedes"] == SEED_ID for p in parsed),
        "paired": any(
            p["claim_key"] == SEED_KEY and p["supersedes"] == SEED_ID for p in parsed
        ),
        "cited_derived_from": any(p["derived_from"] for p in parsed),
        "contested_records": sum(p["contested"] for p in parsed),
        "contest_triggers": [c["trigger"] for c in contests],
        "clean": len(parsed) == 1
        and not any(p["contested"] for p in parsed)
        and any(p["supersedes"] == SEED_ID for p in parsed),
        "records": parsed,
    }


def main():
    by_arm: dict[str, list] = {"armA": [], "armB": []}
    for path in sorted(ROOT.glob("arm*-unprompted-*")):
        arm = path.name.split("-")[0]
        scored = score_store(path)
        if scored:
            scored["trial"] = path.name
            by_arm[arm].append(scored)

    print("=" * 78)
    print("CLAUDE CODE (headless, --strict-mcp-config, scratch store)")
    print("=" * 78)
    labels = [
        ("writes made", lambda s: s["writes"]),
        ("set claim_key", lambda s: s["set_claim_key"]),
        ("  ...matching the incumbent's", lambda s: s["key_matched"]),
        ("declared supersedes", lambda s: s["declared_supersedes"]),
        ("  ...with the correct id", lambda s: s["supersedes_correct"]),
        ("paired key + supersedes correctly", lambda s: s["paired"]),
        ("cited derived_from", lambda s: s["cited_derived_from"]),
        ("contested records produced", lambda s: s["contested_records"]),
        ("ONE clean admitted correction", lambda s: s["clean"]),
    ]
    for arm in ("armA", "armB"):
        trials = by_arm[arm]
        name = "A (no guidance)" if arm == "armA" else "B (guidance)"
        print(f"\n  ARM {name}   n={len(trials)}")
        for label, getter in labels:
            values = [getter(t) for t in trials]
            if all(isinstance(v, bool) for v in values):
                shown = f"{sum(values)}/{len(values)}"
            else:
                shown = " ".join(str(v) for v in values)
            print(f"    {label:<38} {shown}")
        triggers = [t for trial in trials for t in trial["contest_triggers"]]
        if triggers:
            print(f"    contest triggers seen              {triggers}")

    print()
    print("=" * 78)
    print("PER-TRIAL DETAIL")
    print("=" * 78)
    for arm in ("armA", "armB"):
        for trial in by_arm[arm]:
            print(f"\n  {trial['trial']}  writes={trial['writes']} "
                  f"contested={trial['contested_records']} clean={trial['clean']}")
            for record in trial["records"]:
                flag = "CONTESTED" if record["contested"] else "admitted "
                print(f"    {flag} key={str(record['claim_key'])[:22]:<24}"
                      f" supersedes={str(record['supersedes'])[:22]:<24}"
                      f" derived_from={record['derived_from']}")


main()
