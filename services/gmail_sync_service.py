"""
services/gmail_sync_service.py

Email ingestion logic for two scenarios:
  - initialize_and_first_sync: called by POST /api/v1/ingest to set up cursors
    and fetch the first batch of historical emails.
  - run_scheduled_sync: called by the 60-second scheduler to continue backfill
    and capture new emails via Gmail historyId API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from initializer import chunker, db, dispatcher, embedder, store
from loaders.gmail_loader import GmailLoader
from loaders.base_email_loader import EmailLoaderAuthRevokedError, EmailLoaderFetchError
from rag.pipeline import Pipeline

logger = logging.getLogger(__name__)

_pipeline = lambda: Pipeline(store=store, embedder=embedder, dispatcher=dispatcher, chunker=chunker)


def initialize_and_first_sync(
    user_id: int,
    google_creds: dict,
    label: str,
    status_dict: dict,
) -> None:
    """Called by POST /api/v1/ingest. Stores chosen label, initializes cursors,
    and fetches the first 60 historical emails immediately."""
    status_dict[user_id] = {"state": "fetching", "fetched": 0, "chunks_stored": 0}
    try:
        now = datetime.now(tz=timezone.utc)
        with GmailLoader(
            access_token=google_creds["access_token"],
            refresh_token=google_creds["refresh_token"],
            token_expiry=google_creds.get("token_expiry"),
            before_timestamp=now,
            max_emails=60,
            label=label,
        ) as loader:
            history_id = loader.get_current_history_id()
            emails = loader.fetch_emails()

        if loader.access_token != google_creds["access_token"]:
            with db.session_context() as session:
                db.update_google_access_token(session, user_id, loader.access_token, loader.token_expiry)

        status_dict[user_id]["fetched"] = len(emails)
        status_dict[user_id]["state"] = "processing"

        if emails:
            count = _pipeline().run(emails)
            status_dict[user_id]["chunks_stored"] = count
            new_cursor = min(e.date for e in emails)
        else:
            count = 0
            new_cursor = None

        with db.session_context() as session:
            db.update_google_sync_label(session, user_id, label)
            db.update_google_history_id(session, user_id, history_id)
            db.update_google_backfill_cursor(session, user_id, new_cursor)

        status_dict[user_id]["state"] = "done"
        logger.info("Initialized sync for user %d: %d emails, cursor=%s.", user_id, count, new_cursor)

    except EmailLoaderAuthRevokedError:
        with db.session_context() as session:
            db.delete_google_credentials(session, user_id)
        status_dict[user_id]["state"] = "error"
        status_dict[user_id]["error"] = "Google access revoked. Please reconnect your Google account."
        logger.warning("Google credentials revoked for user %d. Credentials deleted.", user_id)

    except Exception as exc:
        status_dict[user_id]["state"] = "error"
        status_dict[user_id]["error"] = str(exc)
        logger.exception("Ingest initialization failed for user %d: %s", user_id, exc)


def run_scheduled_sync(user_id: int, google_creds: dict) -> None:
    """Called by the scheduler every 60s. Skips silently if user hasn't clicked ingest yet."""
    with db.session_context() as session:
        creds = db.find_google_credentials(session, user_id)

    if creds is None or creds.history_id is None:
        return

    label = creds.sync_label

    # Pass 1: Backfill (historical emails going backwards)
    if creds.backfill_cursor is not None:
        logger.info("Starting backfill for user %d, cursor=%s.", user_id, creds.backfill_cursor)
        try:
            with GmailLoader(
                access_token=google_creds["access_token"],
                refresh_token=google_creds["refresh_token"],
                token_expiry=google_creds.get("token_expiry"),
                before_timestamp=creds.backfill_cursor,
                max_emails=60,
                label=label,
            ) as loader:
                emails = loader.fetch_emails()

            if loader.access_token != google_creds["access_token"]:
                with db.session_context() as session:
                    db.update_google_access_token(session, user_id, loader.access_token, loader.token_expiry)
                google_creds = {**google_creds, "access_token": loader.access_token, "token_expiry": loader.token_expiry}

            if emails:
                _pipeline().run(emails)
                new_cursor = min(e.date for e in emails)
                logger.info("Backfill: %d emails for user %d, cursor now %s.", len(emails), user_id, new_cursor)
            else:
                new_cursor = None
                logger.info("Backfill complete for user %d.", user_id)

            with db.session_context() as session:
                db.update_google_backfill_cursor(session, user_id, new_cursor)
        except EmailLoaderAuthRevokedError:
            with db.session_context() as session:
                db.delete_google_credentials(session, user_id)
            logger.warning("Google credentials revoked for user %d during backfill. Credentials deleted.", user_id)
            return
        except Exception as exc:
            logger.exception("Backfill failed for user %d: %s", user_id, exc)

    # Pass 2: Forward sync (new emails via historyId)
    logger.info("Starting forward sync for user %d, historyId=%s.", user_id, creds.history_id)
    try:
        with GmailLoader(
            access_token=google_creds["access_token"],
            refresh_token=google_creds["refresh_token"],
            token_expiry=google_creds.get("token_expiry"),
            label=label,
        ) as loader:
            try:
                new_emails, new_history_id = loader.fetch_new_by_history(creds.history_id)
            except EmailLoaderFetchError:
                new_history_id = loader.get_current_history_id()
                new_emails = []
                logger.warning("historyId expired for user %d, reset to %s.", user_id, new_history_id)

        if loader.access_token != google_creds["access_token"]:
            with db.session_context() as session:
                db.update_google_access_token(session, user_id, loader.access_token, loader.token_expiry)

        if new_emails:
            _pipeline().run(new_emails)
            logger.info("Forward sync: %d new emails for user %d.", len(new_emails), user_id)
        else:
            logger.info("Forward sync: no new emails for user %d.", user_id)

        with db.session_context() as session:
            db.update_google_history_id(session, user_id, new_history_id)

    except EmailLoaderAuthRevokedError:
        with db.session_context() as session:
            db.delete_google_credentials(session, user_id)
        logger.warning("Google credentials revoked for user %d during forward sync. Credentials deleted.", user_id)
    except Exception as exc:
        logger.exception("Forward sync failed for user %d: %s", user_id, exc)
