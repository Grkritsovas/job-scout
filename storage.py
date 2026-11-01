import json
import os
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

SQLITE_SEEN_JOBS_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS recipient_seen_jobs (
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT '',
        target_value TEXT,
        company_name TEXT,
        title TEXT,
        location TEXT,
        is_seen INTEGER NOT NULL DEFAULT 1,
        processing_status TEXT NOT NULL DEFAULT 'processed',
        review_family TEXT,
        classification TEXT,
        stage TEXT,
        run_id TEXT,
        semantic_rank INTEGER,
        raw_embedding_score REAL,
        semantic_score REAL,
        semantic_threshold REAL,
        semantic_fit_hint TEXT,
        salary_upper_bound_gbp REAL,
        sent INTEGER NOT NULL DEFAULT 0,
        review_error_stage TEXT,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (recipient_id, job_url)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_seen_jobs_pending
    ON recipient_seen_jobs (is_seen, classification, updated_at)
    """,
]

POSTGRES_SEEN_JOBS_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS app_config.recipient_seen_jobs (
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT '',
        target_value TEXT,
        company_name TEXT,
        title TEXT,
        location TEXT,
        is_seen BOOLEAN NOT NULL DEFAULT TRUE,
        processing_status TEXT NOT NULL DEFAULT 'processed',
        review_family TEXT,
        classification TEXT,
        stage TEXT,
        run_id TEXT,
        semantic_rank INTEGER,
        raw_embedding_score DOUBLE PRECISION,
        semantic_score DOUBLE PRECISION,
        semantic_threshold DOUBLE PRECISION,
        semantic_fit_hint TEXT,
        salary_upper_bound_gbp DOUBLE PRECISION,
        sent BOOLEAN NOT NULL DEFAULT FALSE,
        review_error_stage TEXT,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (recipient_id, job_url)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_seen_jobs_pending
    ON app_config.recipient_seen_jobs (is_seen, classification, updated_at)
    """,
]

SQLITE_DIGEST_QUEUE_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS recipient_digest_queue (
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        job_json TEXT NOT NULL,
        queued_run_id TEXT,
        first_queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (recipient_id, job_url)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_digest_queue_recipient
    ON recipient_digest_queue (recipient_id, first_queued_at)
    """,
]

POSTGRES_DIGEST_QUEUE_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS app_config.recipient_digest_queue (
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        job_json JSONB NOT NULL,
        queued_run_id TEXT,
        first_queued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (recipient_id, job_url)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_digest_queue_recipient
    ON app_config.recipient_digest_queue (recipient_id, first_queued_at)
    """,
]

SQLITE_REVIEW_AUDIT_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS recipient_review_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        source_type TEXT,
        target_value TEXT,
        company_name TEXT,
        title TEXT,
        location TEXT,
        review_family TEXT NOT NULL,
        classification TEXT NOT NULL,
        stage TEXT,
        seen_recorded INTEGER NOT NULL DEFAULT 0,
        sent INTEGER NOT NULL DEFAULT 0,
        hard_filter_reason TEXT,
        semantic_rank INTEGER,
        raw_embedding_score REAL,
        semantic_score REAL,
        semantic_threshold REAL,
        semantic_top_profile TEXT,
        semantic_second_profile TEXT,
        semantic_fit_summary TEXT,
        title_boost_multiplier REAL,
        salary_upper_bound_gbp REAL,
        salary_penalty_applied REAL,
        gemini_pass1_score INTEGER,
        gemini_pass2_score INTEGER,
        gemini_matched_profile TEXT,
        gemini_reason TEXT,
        supporting_evidence_json TEXT,
        mismatch_evidence_json TEXT,
        review_error_stage TEXT,
        review_error TEXT,
        metadata_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_recipient_created
    ON recipient_review_audit (recipient_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_run
    ON recipient_review_audit (run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_classification
    ON recipient_review_audit (classification)
    """,
]

POSTGRES_REVIEW_AUDIT_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS app_config.recipient_review_audit (
        audit_id BIGSERIAL PRIMARY KEY,
        run_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        job_url TEXT NOT NULL,
        source_type TEXT,
        target_value TEXT,
        company_name TEXT,
        title TEXT,
        location TEXT,
        review_family TEXT NOT NULL,
        classification TEXT NOT NULL,
        stage TEXT,
        seen_recorded BOOLEAN NOT NULL DEFAULT FALSE,
        sent BOOLEAN NOT NULL DEFAULT FALSE,
        hard_filter_reason TEXT,
        semantic_rank INTEGER,
        raw_embedding_score DOUBLE PRECISION,
        semantic_score DOUBLE PRECISION,
        semantic_threshold DOUBLE PRECISION,
        semantic_top_profile TEXT,
        semantic_second_profile TEXT,
        semantic_fit_summary TEXT,
        title_boost_multiplier DOUBLE PRECISION,
        salary_upper_bound_gbp DOUBLE PRECISION,
        salary_penalty_applied DOUBLE PRECISION,
        gemini_pass1_score INTEGER,
        gemini_pass2_score INTEGER,
        gemini_matched_profile TEXT,
        gemini_reason TEXT,
        supporting_evidence_json JSONB,
        mismatch_evidence_json JSONB,
        review_error_stage TEXT,
        review_error TEXT,
        metadata_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_recipient_created
    ON app_config.recipient_review_audit (recipient_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_run
    ON app_config.recipient_review_audit (run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_review_audit_classification
    ON app_config.recipient_review_audit (classification)
    """,
]

SQLITE_RECIPIENT_PROFILE_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS recipient_profiles (
        recipient_id TEXT NOT NULL PRIMARY KEY,
        email TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        config_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recipient_profile_versions (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_id TEXT NOT NULL,
        email TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        config_json TEXT NOT NULL,
        saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

DEFAULT_AUDIT_KEEP_ROWS = 1000
DEFAULT_AUDIT_HIGH_WATER_ROWS = 1500
PENDING_JOB_STATE_CLASSIFICATIONS = (
    "semantic_above_threshold_not_reviewed",
    "gemini_client_setup_failed_not_seen",
    "gemini_batch_failed_not_seen",
    "gemini_pass1_approved_final_failed_not_seen",
)
EXPIRED_JOB_STATE_CLASSIFICATION = "expired_unavailable_seen"

POSTGRES_RECIPIENT_PROFILE_SCHEMA_STATEMENTS = [
    "CREATE SCHEMA IF NOT EXISTS app_config",
    """
    CREATE TABLE IF NOT EXISTS app_config.recipient_profiles (
        recipient_id TEXT NOT NULL PRIMARY KEY,
        email TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        config_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_config.recipient_profile_versions (
        version_id BIGSERIAL PRIMARY KEY,
        recipient_id TEXT NOT NULL,
        email TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        config_json JSONB NOT NULL,
        saved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


def create_storage(database_url=None):
    return Storage(database_url or os.getenv("DATABASE_URL", "sqlite:///job_scraper.db"))


class Storage:
    def __init__(self, database_url):
        self.database_url = database_url
        self.backend = self._detect_backend(database_url)
        self.sqlite_path = (
            self._resolve_sqlite_path(database_url)
            if self.backend == "sqlite"
            else None
        )

    def ensure_schema(self):
        if self.backend == "sqlite":
            self._ensure_sqlite_schema()
            return

        self._ensure_postgres_schema()

    def load_recipient_profile_configs(self, enabled_only=True):
        rows = self.load_recipient_profile_records(enabled_only=enabled_only)
        configs = []
        for row in rows:
            parsed = row.get("config")
            if isinstance(parsed, dict):
                configs.append(parsed)
        return configs

    def load_recipient_profile_records(self, enabled_only=True):
        rows = self._fetch_all(
            f"""
            SELECT recipient_id, email, enabled, config_json, created_at, updated_at
            FROM {self._recipient_profiles_table_name()}
            {"WHERE enabled = " + self._true_literal() if enabled_only else ""}
            ORDER BY recipient_id
            """,
            (),
        )
        records = []
        for row in rows:
            parsed = self._load_json_field(row.get("config_json"))
            if not isinstance(parsed, dict):
                continue
            records.append(
                {
                    **row,
                    "enabled": self._coerce_bool(row.get("enabled")),
                    "config": parsed,
                }
            )
        return records

    def load_recipient_profile_versions(self, recipient_id, limit=20):
        rows = self._fetch_all(
            self._sql(
                f"""
                SELECT version_id, recipient_id, email, enabled, config_json, saved_at
                FROM {self._recipient_profile_versions_table_name()}
                WHERE recipient_id = {{placeholder}}
                ORDER BY saved_at DESC, version_id DESC
                LIMIT {{placeholder}}
                """
            ),
            (recipient_id, max(1, int(limit))),
        )
        versions = []
        for row in rows:
            parsed = self._load_json_field(row.get("config_json"))
            if not isinstance(parsed, dict):
                continue
            versions.append(
                {
                    **row,
                    "enabled": self._coerce_bool(row.get("enabled")),
                    "config": parsed,
                }
            )
        return versions

    def load_recipient_profile_version(self, recipient_id, version_id):
        rows = self._fetch_all(
            self._sql(
                f"""
                SELECT version_id, recipient_id, email, enabled, config_json, saved_at
                FROM {self._recipient_profile_versions_table_name()}
                WHERE recipient_id = {{placeholder}}
                  AND version_id = {{placeholder}}
                """
            ),
            (recipient_id, version_id),
        )
        if not rows:
            return None

        row = rows[0]
        parsed = self._load_json_field(row.get("config_json"))
        if not isinstance(parsed, dict):
            return None
        return {
            **row,
            "enabled": self._coerce_bool(row.get("enabled")),
            "config": parsed,
        }

    def upsert_recipient_profile_configs(self, rows):
        if not rows:
            return

        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                for row in rows:
                    serialized = json.dumps(row["config"], ensure_ascii=True)
                    connection.execute(
                        """
                        INSERT INTO recipient_profiles (
                            recipient_id,
                            email,
                            enabled,
                            config_json,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(recipient_id) DO UPDATE SET
                            email = excluded.email,
                            enabled = excluded.enabled,
                            config_json = excluded.config_json,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            row["recipient_id"],
                            row["email"],
                            1 if row["enabled"] else 0,
                            serialized,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO recipient_profile_versions (
                            recipient_id,
                            email,
                            enabled,
                            config_json
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            row["recipient_id"],
                            row["email"],
                            1 if row["enabled"] else 0,
                            serialized,
                        ),
                    )
                connection.commit()
            finally:
                connection.close()
            return

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                for row in rows:
                    serialized = json.dumps(row["config"], ensure_ascii=True)
                    cursor.execute(
                        """
                        INSERT INTO app_config.recipient_profiles (
                            recipient_id,
                            email,
                            enabled,
                            config_json,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                        ON CONFLICT (recipient_id) DO UPDATE SET
                            email = EXCLUDED.email,
                            enabled = EXCLUDED.enabled,
                            config_json = EXCLUDED.config_json,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            row["recipient_id"],
                            row["email"],
                            row["enabled"],
                            serialized,
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO app_config.recipient_profile_versions (
                            recipient_id,
                            email,
                            enabled,
                            config_json
                        )
                        VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (
                            row["recipient_id"],
                            row["email"],
                            row["enabled"],
                            serialized,
                        ),
                    )
            connection.commit()
        finally:
            connection.close()

    def load_seen_urls(self, recipient_id):
        rows = self._fetch_all(
            self._sql(
                f"""
                SELECT job_url
                FROM {self._seen_jobs_table_name()}
                WHERE recipient_id = {{placeholder}}
                  AND is_seen = {self._true_literal()}
                """
            ),
            (recipient_id,),
        )
        return {row["job_url"] for row in rows if row.get("job_url")}

    def store_seen_jobs(self, recipient_id, jobs):
        state_rows = []
        for job in jobs:
            state_rows.append(
                {
                    "job_url": job.get("url", ""),
                    "source_type": job.get("source", ""),
                    "target_value": job.get("target_value", ""),
                    "company_name": job.get("company", ""),
                    "title": job.get("title", ""),
                    "location": job.get("location", ""),
                    "is_seen": True,
                    "processing_status": "processed",
                    "review_family": job.get("review_family"),
                    "classification": job.get("classification") or "seen",
                    "stage": job.get("stage"),
                    "sent": bool(job.get("sent", False)),
                }
            )
        self.store_job_state_rows(recipient_id, None, state_rows)

    def unmark_seen_job(self, recipient_id, job_url):
        """Allow a full re-evaluation on rediscovery, preserving review history."""
        if not recipient_id or not job_url:
            return 0

        placeholder = "?" if self.backend == "sqlite" else "%s"
        seen_false = "0" if self.backend == "sqlite" else "FALSE"
        connection = (
            self._connect_sqlite()
            if self.backend == "sqlite"
            else self._connect_postgres()
        )
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                UPDATE {self._seen_jobs_table_name()}
                SET is_seen = {seen_false},
                    processing_status = 'awaiting_main_run',
                    review_family = 'manual',
                    classification = 'manual_reset_unseen',
                    stage = 'manual_reset',
                    run_id = NULL,
                    semantic_rank = NULL,
                    raw_embedding_score = NULL,
                    semantic_score = NULL,
                    semantic_threshold = NULL,
                    semantic_fit_hint = NULL,
                    review_error_stage = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE recipient_id = {placeholder}
                  AND job_url = {placeholder}
                  AND is_seen = {self._true_literal()}
                """,
                (recipient_id, job_url),
            )
            updated_count = cursor.rowcount
            if updated_count:
                # A queued approval belongs to the old review. Remove it in the
                # same transaction so it cannot send before the fresh decision.
                cursor.execute(
                    f"""
                    DELETE FROM {self._digest_queue_table_name()}
                    WHERE recipient_id = {placeholder}
                      AND job_url = {placeholder}
                    """,
                    (recipient_id, job_url),
                )
            connection.commit()
            return updated_count
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def store_job_state_rows(self, recipient_id, run_id, state_rows):
        rows = [
            self._normalize_job_state_row(recipient_id, run_id, row)
            for row in state_rows
            if row.get("job_url")
        ]

        if not rows:
            return

        columns = [
            "recipient_id",
            "job_url",
            "source_type",
            "target_value",
            "company_name",
            "title",
            "location",
            "is_seen",
            "processing_status",
            "review_family",
            "classification",
            "stage",
            "run_id",
            "semantic_rank",
            "raw_embedding_score",
            "semantic_score",
            "semantic_threshold",
            "semantic_fit_hint",
            "salary_upper_bound_gbp",
            "sent",
            "review_error_stage",
        ]

        if self.backend == "sqlite":
            placeholders = ", ".join("?" for _column in columns)
            connection = self._connect_sqlite()
            try:
                connection.executemany(
                    f"""
                    INSERT INTO recipient_seen_jobs (
                        {", ".join(columns)}
                    )
                    VALUES ({placeholders})
                    ON CONFLICT(recipient_id, job_url) DO UPDATE SET
                        source_type = excluded.source_type,
                        target_value = excluded.target_value,
                        company_name = excluded.company_name,
                        title = excluded.title,
                        location = excluded.location,
                        is_seen = CASE
                            WHEN recipient_seen_jobs.is_seen = 1
                              OR excluded.is_seen = 1
                            THEN 1 ELSE 0 END,
                        processing_status = CASE
                            WHEN recipient_seen_jobs.is_seen = 1
                              OR excluded.is_seen = 1
                            THEN 'processed'
                            ELSE excluded.processing_status
                        END,
                        review_family = excluded.review_family,
                        classification = excluded.classification,
                        stage = excluded.stage,
                        run_id = excluded.run_id,
                        semantic_rank = excluded.semantic_rank,
                        raw_embedding_score = excluded.raw_embedding_score,
                        semantic_score = excluded.semantic_score,
                        semantic_threshold = excluded.semantic_threshold,
                        semantic_fit_hint = excluded.semantic_fit_hint,
                        salary_upper_bound_gbp = excluded.salary_upper_bound_gbp,
                        sent = CASE
                            WHEN recipient_seen_jobs.sent = 1
                              OR excluded.sent = 1
                            THEN 1 ELSE 0 END,
                        review_error_stage = excluded.review_error_stage,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [tuple(row[column] for column in columns) for row in rows],
                )
                connection.commit()
            finally:
                connection.close()
            return

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                target_table = self._seen_jobs_conflict_target_name()
                for row in rows:
                    cursor.execute(
                        f"""
                        INSERT INTO {self._seen_jobs_table_name()} (
                            {", ".join(columns)}
                        )
                        VALUES (
                            {", ".join("%s" for _column in columns)}
                        )
                        ON CONFLICT (recipient_id, job_url) DO UPDATE SET
                            source_type = EXCLUDED.source_type,
                            target_value = EXCLUDED.target_value,
                            company_name = EXCLUDED.company_name,
                            title = EXCLUDED.title,
                            location = EXCLUDED.location,
                            is_seen = {target_table}.is_seen
                                OR EXCLUDED.is_seen,
                            processing_status = CASE
                                WHEN {target_table}.is_seen
                                  OR EXCLUDED.is_seen
                                THEN 'processed'
                                ELSE EXCLUDED.processing_status
                            END,
                            review_family = EXCLUDED.review_family,
                            classification = EXCLUDED.classification,
                            stage = EXCLUDED.stage,
                            run_id = EXCLUDED.run_id,
                            semantic_rank = EXCLUDED.semantic_rank,
                            raw_embedding_score = EXCLUDED.raw_embedding_score,
                            semantic_score = EXCLUDED.semantic_score,
                            semantic_threshold = EXCLUDED.semantic_threshold,
                            semantic_fit_hint = EXCLUDED.semantic_fit_hint,
                            salary_upper_bound_gbp = EXCLUDED.salary_upper_bound_gbp,
                            sent = {target_table}.sent
                                OR EXCLUDED.sent,
                            review_error_stage = EXCLUDED.review_error_stage,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        tuple(row[column] for column in columns),
                    )
            connection.commit()
        finally:
            connection.close()

    def store_digest_queue_jobs(self, recipient_id, run_id, jobs):
        rows = [
            (
                recipient_id,
                job.get("url", ""),
                json.dumps(job, ensure_ascii=True, default=str),
                run_id,
            )
            for job in jobs or []
            if job.get("url")
        ]
        if not rows:
            return

        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                connection.executemany(
                    """
                    INSERT INTO recipient_digest_queue (
                        recipient_id,
                        job_url,
                        job_json,
                        queued_run_id,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(recipient_id, job_url) DO UPDATE SET
                        job_json = excluded.job_json,
                        queued_run_id = excluded.queued_run_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    rows,
                )
                connection.commit()
            finally:
                connection.close()
            return

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO app_config.recipient_digest_queue (
                        recipient_id,
                        job_url,
                        job_json,
                        queued_run_id,
                        updated_at
                    )
                    VALUES (%s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (recipient_id, job_url) DO UPDATE SET
                        job_json = EXCLUDED.job_json,
                        queued_run_id = EXCLUDED.queued_run_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    rows,
                )
            connection.commit()
        finally:
            connection.close()

    def load_digest_queue_jobs(self, recipient_id):
        rows = self._fetch_all(
            self._sql(
                f"""
                SELECT job_json
                FROM {self._digest_queue_table_name()}
                WHERE recipient_id = {{placeholder}}
                ORDER BY first_queued_at ASC, updated_at ASC
                """
            ),
            (recipient_id,),
        )
        jobs = []
        for row in rows:
            parsed = self._load_json_field(row.get("job_json"))
            if isinstance(parsed, dict) and parsed.get("url"):
                jobs.append(parsed)
        return jobs

    def mark_digest_queue_jobs_sent(self, recipient_id, job_urls, run_id=None):
        clean_urls = [url for url in dict.fromkeys(job_urls or []) if url]
        if not clean_urls:
            return

        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                for job_url in clean_urls:
                    connection.execute(
                        """
                        UPDATE recipient_seen_jobs
                        SET
                            sent = 1,
                            run_id = COALESCE(?, run_id),
                            classification = CASE classification
                                WHEN 'gemini_pass2_approved_queued_seen'
                                    THEN 'gemini_pass2_approved_sent_seen'
                                WHEN 'semantic_above_threshold_queued_seen'
                                    THEN 'semantic_above_threshold_sent_seen'
                                ELSE classification
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE recipient_id = ?
                          AND job_url = ?
                        """,
                        (run_id, recipient_id, job_url),
                    )
                    connection.execute(
                        """
                        DELETE FROM recipient_digest_queue
                        WHERE recipient_id = ?
                          AND job_url = ?
                        """,
                        (recipient_id, job_url),
                    )
                connection.commit()
            finally:
                connection.close()
            return

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                for job_url in clean_urls:
                    cursor.execute(
                        """
                        UPDATE app_config.recipient_seen_jobs
                        SET
                            sent = TRUE,
                            run_id = COALESCE(%s, run_id),
                            classification = CASE classification
                                WHEN 'gemini_pass2_approved_queued_seen'
                                    THEN 'gemini_pass2_approved_sent_seen'
                                WHEN 'semantic_above_threshold_queued_seen'
                                    THEN 'semantic_above_threshold_sent_seen'
                                ELSE classification
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE recipient_id = %s
                          AND job_url = %s
                        """,
                        (run_id, recipient_id, job_url),
                    )
                    cursor.execute(
                        """
                        DELETE FROM app_config.recipient_digest_queue
                        WHERE recipient_id = %s
                          AND job_url = %s
                        """,
                        (recipient_id, job_url),
                    )
            connection.commit()
        finally:
            connection.close()

    def store_review_audit_rows(self, recipient_id, run_id, audit_rows):
        rows = [
            self._normalize_review_audit_row(recipient_id, run_id, row)
            for row in audit_rows
            if row.get("job_url")
        ]
        if not rows:
            return

        columns = [
            "run_id",
            "recipient_id",
            "job_url",
            "source_type",
            "target_value",
            "company_name",
            "title",
            "location",
            "review_family",
            "classification",
            "stage",
            "seen_recorded",
            "sent",
            "hard_filter_reason",
            "semantic_rank",
            "raw_embedding_score",
            "semantic_score",
            "semantic_threshold",
            "semantic_top_profile",
            "semantic_second_profile",
            "semantic_fit_summary",
            "title_boost_multiplier",
            "salary_upper_bound_gbp",
            "salary_penalty_applied",
            "gemini_pass1_score",
            "gemini_pass2_score",
            "gemini_matched_profile",
            "gemini_reason",
            "supporting_evidence_json",
            "mismatch_evidence_json",
            "review_error_stage",
            "review_error",
            "metadata_json",
        ]

        if self.backend == "sqlite":
            placeholders = ", ".join("?" for _column in columns)
            connection = self._connect_sqlite()
            try:
                connection.executemany(
                    f"""
                    INSERT INTO {self._review_audit_table_name()} (
                        {", ".join(columns)}
                    )
                    VALUES ({placeholders})
                    """,
                    [tuple(row[column] for column in columns) for row in rows],
                )
                connection.commit()
            finally:
                connection.close()
            self.prune_review_audit_rows()
            return

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                value_placeholders = [
                    "%s::jsonb"
                    if column
                    in {
                        "supporting_evidence_json",
                        "mismatch_evidence_json",
                        "metadata_json",
                    }
                    else "%s"
                    for column in columns
                ]
                for row in rows:
                    cursor.execute(
                        f"""
                        INSERT INTO {self._review_audit_table_name()} (
                            {", ".join(columns)}
                        )
                        VALUES (
                            {", ".join(value_placeholders)}
                        )
                        """,
                        tuple(row[column] for column in columns),
                    )
            connection.commit()
        finally:
            connection.close()
        self.prune_review_audit_rows()

    def prune_review_audit_rows(self, keep_rows=None, high_water_rows=None):
        keep_rows, high_water_rows = self._review_audit_retention_limits(
            keep_rows,
            high_water_rows,
        )
        row_count = self._review_audit_row_count()
        if row_count <= high_water_rows:
            return 0

        delete_count = row_count - keep_rows
        if delete_count <= 0:
            return 0

        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                cursor = connection.execute(
                    """
                    DELETE FROM recipient_review_audit
                    WHERE audit_id IN (
                        SELECT audit_id
                        FROM recipient_review_audit
                        ORDER BY created_at ASC, audit_id ASC
                        LIMIT ?
                    )
                    """,
                    (delete_count,),
                )
                connection.commit()
                return cursor.rowcount
            finally:
                connection.close()

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM app_config.recipient_review_audit
                    WHERE audit_id IN (
                        SELECT audit_id
                        FROM app_config.recipient_review_audit
                        ORDER BY created_at ASC, audit_id ASC
                        LIMIT %s
                    )
                    """,
                    (delete_count,),
                )
                deleted_rows = cursor.rowcount
            connection.commit()
            return deleted_rows
        finally:
            connection.close()

    def load_review_audit_rows(
        self,
        limit=None,
        recipient_id=None,
        classification=None,
        review_family=None,
        run_id=None,
        latest_first=False,
        sort=None,
    ):
        filters = []
        params = []
        placeholder = "?" if self.backend == "sqlite" else "%s"

        for column_name, value in (
            ("recipient_id", recipient_id),
            ("classification", classification),
            ("review_family", review_family),
            ("run_id", run_id),
        ):
            if value:
                filters.append(f"{column_name} = {placeholder}")
                params.append(value)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        order_clause = self._review_audit_order_clause(sort, latest_first)
        limit_clause = ""
        if limit is not None:
            limit_clause = f"LIMIT {placeholder}"
            params.append(max(1, int(limit)))

        return self._fetch_all(
            f"""
            SELECT *
            FROM {self._review_audit_table_name()}
            {where_clause}
            ORDER BY {order_clause}
            {limit_clause}
            """,
            tuple(params),
        )

    def load_review_audit_filter_values(self):
        rows = self._fetch_all(
            f"""
            SELECT recipient_id, review_family, classification, run_id
            FROM {self._review_audit_table_name()}
            ORDER BY created_at DESC, audit_id DESC
            """,
            (),
        )
        return {
            "recipient_ids": self._unique_values(row.get("recipient_id") for row in rows),
            "review_families": self._unique_values(row.get("review_family") for row in rows),
            "classifications": self._unique_values(row.get("classification") for row in rows),
            "run_ids": self._unique_values(row.get("run_id") for row in rows),
        }

    def count_recent_unseen_review_backlog(self, max_age_hours=None):
        return self.count_recent_pending_job_backlog(max_age_hours=max_age_hours)

    def load_pending_job_backlog(self, recipient_id, limit=None):
        placeholder = "?" if self.backend == "sqlite" else "%s"
        classification_placeholders = ", ".join(
            placeholder for _classification in PENDING_JOB_STATE_CLASSIFICATIONS
        )
        seen_false = "0" if self.backend == "sqlite" else "FALSE"
        params = [recipient_id, *PENDING_JOB_STATE_CLASSIFICATIONS]
        limit_clause = ""
        if limit is not None:
            limit_clause = f"LIMIT {placeholder}"
            params.append(max(1, int(limit)))

        return self._fetch_all(
            f"""
            SELECT
                recipient_id,
                job_url,
                source_type,
                target_value,
                company_name,
                title,
                location,
                is_seen,
                processing_status,
                review_family,
                classification,
                stage,
                run_id,
                semantic_rank,
                raw_embedding_score,
                semantic_score,
                semantic_threshold,
                semantic_fit_hint,
                salary_upper_bound_gbp,
                sent,
                review_error_stage,
                first_seen_at,
                updated_at
            FROM {self._seen_jobs_table_name()}
            WHERE recipient_id = {placeholder}
              AND is_seen = {seen_false}
              AND classification IN ({classification_placeholders})
            ORDER BY
                semantic_rank IS NULL ASC,
                semantic_rank ASC,
                semantic_score DESC,
                updated_at ASC,
                job_url ASC
            {limit_clause}
            """,
            tuple(params),
        )

    def mark_pending_job_expired(self, recipient_id, job_url, run_id=None, reason=None):
        if not recipient_id or not job_url:
            return 0

        placeholder = "?" if self.backend == "sqlite" else "%s"
        classification_placeholders = ", ".join(
            placeholder for _classification in PENDING_JOB_STATE_CLASSIFICATIONS
        )
        seen_false = "0" if self.backend == "sqlite" else "FALSE"
        seen_true = "1" if self.backend == "sqlite" else "TRUE"
        params = [
            run_id,
            recipient_id,
            job_url,
            *PENDING_JOB_STATE_CLASSIFICATIONS,
        ]

        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                cursor = connection.execute(
                    f"""
                    UPDATE recipient_seen_jobs
                    SET
                        is_seen = {seen_true},
                        processing_status = 'processed',
                        classification = ?,
                        run_id = COALESCE(?, run_id),
                        review_error_stage = 'url_refetch',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE recipient_id = ?
                      AND job_url = ?
                      AND is_seen = {seen_false}
                      AND classification IN ({classification_placeholders})
                    """,
                    (
                        EXPIRED_JOB_STATE_CLASSIFICATION,
                        *params,
                    ),
                )
                connection.commit()
                return cursor.rowcount
            finally:
                connection.close()

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE app_config.recipient_seen_jobs
                    SET
                        is_seen = {seen_true},
                        processing_status = 'processed',
                        classification = %s,
                        run_id = COALESCE(%s, run_id),
                        review_error_stage = 'url_refetch',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE recipient_id = %s
                      AND job_url = %s
                      AND is_seen = {seen_false}
                      AND classification IN ({classification_placeholders})
                    """,
                    (
                        EXPIRED_JOB_STATE_CLASSIFICATION,
                        *params,
                    ),
                )
                updated_count = cursor.rowcount
            connection.commit()
            return updated_count
        finally:
            connection.close()

    def count_recent_pending_job_backlog(self, max_age_hours=None):
        placeholder = "?" if self.backend == "sqlite" else "%s"
        classification_placeholders = ", ".join(
            placeholder for _classification in PENDING_JOB_STATE_CLASSIFICATIONS
        )
        seen_false = "0" if self.backend == "sqlite" else "FALSE"
        filters = [
            f"is_seen = {seen_false}",
            f"classification IN ({classification_placeholders})",
        ]
        params = list(PENDING_JOB_STATE_CLASSIFICATIONS)

        if max_age_hours is not None:
            hours = max(1, int(max_age_hours))
            if self.backend == "sqlite":
                filters.append("updated_at >= datetime('now', ?)")
                params.append(f"-{hours} hours")
            else:
                filters.append(
                    "updated_at >= (CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour'))"
                )
                params.append(hours)

        rows = self._fetch_all(
            f"""
            SELECT COUNT(*) AS row_count
            FROM (
                SELECT recipient_id, job_url
                FROM {self._seen_jobs_table_name()}
                WHERE {" AND ".join(filters)}
                GROUP BY recipient_id, job_url
            ) backlog
            """,
            tuple(params),
        )
        return int(rows[0]["row_count"]) if rows else 0

    def _fetch_all(self, query, params):
        if self.backend == "sqlite":
            connection = self._connect_sqlite()
            try:
                cursor = connection.execute(query, params)
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                connection.close()

        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                columns = [column.name for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            connection.close()

    def _ensure_sqlite_schema(self):
        connection = self._connect_sqlite()
        try:
            connection.execute(SQLITE_SEEN_JOBS_SCHEMA_STATEMENTS[0])
            self._ensure_sqlite_columns(
                connection,
                "recipient_seen_jobs",
                {
                    "is_seen": "INTEGER NOT NULL DEFAULT 1",
                    "processing_status": "TEXT NOT NULL DEFAULT 'processed'",
                    "review_family": "TEXT",
                    "classification": "TEXT",
                    "stage": "TEXT",
                    "run_id": "TEXT",
                    "semantic_rank": "INTEGER",
                    "raw_embedding_score": "REAL",
                    "semantic_score": "REAL",
                    "semantic_threshold": "REAL",
                    "semantic_fit_hint": "TEXT",
                    "salary_upper_bound_gbp": "REAL",
                    "sent": "INTEGER NOT NULL DEFAULT 0",
                    "review_error_stage": "TEXT",
                    "updated_at": "TEXT",
                },
            )
            connection.execute(
                """
                UPDATE recipient_seen_jobs
                SET updated_at = COALESCE(updated_at, first_seen_at, CURRENT_TIMESTAMP)
                WHERE updated_at IS NULL
                """
            )
            for statement in SQLITE_SEEN_JOBS_SCHEMA_STATEMENTS[1:]:
                connection.execute(statement)
            for statement in SQLITE_DIGEST_QUEUE_SCHEMA_STATEMENTS:
                connection.execute(statement)
            for statement in SQLITE_REVIEW_AUDIT_SCHEMA_STATEMENTS:
                connection.execute(statement)
            self._ensure_sqlite_columns(
                connection,
                "recipient_review_audit",
                {"raw_embedding_score": "REAL"},
            )
            for statement in SQLITE_RECIPIENT_PROFILE_SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()

    def _ensure_postgres_schema(self):
        connection = self._connect_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS app_config")
                for statement in POSTGRES_SEEN_JOBS_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                for statement in POSTGRES_DIGEST_QUEUE_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                for statement in POSTGRES_REVIEW_AUDIT_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                self._ensure_postgres_seen_job_columns(cursor)
                cursor.execute(
                    """
                    ALTER TABLE app_config.recipient_review_audit
                    ADD COLUMN IF NOT EXISTS raw_embedding_score DOUBLE PRECISION
                    """
                )
                for statement in POSTGRES_RECIPIENT_PROFILE_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                self._migrate_public_seen_jobs_to_app_config(cursor)
                self._migrate_public_review_audit_to_app_config(cursor)
            connection.commit()
        finally:
            connection.close()

    def _connect_sqlite(self):
        connection = sqlite3.connect(self.sqlite_path)
        return connection

    @staticmethod
    def _ensure_sqlite_columns(connection, table_name, columns):
        existing_columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table_name})")
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )

    @staticmethod
    def _ensure_postgres_seen_job_columns(cursor):
        columns = {
            "is_seen": "BOOLEAN NOT NULL DEFAULT TRUE",
            "processing_status": "TEXT NOT NULL DEFAULT 'processed'",
            "review_family": "TEXT",
            "classification": "TEXT",
            "stage": "TEXT",
            "run_id": "TEXT",
            "semantic_rank": "INTEGER",
            "raw_embedding_score": "DOUBLE PRECISION",
            "semantic_score": "DOUBLE PRECISION",
            "semantic_threshold": "DOUBLE PRECISION",
            "semantic_fit_hint": "TEXT",
            "salary_upper_bound_gbp": "DOUBLE PRECISION",
            "sent": "BOOLEAN NOT NULL DEFAULT FALSE",
            "review_error_stage": "TEXT",
            "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, column_type in columns.items():
            cursor.execute(
                f"""
                ALTER TABLE app_config.recipient_seen_jobs
                ADD COLUMN IF NOT EXISTS {column_name} {column_type}
                """
            )

    @staticmethod
    def _migrate_public_seen_jobs_to_app_config(cursor):
        cursor.execute("SELECT to_regclass('public.recipient_seen_jobs') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return

        cursor.execute(
            """
            INSERT INTO app_config.recipient_seen_jobs (
                recipient_id,
                job_url,
                source_type,
                target_value,
                company_name,
                title,
                location,
                is_seen,
                processing_status,
                classification,
                first_seen_at,
                updated_at
            )
            SELECT
                recipient_id,
                job_url,
                COALESCE(source_type, ''),
                target_value,
                company_name,
                title,
                location,
                TRUE,
                'processed',
                'seen',
                first_seen_at::timestamptz,
                first_seen_at::timestamptz
            FROM public.recipient_seen_jobs
            ON CONFLICT (recipient_id, job_url) DO NOTHING
            """
        )

    @staticmethod
    def _migrate_public_review_audit_to_app_config(cursor):
        cursor.execute("SELECT to_regclass('public.recipient_review_audit') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'recipient_review_audit'
            """
        )
        public_columns = {row[0] for row in cursor.fetchall()}
        raw_embedding_select = (
            "raw_embedding_score"
            if "raw_embedding_score" in public_columns
            else "NULL"
        )
        cursor.execute(
            f"""
            INSERT INTO app_config.recipient_review_audit (
                run_id,
                recipient_id,
                job_url,
                source_type,
                target_value,
                company_name,
                title,
                location,
                review_family,
                classification,
                stage,
                seen_recorded,
                sent,
                hard_filter_reason,
                semantic_rank,
                raw_embedding_score,
                semantic_score,
                semantic_threshold,
                semantic_top_profile,
                semantic_second_profile,
                semantic_fit_summary,
                title_boost_multiplier,
                salary_upper_bound_gbp,
                salary_penalty_applied,
                gemini_pass1_score,
                gemini_pass2_score,
                gemini_matched_profile,
                gemini_reason,
                supporting_evidence_json,
                mismatch_evidence_json,
                review_error_stage,
                review_error,
                metadata_json,
                created_at
            )
            SELECT
                run_id,
                recipient_id,
                job_url,
                source_type,
                target_value,
                company_name,
                title,
                location,
                review_family,
                classification,
                stage,
                seen_recorded,
                sent,
                hard_filter_reason,
                semantic_rank,
                {raw_embedding_select},
                semantic_score,
                semantic_threshold,
                semantic_top_profile,
                semantic_second_profile,
                semantic_fit_summary,
                title_boost_multiplier,
                salary_upper_bound_gbp,
                salary_penalty_applied,
                gemini_pass1_score,
                gemini_pass2_score,
                gemini_matched_profile,
                gemini_reason,
                supporting_evidence_json,
                mismatch_evidence_json,
                review_error_stage,
                review_error,
                metadata_json,
                created_at::timestamptz
            FROM public.recipient_review_audit old_audit
            WHERE NOT EXISTS (
                SELECT 1
                FROM app_config.recipient_review_audit migrated
                WHERE migrated.run_id = old_audit.run_id
                  AND migrated.recipient_id = old_audit.recipient_id
                  AND migrated.job_url = old_audit.job_url
                  AND migrated.review_family = old_audit.review_family
                  AND migrated.classification = old_audit.classification
                  AND COALESCE(migrated.stage, '') = COALESCE(old_audit.stage, '')
                  AND migrated.created_at = old_audit.created_at::timestamptz
            )
            """
        )

    def _connect_postgres(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "Postgres support requires psycopg. Install dependencies from requirements.txt."
            ) from exc

        try:
            return psycopg.connect(self.database_url)
        except psycopg.OperationalError as exc:
            message = str(exc)
            if "Network is unreachable" in message:
                raise RuntimeError(
                    "Postgres connection failed because the configured host is not "
                    "reachable from GitHub Actions. If you are using Supabase, use "
                    "the pooled IPv4 connection string instead of the direct database host."
                ) from exc
            raise

    def _sql(self, template):
        placeholder = "?" if self.backend == "sqlite" else "%s"
        return template.replace("{placeholder}", placeholder)

    def _recipient_profiles_table_name(self):
        if self.backend == "sqlite":
            return "recipient_profiles"
        return "app_config.recipient_profiles"

    def _recipient_profile_versions_table_name(self):
        if self.backend == "sqlite":
            return "recipient_profile_versions"
        return "app_config.recipient_profile_versions"

    def _seen_jobs_table_name(self):
        if self.backend == "sqlite":
            return "recipient_seen_jobs"
        return "app_config.recipient_seen_jobs"

    def _digest_queue_table_name(self):
        if self.backend == "sqlite":
            return "recipient_digest_queue"
        return "app_config.recipient_digest_queue"

    def _seen_jobs_conflict_target_name(self):
        return "recipient_seen_jobs"

    def _review_audit_table_name(self):
        if self.backend == "sqlite":
            return "recipient_review_audit"
        return "app_config.recipient_review_audit"

    def _true_literal(self):
        return "1" if self.backend == "sqlite" else "TRUE"

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
    def _unique_values(values):
        return [
            value
            for value in dict.fromkeys(values)
            if value not in (None, "")
        ]

    @staticmethod
    def _review_audit_order_clause(sort, latest_first=False):
        orderings = {
            "raw_embedding_score_desc": (
                "raw_embedding_score IS NULL ASC, raw_embedding_score DESC, "
                "semantic_rank IS NULL ASC, semantic_rank ASC, audit_id ASC"
            ),
            "raw_embedding_score_asc": (
                "raw_embedding_score IS NULL ASC, raw_embedding_score ASC, "
                "semantic_rank IS NULL ASC, semantic_rank DESC, audit_id ASC"
            ),
            "semantic_score_desc": (
                "semantic_score IS NULL ASC, semantic_score DESC, "
                "semantic_rank IS NULL ASC, semantic_rank ASC, audit_id ASC"
            ),
            "semantic_score_asc": (
                "semantic_score IS NULL ASC, semantic_score ASC, "
                "semantic_rank IS NULL ASC, semantic_rank DESC, audit_id ASC"
            ),
            "semantic_rank": (
                "semantic_rank IS NULL ASC, semantic_rank ASC, audit_id ASC"
            ),
            "oldest": "created_at ASC, audit_id ASC",
            "latest": "created_at DESC, audit_id DESC",
        }
        if sort in orderings:
            return orderings[sort]

        if latest_first:
            return orderings["latest"]
        return orderings["oldest"]

    def _review_audit_row_count(self):
        rows = self._fetch_all(
            f"SELECT COUNT(*) AS row_count FROM {self._review_audit_table_name()}",
            (),
        )
        return int(rows[0]["row_count"]) if rows else 0

    def _review_audit_retention_limits(self, keep_rows=None, high_water_rows=None):
        keep = self._safe_int_env(
            "JOB_SCRAPER_AUDIT_KEEP_ROWS",
            DEFAULT_AUDIT_KEEP_ROWS,
            override=keep_rows,
        )
        high_water = self._safe_int_env(
            "JOB_SCRAPER_AUDIT_HIGH_WATER_ROWS",
            DEFAULT_AUDIT_HIGH_WATER_ROWS,
            override=high_water_rows,
        )
        keep = max(1, keep)
        high_water = max(keep, high_water)
        return keep, high_water

    def _normalize_job_state_row(self, recipient_id, run_id, row):
        is_seen = bool(row.get("is_seen", row.get("seen_recorded", False)))
        return {
            "recipient_id": recipient_id,
            "job_url": row.get("job_url", ""),
            "source_type": row.get("source_type", ""),
            "target_value": row.get("target_value", ""),
            "company_name": row.get("company_name", ""),
            "title": row.get("title", ""),
            "location": row.get("location", ""),
            "is_seen": is_seen,
            "processing_status": "processed"
            if is_seen
            else row.get("processing_status", "pending_review"),
            "review_family": row.get("review_family"),
            "classification": row.get("classification"),
            "stage": row.get("stage"),
            "run_id": row.get("run_id") or run_id,
            "semantic_rank": row.get("semantic_rank"),
            "raw_embedding_score": row.get("raw_embedding_score"),
            "semantic_score": row.get("semantic_score"),
            "semantic_threshold": row.get("semantic_threshold"),
            "semantic_fit_hint": (
                row.get("semantic_fit_hint") or row.get("semantic_fit_summary")
            ),
            "salary_upper_bound_gbp": row.get("salary_upper_bound_gbp"),
            "sent": bool(row.get("sent", False)),
            "review_error_stage": row.get("review_error_stage"),
        }

    def _normalize_review_audit_row(self, recipient_id, run_id, row):
        metadata = row.get("metadata") or {}
        return {
            "run_id": run_id,
            "recipient_id": recipient_id,
            "job_url": row.get("job_url", ""),
            "source_type": row.get("source_type", ""),
            "target_value": row.get("target_value", ""),
            "company_name": row.get("company_name", ""),
            "title": row.get("title", ""),
            "location": row.get("location", ""),
            "review_family": row.get("review_family", ""),
            "classification": row.get("classification", ""),
            "stage": row.get("stage", ""),
            "seen_recorded": bool(row.get("seen_recorded", False)),
            "sent": bool(row.get("sent", False)),
            "hard_filter_reason": row.get("hard_filter_reason"),
            "semantic_rank": row.get("semantic_rank"),
            "raw_embedding_score": row.get("raw_embedding_score"),
            "semantic_score": row.get("semantic_score"),
            "semantic_threshold": row.get("semantic_threshold"),
            "semantic_top_profile": row.get("semantic_top_profile"),
            "semantic_second_profile": row.get("semantic_second_profile"),
            "semantic_fit_summary": row.get("semantic_fit_summary"),
            "title_boost_multiplier": row.get("title_boost_multiplier"),
            "salary_upper_bound_gbp": row.get("salary_upper_bound_gbp"),
            "salary_penalty_applied": row.get("salary_penalty_applied"),
            "gemini_pass1_score": row.get("gemini_pass1_score"),
            "gemini_pass2_score": row.get("gemini_pass2_score"),
            "gemini_matched_profile": row.get("gemini_matched_profile"),
            "gemini_reason": row.get("gemini_reason"),
            "supporting_evidence_json": self._json_dump(
                row.get("supporting_evidence") or []
            ),
            "mismatch_evidence_json": self._json_dump(
                row.get("mismatch_evidence") or []
            ),
            "review_error_stage": row.get("review_error_stage"),
            "review_error": row.get("review_error"),
            "metadata_json": self._json_dump(metadata),
        }

    @staticmethod
    def _json_dump(value):
        return json.dumps(value, ensure_ascii=True)

    @staticmethod
    def _safe_int_env(name, default_value, override=None):
        if override is not None:
            return int(override)

        raw_value = os.getenv(name, "").strip()
        if not raw_value:
            return int(default_value)

        try:
            return int(raw_value)
        except ValueError:
            return int(default_value)

    @staticmethod
    def _load_json_field(value):
        if isinstance(value, dict):
            return value

        if not value:
            return None

        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")

        if isinstance(value, str):
            return json.loads(value)

        return None

    @staticmethod
    def _detect_backend(database_url):
        if database_url.startswith("sqlite:///"):
            return "sqlite"

        if database_url.startswith("postgres://") or database_url.startswith(
            "postgresql://"
        ):
            return "postgres"

        raise RuntimeError(
            "Unsupported DATABASE_URL. Use sqlite:///job_scraper.db or a postgres connection string."
        )

    @staticmethod
    def _resolve_sqlite_path(database_url):
        relative_path = database_url.replace("sqlite:///", "", 1)
        candidate_path = Path(relative_path)
        if candidate_path.is_absolute():
            return str(candidate_path.resolve())
        return str((BASE_DIR / candidate_path).resolve())
