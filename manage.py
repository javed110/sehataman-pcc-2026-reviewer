"""Local lifecycle and explicitly privileged synthetic fixture controls."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from sehataman.bootstrap import bootstrap
from sehataman.crypto import iso, timestamp, totp
from sehataman.server import LocalServer
from sehataman.storage import IntegrityFailure

ROOT = Path(__file__).resolve().parent
LOCAL_ACTOR = {"id": "local-synthetic-verifier", "label": "Local Synthetic Fixture Verifier", "role": "local_fixture"}


def parser():
    result = argparse.ArgumentParser(description="SehatAman — all-synthetic local demonstration")
    result.add_argument("--home", type=Path, default=ROOT / ".local", help="Separate local demo home; never a real dataset")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8787)
    accounts = commands.add_parser("accounts")
    accounts.add_argument("--json", action="store_true")
    commands.add_parser("inputs", help="Restricted synthetic laboratory identity-entry fixtures; not a public API")
    commands.add_parser("verify")
    clock = commands.add_parser("clock")
    clock.add_argument("--advance-minutes", type=int)
    clock.add_argument("--set", dest="set_time")
    for kind in ("registration", "identity", "issuer"):
        item = commands.add_parser(kind, help="Privileged local simulated evidence only; no live verification")
        item.add_argument("alias")
        item.add_argument("status", choices=["valid", "pending", "stale", "suspended", "revoked", "expired"])
    revoke = commands.add_parser("revoke-sessions")
    revoke.add_argument("alias")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = bootstrap(args.home)
        if args.command in ("init", "verify"):
            print(json.dumps(store.verify(), indent=2))
        elif args.command == "accounts":
            credentials = json.loads((store.protected / "demo-accounts.json").read_text("utf-8"))
            rows = [{"username": item["username"], "password": item["password"],
                     "current_code": totp(item["totp_secret"]), "role": item["role"]} for item in credentials]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                print("SYNTHETIC DEMO CREDENTIALS — local display only, not application logs")
                print("Codes rotate every 30 seconds; each accepted code is usable once per account.")
                for row in rows:
                    print(f"{row['username']:<10} {row['password']:<30} code {row['current_code']}  {row['role']}")
        elif args.command == "inputs":
            print("RESTRICTED SYNTHETIC LAB INPUT FIXTURES — for identity-entry fields only")
            with store.transaction() as tx:
                for patient in tx.state["patients"].values():
                    print(f"{patient['alias']}  CNIC {patient['cnic']}  DOB {patient['dob']}")
        elif args.command == "serve":
            if not 1024 <= args.port <= 65535:
                raise ValueError("Choose a local port between 1024 and 65535.")
            server = LocalServer(store, args.port)
            print(f"SehatAman: http://127.0.0.1:{server.server_port}", flush=True)
            print("Loopback-only synthetic MVP. Step 5 engineering checks passed; direct stakeholder validation remains pending.", flush=True)
            print("Run Show-DemoAccounts.cmd for local sign-in credentials and current test codes.", flush=True)
            try:
                server.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.command == "clock":
            with store.transaction() as tx:
                if args.set_time:
                    new_time = timestamp(args.set_time)
                elif args.advance_minutes is not None and abs(args.advance_minutes) <= 525600:
                    new_time = timestamp(tx.state["clock"]) + args.advance_minutes * 60
                else:
                    print(json.dumps({"synthetic_test_clock": tx.state["clock"], "mode": "fixed; sessions/TOTP use actual time"}))
                    return 0
                tx.state["clock"] = iso(new_time)
                tx.audit("synthetic_clock_changed", LOCAL_ACTOR, reason="local_fixture_control")
                print(json.dumps({"synthetic_test_clock": tx.state["clock"]}))
        else:
            with store.transaction() as tx:
                state = tx.state
                if args.command == "revoke-sessions":
                    user = next((item for item in state["users"].values() if item["alias"].upper() == args.alias.upper()), None)
                    if not user:
                        raise ValueError("Unknown synthetic account alias.")
                    user["sessions"].clear()
                    tx.audit("sessions_revoked", LOCAL_ACTOR, object_id=user["id"])
                else:
                    collection, field = {"registration": ("profiles", "registration"),
                                         "identity": ("patients", "identity"),
                                         "issuer": ("organizations", "evidence")}[args.command]
                    subject = next((item for item in state[collection].values() if item["alias"].upper() == args.alias.upper()), None)
                    if not subject:
                        raise ValueError("Unknown synthetic entity alias.")
                    evidence = subject[field]
                    state["credential_history"].append({"kind": args.command, "subject_id": subject["id"], "evidence": deepcopy(evidence)})
                    evidence = {**evidence, "status": args.status, "checked_at": state["clock"], "verifier": LOCAL_ACTOR["label"]}
                    if args.status == "valid":
                        evidence.update({"valid_from": state["clock"], "valid_until": iso(timestamp(state["clock"]) + 86400)})
                    if args.status == "expired":
                        evidence["valid_until"] = state["clock"]
                    subject[field] = evidence
                    tx.audit("synthetic_" + args.command + "_" + args.status, LOCAL_ACTOR, object_id=subject["id"],
                             reason="simulated_evidence_only")
                print("Committed local synthetic fixture change; next request uses current state.")
        return 0
    except (IntegrityFailure, OSError, ValueError) as exc:
        print("Local operation unavailable: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
