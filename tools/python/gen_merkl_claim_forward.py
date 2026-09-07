#!/usr/bin/env python3
"""
Generate a Safe payload that claims Merkl rewards for a user and forwards
the claimed ERC-20 balance to a destination (e.g. bizdev).

Use AFTER a Merkl reallocateCampaignRewards has been processed and a new
merkle root includes the recipient (often ~24h). Proofs are fetched live
from the Merkl API.

Example (Plasma Omni -> bizdev for WXPL):

  python tools/python/gen_merkl_claim_forward.py \\
    --chain-id 9745 \\
    --safe 0x9ff471F9f98F42E5151C7855fD1b5aa906b1AF7e \\
    --token 0x6100E367285b01F48D07953803A2d8dCA5D19873 \\
    --to 0xF3B4829C8B9E2910C2396538F49a12b0c2475a7e \\
    --out MaxiOps/merkl/payloads/plasma-wxpl-claim-forward-to-bizdev.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.merkl.xyz"
# Canonical Merkl Distributor (same address on Plasma)
MERKL_DISTRIBUTOR = "0x3Ef3D8bA38EBe18DB133cEc108f4D14CE00Dd9Ae"


def _checksum_hint(addr: str) -> str:
    return addr


def fetch_token_reward(chain_id: int, user: str, token: str) -> dict:
    url = f"{BASE_URL}/v4/users/{user}/rewards"
    r = requests.get(url, params={"chainId": chain_id}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    token_l = token.lower()
    for chain_block in payload:
        for reward in chain_block.get("rewards", []):
            t = reward.get("token") or {}
            if (t.get("address") or "").lower() == token_l:
                return reward
    raise SystemExit(
        f"No Merkl rewards found for user={user} token={token} chainId={chain_id}"
    )


def build_payload(
    chain_id: int,
    safe: str,
    token: str,
    to: str,
    reward: dict,
    name: str,
) -> dict:
    amount = str(int(reward["amount"]) - int(reward.get("claimed") or 0))
    if int(amount) <= 0:
        raise SystemExit(
            f"Nothing unclaimed for {safe} / {token} "
            f"(amount={reward.get('amount')} claimed={reward.get('claimed')})"
        )
    proofs = reward.get("proofs") or reward.get("proof")
    if not proofs:
        raise SystemExit("Merkl reward response missing proofs; cannot build claim")

    return {
        "version": "1.0",
        "chainId": str(chain_id),
        "createdAt": int(datetime.now(tz=timezone.utc).timestamp()),
        "meta": {
            "name": name,
            "description": (
                f"Claim Merkl {token} for {safe} and transfer unclaimed amount "
                f"({amount}) to {to}."
            ),
            "txBuilderVersion": "1.16.3",
            "createdFromSafeAddress": safe,
            "createdFromOwnerAddress": "",
        },
        "transactions": [
            {
                "to": MERKL_DISTRIBUTOR,
                "value": "0",
                "data": None,
                "contractMethod": {
                    "inputs": [
                        {
                            "internalType": "address[]",
                            "name": "users",
                            "type": "address[]",
                        },
                        {
                            "internalType": "address[]",
                            "name": "tokens",
                            "type": "address[]",
                        },
                        {
                            "internalType": "uint256[]",
                            "name": "amounts",
                            "type": "uint256[]",
                        },
                        {
                            "internalType": "bytes32[][]",
                            "name": "proofs",
                            "type": "bytes32[][]",
                        },
                    ],
                    "name": "claim",
                    "payable": False,
                },
                "contractInputsValues": {
                    "users": json.dumps([safe]),
                    # Merkl claim uses accumulated amount (not remaining unclaimed)
                    "tokens": json.dumps([token]),
                    "amounts": json.dumps([str(reward["amount"])]),
                    "proofs": json.dumps([proofs]),
                },
            },
            {
                "to": token,
                "value": "0",
                "data": None,
                "contractMethod": {
                    "inputs": [
                        {
                            "internalType": "address",
                            "name": "to",
                            "type": "address",
                        },
                        {
                            "internalType": "uint256",
                            "name": "value",
                            "type": "uint256",
                        },
                    ],
                    "name": "transfer",
                    "payable": False,
                },
                "contractInputsValues": {
                    "to": to,
                    "value": amount,
                },
            },
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chain-id", type=int, required=True)
    p.add_argument("--safe", required=True, help="Claim recipient / executing Safe")
    p.add_argument("--token", required=True, help="Reward token address")
    p.add_argument("--to", required=True, help="Forward destination (e.g. bizdev)")
    p.add_argument(
        "--name",
        default="Merkl Claim & Forward",
        help="Safe TX Builder batch name",
    )
    p.add_argument("--out", required=True, help="Output JSON path")
    args = p.parse_args(argv)

    safe = _checksum_hint(args.safe)
    token = _checksum_hint(args.token)
    to = _checksum_hint(args.to)

    reward = fetch_token_reward(args.chain_id, safe, token)
    payload = build_payload(args.chain_id, safe, token, to, reward, args.name)

    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    unclaimed = int(reward["amount"]) - int(reward.get("claimed") or 0)
    print(
        f"Wrote {args.out}: claim accumulated={reward['amount']} "
        f"unclaimed={unclaimed} -> {to}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
