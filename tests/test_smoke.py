from httpx import AsyncClient, ASGITransport

from recruit_assist.main import app


async def test_root_endpoint_loads(anyio_backend):
    """Tests if the root endpoint ('/') returns a 200 OK status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
