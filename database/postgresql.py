"""
PostgreSQL data-access layer using SQLAlchemy ORM.

Responsibilities:
  - Initial setup: create the application database and all ORM tables.
  - CRUD: insert, query, and update user rows (OAuth credentials, profile).

All methods use SQLAlchemy sessions managed via ``sessionmaker``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from .base_database import BaseDatabase
from .models import Base, CleanedMessageRow, DiscordCredentialRow, GoogleCredentialRow, SlackCredentialRow, TelegramCredentialRow, User

logger = logging.getLogger(__name__)


class Database(BaseDatabase):
    """PostgreSQL implementation of the database access layer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = create_engine(
            settings.database_url,
            pool_size=settings.POSTGRES_POOL_SIZE,
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self._engine)

    def _session(self) -> Session:
        return self._session_factory()

    def create_database(self) -> None:
        """Create the application database if it does not exist."""
        conn = psycopg2.connect(
            host=self._settings.POSTGRES_HOST,
            port=self._settings.POSTGRES_PORT,
            dbname="postgres",
            user=self._settings.POSTGRES_USER,
            password=self._settings.POSTGRES_PASSWORD.get_secret_value(),
        )
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname=%s",
                    (self._settings.POSTGRES_DB,),
                )
                if not cur.fetchone():
                    cur.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(self._settings.POSTGRES_DB)
                        )
                    )
                    logger.info("Database %s created", self._settings.POSTGRES_DB)
                else:
                    logger.info("Database %s already exists", self._settings.POSTGRES_DB)
        finally:
            conn.close()

    def create_tables(self) -> None:
        """Create all ORM-defined tables if they do not already exist."""
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def find_user_by_id(self, user_id: int) -> Optional[User]:
        with self._session() as session:
            user = session.get(User, user_id)
            if user:
                session.expunge(user)
            return user

    def user_exists(self, email: str) -> bool:
        with self._session() as session:
            stmt = select(User.id).where(User.email == email)
            return session.execute(stmt).first() is not None

    def find_user_by_email(self, email: str) -> Optional[User]:
        with self._session() as session:
            stmt = select(User).where(User.email == email)
            user = session.scalars(stmt).first()
            if user:
                session.expunge(user)
            return user

    def create_user(self, *, name: str, email: str, password_hash: str) -> User:
        with self._session() as session:
            user = User(name=name, email=email, password_hash=password_hash)
            session.add(user)
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user

    def update_user_profile(self, user_id: int, *, name: str) -> User:
        with self._session() as session:
            user = session.get(User, user_id)
            user.name = name
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user

    # ------------------------------------------------------------------
    # Google Credentials
    # ------------------------------------------------------------------

    def find_google_credentials(self, user_id: int) -> Optional[GoogleCredentialRow]:
        with self._session() as session:
            stmt = select(GoogleCredentialRow).where(GoogleCredentialRow.user_id == user_id)
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def find_user_by_google_id(self, google_id: str) -> Optional[GoogleCredentialRow]:
        with self._session() as session:
            stmt = select(GoogleCredentialRow).where(GoogleCredentialRow.google_id == google_id)
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def save_google_credentials(
        self,
        user_id: int,
        *,
        google_id: str,
        access_token: str,
        refresh_token: Optional[str],
        token_expiry: Optional[datetime],
    ) -> GoogleCredentialRow:
        with self._session() as session:
            # Check if this Google account is already linked to a different user
            stmt = select(GoogleCredentialRow).where(
                GoogleCredentialRow.google_id == google_id,
                GoogleCredentialRow.user_id != user_id,
            )
            if session.scalars(stmt).first():
                raise ValueError("This Google account is already linked to another user.")

            # Upsert: find existing row for user or create new
            stmt = select(GoogleCredentialRow).where(GoogleCredentialRow.user_id == user_id)
            cred = session.scalars(stmt).first()

            if cred:
                cred.google_id = google_id
                cred.access_token = access_token
                if refresh_token is not None:
                    cred.refresh_token = refresh_token
                cred.token_expiry = token_expiry
            else:
                cred = GoogleCredentialRow(
                    user_id=user_id,
                    google_id=google_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expiry=token_expiry,
                )
                session.add(cred)

            session.commit()
            session.refresh(cred)
            session.expunge(cred)
            return cred

    # ------------------------------------------------------------------
    # Slack Credentials
    # ------------------------------------------------------------------

    def find_slack_credentials(self, team_id: str) -> Optional[SlackCredentialRow]:
        with self._session() as session:
            stmt = select(SlackCredentialRow).where(SlackCredentialRow.team_id == team_id)
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def save_slack_credentials(
        self,
        user_id: int,
        team_id: str,
        *,
        access_token: str,
        refresh_token: Optional[str] = None,
        team_name: Optional[str] = None,
        bot_user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SlackCredentialRow:
        with self._session() as session:
            stmt = select(SlackCredentialRow).where(SlackCredentialRow.team_id == team_id)
            cred = session.scalars(stmt).first()

            meta_str = json.dumps(metadata) if metadata else None

            if cred:
                cred.user_id = user_id
                cred.access_token = access_token
                if refresh_token is not None:
                    cred.refresh_token = refresh_token
                if team_name is not None:
                    cred.team_name = team_name
                if bot_user_id is not None:
                    cred.bot_user_id = bot_user_id
                if meta_str is not None:
                    cred.metadata_json = meta_str
            else:
                cred = SlackCredentialRow(
                    user_id=user_id,
                    team_id=team_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    team_name=team_name,
                    bot_user_id=bot_user_id,
                    metadata_json=meta_str,
                )
                session.add(cred)

            session.commit()
            session.refresh(cred)
            session.expunge(cred)
            return cred

    def delete_slack_credentials(self, team_id: str) -> bool:
        with self._session() as session:
            stmt = select(SlackCredentialRow).where(SlackCredentialRow.team_id == team_id)
            cred = session.scalars(stmt).first()
            if cred:
                session.delete(cred)
                session.commit()
                return True
            return False

    # ------------------------------------------------------------------
    # Discord Credentials
    # ------------------------------------------------------------------

    def find_discord_credentials(
        self, discord_user_id: str, guild_id: str
    ) -> Optional[DiscordCredentialRow]:
        with self._session() as session:
            stmt = select(DiscordCredentialRow).where(
                DiscordCredentialRow.discord_user_id == discord_user_id,
                DiscordCredentialRow.guild_id == guild_id,
            )
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def find_discord_credentials_by_guild(self, guild_id: str) -> Optional[DiscordCredentialRow]:
        with self._session() as session:
            stmt = select(DiscordCredentialRow).where(
                DiscordCredentialRow.guild_id == guild_id
            )
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def save_discord_credentials(
        self,
        *,
        user_id: int,
        discord_user_id: str,
        guild_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        token_type: str = "Bearer",
        scopes: str = "identify bot",
        expires_at: Optional[datetime] = None,
        granted_permissions: Optional[str] = None,
    ) -> DiscordCredentialRow:
        with self._session() as session:
            stmt = select(DiscordCredentialRow).where(
                DiscordCredentialRow.discord_user_id == discord_user_id,
                DiscordCredentialRow.guild_id == guild_id,
            )
            cred = session.scalars(stmt).first()

            if cred:
                cred.user_id = user_id
                cred.access_token = access_token
                if refresh_token is not None:
                    cred.refresh_token = refresh_token
                cred.token_type = token_type
                cred.scopes = scopes
                if expires_at is not None:
                    cred.expires_at = expires_at
                cred.granted_permissions = granted_permissions
            else:
                cred = DiscordCredentialRow(
                    user_id=user_id,
                    discord_user_id=discord_user_id,
                    guild_id=guild_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type=token_type,
                    scopes=scopes,
                    expires_at=expires_at,
                    granted_permissions=granted_permissions,
                )
                session.add(cred)

            session.commit()
            session.refresh(cred)
            session.expunge(cred)
            return cred

    def delete_discord_credentials(self, discord_user_id: str, guild_id: str) -> bool:
        with self._session() as session:
            stmt = select(DiscordCredentialRow).where(
                DiscordCredentialRow.discord_user_id == discord_user_id,
                DiscordCredentialRow.guild_id == guild_id,
            )
            cred = session.scalars(stmt).first()
            if cred:
                session.delete(cred)
                session.commit()
                return True
            return False

    def list_discord_guild_ids(self) -> List[str]:
        with self._session() as session:
            return list(session.scalars(select(DiscordCredentialRow.guild_id).distinct()))

    def discord_guild_connection_exists(self, guild_id: str) -> bool:
        with self._session() as session:
            stmt = select(DiscordCredentialRow.id).where(
                DiscordCredentialRow.guild_id == guild_id
            ).limit(1)
            return session.execute(stmt).first() is not None

    def discord_guild_owned_by_user(self, user_id: int, guild_id: str) -> bool:
        with self._session() as session:
            stmt = select(DiscordCredentialRow.id).where(
                DiscordCredentialRow.user_id == user_id,
                DiscordCredentialRow.guild_id == guild_id,
            ).limit(1)
            return session.execute(stmt).first() is not None

    def list_user_discord_guild_ids(self, user_id: int) -> List[str]:
        with self._session() as session:
            stmt = select(DiscordCredentialRow.guild_id).where(
                DiscordCredentialRow.user_id == user_id
            ).distinct()
            return list(session.scalars(stmt))

    # ------------------------------------------------------------------
    # Telegram Credentials
    # ------------------------------------------------------------------

    def find_telegram_credentials(self, phone_number: str) -> Optional[TelegramCredentialRow]:
        with self._session() as session:
            stmt = select(TelegramCredentialRow).where(
                TelegramCredentialRow.phone_number == phone_number
            )
            cred = session.scalars(stmt).first()
            if cred:
                session.expunge(cred)
            return cred

    def save_telegram_credentials(
        self,
        user_id: int,
        phone_number: str,
        *,
        telegram_user_id: Optional[int] = None,
        session_string: str,
    ) -> TelegramCredentialRow:
        with self._session() as session:
            stmt = select(TelegramCredentialRow).where(
                TelegramCredentialRow.phone_number == phone_number
            )
            cred = session.scalars(stmt).first()

            if cred:
                cred.user_id = user_id
                cred.session_string = session_string
                if telegram_user_id is not None:
                    cred.telegram_user_id = telegram_user_id
            else:
                cred = TelegramCredentialRow(
                    user_id=user_id,
                    phone_number=phone_number,
                    telegram_user_id=telegram_user_id,
                    session_string=session_string,
                )
                session.add(cred)

            session.commit()
            session.refresh(cred)
            session.expunge(cred)
            return cred

    def delete_telegram_credentials(self, phone_number: str) -> bool:
        with self._session() as session:
            stmt = select(TelegramCredentialRow).where(
                TelegramCredentialRow.phone_number == phone_number
            )
            cred = session.scalars(stmt).first()
            if cred:
                session.delete(cred)
                session.commit()
                return True
            return False

    # ------------------------------------------------------------------
    # Cleaned Messages
    # ------------------------------------------------------------------

    def save_cleaned_messages(
        self,
        messages: List[Dict[str, Any]],
        provider: str = "slack",
    ) -> int:
        saved_count = 0
        with self._session() as session:
            for msg in messages:
                meta = msg.get("metadata") or {}
                record = CleanedMessageRow(
                    provider=provider,
                    channel_id=msg.get("channel_id") or meta.get("channel"),
                    message_id=msg.get("message_id") or meta.get("ts"),
                    user_id=msg.get("user_id") or meta.get("user"),
                    raw_text=msg.get("raw_text", ""),
                    cleaned_text=msg.get("cleaned_text", ""),
                    is_boilerplate=msg.get("is_boilerplate", False),
                    is_duplicate_of=msg.get("is_duplicate_of"),
                    dedup_hash=msg.get("dedup_hash"),
                    metadata_json=json.dumps(meta) if meta else None,
                )
                session.add(record)
                saved_count += 1
            session.commit()
        return saved_count

    def get_stored_messages(
        self,
        channel_id: Optional[str] = None,
        provider: str = "slack",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        with self._session() as session:
            stmt = select(CleanedMessageRow).where(CleanedMessageRow.provider == provider)
            if channel_id:
                stmt = stmt.where(CleanedMessageRow.channel_id == channel_id)
            stmt = stmt.order_by(CleanedMessageRow.id.desc()).limit(limit)
            records = session.scalars(stmt).all()
            results = []
            for r in records:
                meta = {}
                if r.metadata_json:
                    try:
                        meta = json.loads(r.metadata_json)
                    except Exception:
                        pass
                results.append({
                    "id": r.id,
                    "provider": r.provider,
                    "channel_id": r.channel_id,
                    "message_id": r.message_id,
                    "user_id": r.user_id,
                    "raw_text": r.raw_text,
                    "cleaned_text": r.cleaned_text,
                    "is_boilerplate": r.is_boilerplate,
                    "is_duplicate_of": r.is_duplicate_of,
                    "dedup_hash": r.dedup_hash,
                    "metadata": meta,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })
            return results
