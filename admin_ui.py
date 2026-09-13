import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlsplit

from config.recipient_profiles import prepare_recipient_profile_db_rows
from storage import create_storage


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "admin_ui_static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_SQLITE_URL = "sqlite:///job_scraper.db"
MAX_AUDIT_LIMIT = 500
ADMIN_DATABASE_REQUIRED_MESSAGE = (
    "Set DATABASE_URL to edit Supabase profiles, or pass --database-url "
    f"{DEFAULT_SQLITE_URL} for explicit local SQLite."
)


class AdminApiError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = status


class AdminController:
    def __init__(self, storage, storage_info=None):
        self.storage = storage
        self.storage_info = storage_info or {}

    def health(self):
        return {
            "ok": True,
            "backend": self.storage.backend,
            **self.storage_info,
        }

    def list_profiles(self):
        records = self.storage.load_recipient_profile_records(enabled_only=False)
        return {
            "profiles": [
                self._profile_summary(record["config"], record)
                for record in records
            ]
        }

    def get_profile(self, recipient_id):
        for record in self.storage.load_recipient_profile_records(enabled_only=False):
            if record["recipient_id"] == recipient_id:
                return {
                    "profile": record["config"],
                    "summary": self._profile_summary(record["config"], record),
                }
        raise AdminApiError("Recipient profile not found.", HTTPStatus.NOT_FOUND)

    def list_profile_versions(self, recipient_id):
        versions = self.storage.load_recipient_profile_versions(recipient_id, limit=30)
        return {
            "versions": [
                self._profile_version_payload(version)
                for version in versions
            ]
        }

    def validate_profile(self, profile):
        row = self._prepare_profile_row(profile)
        return {
            "valid": True,
            "profile": row["config"],
            "summary": self._profile_summary(row["config"]),
        }

    def save_profile(self, profile):
        row = self._prepare_profile_row(profile)
        self.storage.upsert_recipient_profile_configs([row])
        return {
            "saved": True,
            "profile": row["config"],
            "summary": self._profile_summary(row["config"]),
        }

    def restore_profile_version(self, recipient_id, version_id):
        try:
            version_id = int(version_id)
        except (TypeError, ValueError) as exc:
            raise AdminApiError("Profile version id is required.") from exc

        version = self.storage.load_recipient_profile_version(recipient_id, version_id)
        if not version:
            raise AdminApiError("Profile version not found.", HTTPStatus.NOT_FOUND)

        row = self._prepare_profile_row(version["config"])
        self.storage.upsert_recipient_profile_configs([row])
        return {
            "restored": True,
            "profile": row["config"],
            "summary": self._profile_summary(row["config"]),
            "restored_version": self._profile_version_payload(version),
        }

    def list_audit_rows(self, filters):
        rows = self.storage.load_review_audit_rows(
            limit=self._audit_limit(filters.get("limit")),
            recipient_id=filters.get("recipient_id"),
            classification=filters.get("classification"),
            review_family=filters.get("review_family"),
            run_id=filters.get("run_id"),
            sort=filters.get("sort") or "semantic_score_desc",
        )
        parsed_rows = [self._parse_audit_row(row) for row in rows]
        return {
            "rows": parsed_rows,
            "summary": {
                "row_count": len(parsed_rows),
                "classifications": self._count_by(parsed_rows, "classification"),
                "review_families": self._count_by(parsed_rows, "review_family"),
            },
        }

    def audit_filter_values(self):
        values = self.storage.load_review_audit_filter_values()
        profile_ids = [
            record["recipient_id"]
            for record in self.storage.load_recipient_profile_records(enabled_only=False)
        ]
        return {
            **values,
            "recipient_ids": list(
                dict.fromkeys(profile_ids + values.get("recipient_ids", []))
            ),
        }

    def _prepare_profile_row(self, profile):
        if not isinstance(profile, dict):
            raise AdminApiError("Profile payload must be a JSON object.")

        try:
            return prepare_recipient_profile_db_rows(
                [profile],
                sender_email=os.getenv("JOB_SCRAPER_EMAIL", ""),
            )[0]
        except Exception as exc:
            raise AdminApiError(str(exc)) from exc

    @staticmethod
    def _profile_summary(profile, record=None):
        candidate = profile.get("candidate") or {}
        delivery = profile.get("delivery") or {}
        preferences = profile.get("job_preferences") or {}
        matching = profile.get("matching") or {}
        target_roles = candidate.get("target_roles") or []
        return {
            "id": profile.get("id") or (record or {}).get("recipient_id", ""),
            "email": delivery.get("email") or profile.get("email") or "",
            "language": delivery.get("language") or "",
            "location": preferences.get("location") or "UK",
            "enabled": bool(profile.get("enabled", True)),
            "target_roles": [
                role.get("id") if isinstance(role, dict) else role
                for role in target_roles
            ],
            "semantic_threshold": matching.get("semantic_threshold"),
            "updated_at": (record or {}).get("updated_at"),
        }

    @classmethod
    def _profile_version_payload(cls, version):
        return {
            "version_id": version.get("version_id"),
            "recipient_id": version.get("recipient_id"),
            "email": version.get("email"),
            "enabled": cls._coerce_bool(version.get("enabled")),
            "saved_at": version.get("saved_at"),
            "profile": version.get("config"),
            "summary": cls._profile_summary(version.get("config") or {}, version),
        }

    @staticmethod
    def _coerce_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            return value.lower() in {"1", "true", "t", "yes"}
        return bool(value)

    @staticmethod
    def _audit_limit(value):
        if value in (None, ""):
            return 150
        try:
            return min(MAX_AUDIT_LIMIT, max(1, int(value)))
        except (TypeError, ValueError):
            return 150

    @staticmethod
    def _count_by(rows, key):
        counts = {}
        for row in rows:
            value = row.get(key) or "-"
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _parse_audit_row(row):
        parsed = dict(row)
        for key in ("supporting_evidence_json", "mismatch_evidence_json", "metadata_json"):
            parsed[key.replace("_json", "")] = _parse_json_field(parsed.get(key))
        return parsed


def _parse_json_field(value):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return [] if value != "{}" else {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run the local admin UI for recipient profiles and review audits."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "database_url_arg",
        nargs="?",
        help="Optional database URL. Prefer quotes in PowerShell.",
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this UI process.",
    )
    return parser


def create_admin_storage(database_url=None):
    primary_url = (database_url or os.getenv("DATABASE_URL", "")).strip()
    if not primary_url:
        raise RuntimeError(ADMIN_DATABASE_REQUIRED_MESSAGE)

    primary_label = database_label(primary_url)
    try:
        storage = create_storage(primary_url)
        storage.ensure_schema()
    except Exception as exc:
        raise RuntimeError(
            f"Unable to connect to admin database {primary_label}. "
            f"{ADMIN_DATABASE_REQUIRED_MESSAGE} Original error: {exc}"
        ) from exc

    return storage, {
        "database_source": "argument" if database_url else "environment",
        "database_label": primary_label,
        "using_fallback": False,
    }


def database_label(database_url):
    if not database_url:
        return ""

    parsed = urlsplit(database_url)
    if parsed.scheme == "sqlite":
        return database_url
    if parsed.scheme in {"postgres", "postgresql"}:
        path = parsed.path.strip("/") or "database"
        host = parsed.hostname or "host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}/{path}"
    return parsed.scheme or "database"


def make_handler(controller):
    class AdminRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle_request("GET")

        def do_POST(self):
            self._handle_request("POST")

        def log_message(self, format_value, *args):
            print(f"[admin_ui] {self.address_string()} {format_value % args}")

        def _handle_request(self, method):
            parsed = urlparse(self.path)
            try:
                if method == "GET":
                    self._handle_get(parsed)
                    return
                if method == "POST":
                    self._handle_post(parsed)
                    return
                self._send_json({"error": "Unsupported method."}, HTTPStatus.METHOD_NOT_ALLOWED)
            except AdminApiError as exc:
                self._send_json({"error": exc.message}, exc.status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _handle_get(self, parsed):
            path = parsed.path
            if path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path.startswith("/static/"):
                self._send_static(path)
                return
            if path == "/api/health":
                self._send_json(controller.health())
                return
            if path == "/api/profiles":
                self._send_json(controller.list_profiles())
                return
            if path.startswith("/api/profiles/"):
                recipient_id = unquote(path.removeprefix("/api/profiles/"))
                if recipient_id.endswith("/versions"):
                    recipient_id = recipient_id.removesuffix("/versions")
                    self._send_json(controller.list_profile_versions(recipient_id))
                    return
                self._send_json(controller.get_profile(recipient_id))
                return
            if path == "/api/audit":
                filters = _single_value_params(parse_qs(parsed.query))
                self._send_json(controller.list_audit_rows(filters))
                return
            if path == "/api/audit/options":
                self._send_json(controller.audit_filter_values())
                return
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

        def _handle_post(self, parsed):
            payload = self._read_json()
            if parsed.path == "/api/profiles/validate":
                self._send_json(controller.validate_profile(payload.get("profile")))
                return
            if parsed.path == "/api/profiles/save":
                self._send_json(controller.save_profile(payload.get("profile")))
                return
            if parsed.path.startswith("/api/profiles/") and parsed.path.endswith("/restore"):
                recipient_id = unquote(
                    parsed.path.removeprefix("/api/profiles/").removesuffix("/restore")
                )
                self._send_json(
                    controller.restore_profile_version(
                        recipient_id,
                        payload.get("version_id"),
                    )
                )
                return
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

        def _read_json(self):
            content_length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                return json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise AdminApiError(f"Invalid JSON: {exc.msg}") from exc

        def _send_static(self, path):
            relative_path = path.removeprefix("/static/")
            static_path = (STATIC_DIR / relative_path).resolve()
            if STATIC_DIR.resolve() not in static_path.parents:
                self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            content_type = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }.get(static_path.suffix, "application/octet-stream")
            self._send_file(static_path, content_type)

        def _send_file(self, path, content_type):
            if not path.exists() or not path.is_file():
                self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            payload = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload, status=HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return AdminRequestHandler


def _single_value_params(query):
    return {
        key: values[-1]
        for key, values in query.items()
        if values and values[-1] != ""
    }


def main(argv=None):
    args = build_parser().parse_args(argv)
    requested_database_url = args.database_url or args.database_url_arg
    try:
        storage, storage_info = create_admin_storage(requested_database_url)
    except RuntimeError as exc:
        raise SystemExit(f"[admin_ui] {exc}") from exc
    controller = AdminController(storage, storage_info=storage_info)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(controller))
    print(
        f"[admin_ui] http://{args.host}:{args.port} "
        f"({storage_info.get('database_label', storage.backend)})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[admin_ui] stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
