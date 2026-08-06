"""Timestamp UTC "naive" (sem tzinfo) -- é o formato que o SQLite/SQLAlchemy
usa nas colunas DateTime deste projeto. datetime.utcnow() faz a mesma coisa
mas está depreciado; esta função é o substituto direto."""
from datetime import datetime, timezone


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
