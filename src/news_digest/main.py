"""Local dry-run CLI. Live adapters are intentionally configured by deployment code."""

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .kakao import validate_messages


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Kakao digest without network I/O")
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--messages", type=Path, required=True,
                        help="JSON file containing a list of final Kakao message strings")
    args = parser.parse_args(argv)
    payload = json.loads(args.messages.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        parser.error("--messages must contain a JSON string list")
    envelopes = validate_messages(payload)
    print(json.dumps({"status": "dry_run", "messages": len(envelopes),
                      "characters": sum(len(item.text) for item in envelopes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
