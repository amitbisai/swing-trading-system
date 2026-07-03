"""
Strategy settings API — runtime-adjustable knobs stored in app_settings.

Currently exposes max_entries_per_day (the top-N daily entry cap used by the
auto-entry engine). Set from the Analytics page.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.schemas import ApiResponse
from config import settings
from db.app_settings import get_int_setting, set_setting

router = APIRouter()


class StrategySettingsOut(BaseModel):
    max_entries_per_day: int   # 0 = unlimited


class StrategySettingsUpdate(BaseModel):
    max_entries_per_day: int = Field(ge=0, le=100)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/", response_model=ApiResponse[StrategySettingsOut])
async def get_strategy_settings() -> ApiResponse[StrategySettingsOut]:
    value = await get_int_setting("max_entries_per_day", settings.max_entries_per_day)
    return ApiResponse(
        data=StrategySettingsOut(max_entries_per_day=value),
        timestamp=_ts(),
    )


@router.put("/", response_model=ApiResponse[StrategySettingsOut])
async def update_strategy_settings(
    body: StrategySettingsUpdate,
) -> ApiResponse[StrategySettingsOut]:
    await set_setting("max_entries_per_day", str(body.max_entries_per_day))
    return ApiResponse(
        data=StrategySettingsOut(max_entries_per_day=body.max_entries_per_day),
        timestamp=_ts(),
    )
