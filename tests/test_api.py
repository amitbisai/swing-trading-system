import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["error"] is None
    assert body["timestamp"] is not None


@pytest.mark.asyncio
async def test_suggestions_envelope(client):
    response = await client.get("/api/suggestions/")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "error" in body
    assert "timestamp" in body


@pytest.mark.asyncio
async def test_portfolio_positions_envelope(client):
    response = await client.get("/api/portfolio/positions")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_stocks_envelope(client):
    response = await client.get("/api/stocks/")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
