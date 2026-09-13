import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.recipient_profiles import normalize_grouped_profile
from storage import create_storage


def _profile_label(profile, index):
    if isinstance(profile, dict):
        return (
            profile.get("id")
            or (profile.get("delivery") or {}).get("email")
            or profile.get("email")
            or f"profile[{index}]"
        )
    return f"profile[{index}]"


def validate_profile_configs(configs, sender_email=""):
    results = []
    normalized_ids = []

    for index, profile in enumerate(configs):
        label = _profile_label(profile, index)
        try:
            normalized = normalize_grouped_profile(
                profile,
                index=index,
                sender_email=sender_email,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            results.append(
                {
                    "ok": False,
                    "index": index,
                    "label": label,
                    "error": str(exc),
                }
            )
            continue

        normalized_ids.append(normalized["id"])
        results.append(
            {
                "ok": True,
                "index": index,
                "label": label,
                "recipient_id": normalized["id"],
                "email": normalized["delivery"]["email"],
                "language": normalized["delivery"].get("language", ""),
                "location": normalized["job_preferences"].get("location", "UK"),
                "enabled": bool(normalized.get("enabled", True)),
                "target_roles": [
                    role["id"] for role in normalized["candidate"]["target_roles"]
                ],
            }
        )

    duplicate_ids = {
        recipient_id
        for recipient_id in normalized_ids
        if normalized_ids.count(recipient_id) > 1
    }
    if duplicate_ids:
        for result in results:
            if result.get("recipient_id") in duplicate_ids:
                result["ok"] = False
                result["error"] = (
                    f"Duplicate normalized recipient id: {result['recipient_id']}"
                )

    return results


def load_configs_from_storage(enabled_only=False):
    storage = create_storage()
    storage.ensure_schema()
    return storage.load_recipient_profile_configs(enabled_only=enabled_only)


def print_validation_results(results):
    for result in results:
        if result["ok"]:
            role_list = ",".join(result["target_roles"]) or "-"
            language = result.get("language") or "-"
            location = result.get("location") or "UK"
            print(
                f"OK profile[{result['index']}] "
                f"id={result['recipient_id']} "
                f"email={result['email']} "
                f"language={language} "
                f"location={location} "
                f"enabled={1 if result['enabled'] else 0} "
                f"target_roles={role_list}"
            )
            continue

        print(
            f"ERROR profile[{result['index']}] "
            f"label={result['label']} "
            f"error={result['error']}"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate recipient profiles stored in the configured database."
    )
    parser.add_argument(
        "--enabled-only",
        action="store_true",
        help="Validate only enabled recipient profiles.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    configs = load_configs_from_storage(enabled_only=args.enabled_only)
    if not configs:
        print("ERROR no recipient profiles found.")
        return 1

    results = validate_profile_configs(
        configs,
        sender_email=os.getenv("JOB_SCRAPER_EMAIL", ""),
    )
    print_validation_results(results)

    error_count = sum(1 for result in results if not result["ok"])
    if error_count:
        print(f"Validation failed: {error_count}/{len(results)} profile(s) invalid.")
        return 1

    print(f"Validation passed: {len(results)} profile(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
