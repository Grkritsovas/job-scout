import threading


def _format_log_value(value, max_length=180):
    if value is None:
        return ""

    cleaned = " ".join(str(value).split())
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."
    return cleaned.replace('"', "'")


def _format_count_map(values):
    return ",".join(
        f"{key}:{count}"
        for key, count in sorted(
            (values or {}).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ) or "-"


class ScrapeDiagnostics:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.target_summaries = []
        self.source_failures = []
        self.recipient_summaries = []
        self.run_summaries = []
        self.description_fallbacks = []
        self.url_rejections = []
        self._lock = threading.Lock()

    def record_target_summary(self, source, target, summary):
        if not self.enabled:
            return

        payload = {"source": source, "target": target, **summary}
        sample_title = payload.get("sample_title") or "-"
        reason = payload.get("reason") or "-"
        with self._lock:
            self.target_summaries.append(payload)
            print(
                f"[scrape:{source}:{target}] "
                f"fetched={payload.get('fetched_jobs', 0)} "
                f"location={payload.get('location_jobs', 0)} "
                f"url_ok={payload.get('url_ok_jobs', 0)} "
                f"new={payload.get('new_jobs', 0)} "
                f"desc_ok={payload.get('description_ok_jobs', 0)} "
                f"desc_html={payload.get('html_like_descriptions', 0)} "
                f"usable={payload.get('usable_jobs', 0)} "
                f"reason={reason} "
                f"sample={sample_title}"
            )

    def record_source_failure(self, source, error):
        if not self.enabled:
            return

        payload = {
            "source": source,
            "error": _format_log_value(error),
        }
        with self._lock:
            self.source_failures.append(payload)
            print(
                f"[scrape_failure:{source}] "
                f'error="{payload["error"]}"'
            )

    def record_recipient_summary(self, recipient_id, summary):
        if not self.enabled:
            return

        payload = {"recipient_id": recipient_id, **summary}
        hard_filter_reasons = payload.get("hard_filter_reasons") or {}
        formatted_reasons = _format_count_map(hard_filter_reasons)
        review_mode = payload.get("review_mode") or "-"
        reviewed_jobs = payload.get("reviewed_jobs")
        reviewed_suffix = (
            f" reviewed={reviewed_jobs}"
            if reviewed_jobs is not None
            else ""
        )
        llm_shortlisted = payload.get("llm_shortlisted_jobs")
        llm_suffix = (
            f" llm_shortlisted={llm_shortlisted}"
            if llm_shortlisted is not None
            else ""
        )
        gemini_reviewed_jobs = payload.get("gemini_reviewed_jobs")
        gemini_reviewed_suffix = (
            f" gemini_reviewed={gemini_reviewed_jobs}"
            if gemini_reviewed_jobs is not None
            else ""
        )
        seen_recorded_jobs = payload.get("seen_recorded_jobs")
        seen_recorded_suffix = (
            f" seen_new={seen_recorded_jobs}"
            if seen_recorded_jobs is not None
            else ""
        )
        review_error = payload.get("review_error")
        review_error_suffix = (
            f' review_error="{_format_log_value(review_error)}"'
            if review_error
            else ""
        )
        review_error_stage = payload.get("review_error_stage")
        review_error_stage_suffix = (
            f" review_error_stage={_format_log_value(review_error_stage)}"
            if review_error_stage
            else ""
        )
        not_passed_to_review = payload.get("ranked_jobs_not_passed_to_review", 0)
        not_passed_suffix = (
            f" ranked_not_reviewed={not_passed_to_review}"
            if not_passed_to_review
            else ""
        )
        with self._lock:
            self.recipient_summaries.append(payload)
            print(
                f"[ranking:{recipient_id}] "
                f"input={payload.get('input_jobs', 0)} "
                f"seen_skipped={payload.get('seen_skipped_jobs', 0)} "
                f"hard_filtered={payload.get('hard_filtered_jobs', 0)} "
                f"below_threshold={payload.get('below_threshold_jobs', 0)} "
                f"ranked={payload.get('ranked_jobs', 0)} "
                f"ranked_jobs_passed_to_review={payload.get('ranked_jobs_passed_to_review', 0)} "
                f"{not_passed_suffix}"
                f"review_mode={review_mode}"
                f"{reviewed_suffix}"
                f"{seen_recorded_suffix}"
                f"{llm_suffix}"
                f"{gemini_reviewed_suffix}"
                f"{review_error_stage_suffix}"
                f"{review_error_suffix} "
                f"recipient_seen={payload.get('recipient_seen_urls', 0)} "
                f"hard_filter_reasons={formatted_reasons}"
            )

    def record_sponsor_lookup_summary(self, count):
        if not self.enabled:
            return

        with self._lock:
            print(f"[sponsorship] sponsor_lookup_companies={count}")

    def record_description_fallback(
        self,
        source,
        target,
        title,
        url,
        status,
        looks_like_html,
    ):
        if not self.enabled:
            return

        payload = {
            "source": source,
            "target": target,
            "title": title,
            "url": url,
            "status": status,
            "looks_like_html": looks_like_html,
        }
        with self._lock:
            self.description_fallbacks.append(payload)
            print(
                f"[description_fallback:{source}:{target}] "
                f"status={status} "
                f"html={1 if looks_like_html else 0} "
                f"title={title or '-'} "
                f"url={url or '-'}"
            )

    def record_url_rejection(self, source, target, title, raw_url):
        if not self.enabled:
            return

        payload = {
            "source": source,
            "target": target,
            "title": title,
            "raw_url": raw_url,
        }
        with self._lock:
            self.url_rejections.append(payload)
            print(
                f"[url_reject:{source}:{target}] "
                f"title={title or '-'} "
                f"raw={raw_url or '-'}"
            )

    def record_run_summary(self, summary):
        if not self.enabled:
            return

        source_failure_sources = ",".join(
            sorted(failure["source"] for failure in self.source_failures)
        ) or "-"
        review_modes = _format_count_map(summary.get("review_modes"))
        gemini_failure_stages = _format_count_map(
            summary.get("gemini_failure_stages")
        )
        support_refetch_statuses = _format_count_map(
            summary.get("support_backlog_refetch_statuses")
        )
        with self._lock:
            self.run_summaries.append(
                {
                    **summary,
                    "source_failures": list(self.source_failures),
                }
            )
            print(
                "[run_summary] "
                f"candidate_jobs={summary.get('candidate_jobs', 0)} "
                f"enriched_jobs={summary.get('enriched_jobs', 0)} "
                f"recipients={summary.get('recipient_count', 0)} "
                f"jobs_sent={summary.get('jobs_sent', 0)} "
                f"jobs_queued={summary.get('jobs_queued', 0)} "
                f"queued_delivered={summary.get('queued_jobs_delivered', 0)} "
                f"reviewed_jobs={summary.get('reviewed_jobs', 0)} "
                f"support_backlog_candidates={summary.get('support_backlog_candidates', 0)} "
                f"support_backlog_refetched={summary.get('support_backlog_refetched', 0)} "
                f"support_backlog_expired={summary.get('support_backlog_expired', 0)} "
                f"support_backlog_refetch_statuses={support_refetch_statuses} "
                f"source_failures={len(self.source_failures)} "
                f"failed_sources={source_failure_sources} "
                f"review_modes={review_modes} "
                f"gemini_failure_stages={gemini_failure_stages}"
            )
