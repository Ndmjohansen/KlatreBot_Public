"""Pydantic row models. Match table column types and names."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class User(BaseModel):
    discord_user_id: int
    display_name: str
    is_admin: bool = False


class Message(BaseModel):
    discord_message_id: int
    channel_id: int
    user_id: int
    content: str
    timestamp_utc: datetime
    is_bot: bool = False


class AttendanceSession(BaseModel):
    id: int | None = None
    date_local: str          # 'YYYY-MM-DD'
    channel_id: int
    message_id: int
    klatring_start_utc: datetime


class AttendanceEvent(BaseModel):
    id: int | None = None
    session_id: int
    user_id: int
    status: Literal["yes", "no"]
    timestamp_utc: datetime
