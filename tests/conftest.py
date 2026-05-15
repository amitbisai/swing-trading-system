import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient


class _MockResult:
    """Mimics SQLAlchemy AsyncResult for envelope-only tests."""
    def scalars(self) -> MagicMock:
        m = MagicMock()
        m.all.return_value = []
        return m

    def scalar_one_or_none(self) -> None:
        return None


async def _mock_get_db():
    session = AsyncMock()
    session.execute.return_value = _MockResult()
    yield session


@pytest.fixture(scope="session")
async def client():
    from main import app
    from api.dependencies import get_db

    app.dependency_overrides[get_db] = _mock_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
