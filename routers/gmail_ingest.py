"""
routers/gmail_ingest.py

Endpoints to trigger Gmail ingestion into the RAG pipeline.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from initializer import db
from services.app_auth_service import get_current_user
from services.gmail_sync_service import initialize_and_first_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingest"])

# In-memory ingestion progress tracker keyed by user_id
_ingest_status: dict[int, dict] = {}


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger email ingestion",
    description="Initializes sync cursors and fetches the first batch of emails in the background. The scheduler continues automatically after this.",
)
def ingest(
    background_tasks: BackgroundTasks,
    label: str = Query(default="INBOX", description="Gmail label/folder to sync"),
    user=Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    """Initialize email sync for a user and fetch the first batch in the background."""
    google_creds = db.find_google_credentials(session, user.id)
    if not google_creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account not linked. Connect Google first.",
        )

    background_tasks.add_task(
        initialize_and_first_sync,
        user.id,
        {"access_token": google_creds.access_token, "refresh_token": google_creds.refresh_token, "token_expiry": google_creds.token_expiry},
        label,
        _ingest_status,
    )
    return {"status": "Ingestion started", "label": label}


@router.get(
    "/ingest/status",
    summary="Check ingestion progress",
    description="Returns the current ingestion status for the logged-in user.",
)
def ingest_status(
    user=Depends(get_current_user),
):
    """Return the current ingestion progress for the logged-in user."""
    status = _ingest_status.get(user.id)
    if not status:
        return {"state": "idle"}
    return status


