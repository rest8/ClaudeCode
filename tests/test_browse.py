"""Test restaurant browsing and search against mock server."""

import pytest


@pytest.mark.asyncio
async def test_discover_browse_urls(client, base_url):
    """Verify area and genre URLs are discovered from the top page."""
    result = await client.discover_browse_urls()

    assert len(result["areas"]) >= 3
    assert len(result["genres"]) >= 3

    area_names = [a["name"] for a in result["areas"]]
    assert "東京" in area_names
    assert "大阪" in area_names

    genre_names = [g["name"] for g in result["genres"]]
    assert "鮨" in genre_names
    assert "天ぷら" in genre_names


@pytest.mark.asyncio
async def test_browse_restaurants_by_area(client, base_url):
    """Verify browsing restaurants by area returns correct results."""
    restaurants = await client.browse_restaurants(f"{base_url}/ja/area/tokyo")

    assert len(restaurants) == 3
    names = [r.name for r in restaurants]
    assert "鮨 テスト太郎" in names
    assert "天ぷら テスト" in names


@pytest.mark.asyncio
async def test_browse_restaurants_by_genre(client, base_url):
    """Verify browsing restaurants by genre returns correct results."""
    restaurants = await client.browse_restaurants(f"{base_url}/ja/genre/sushi")

    assert len(restaurants) == 2
    names = [r.name for r in restaurants]
    assert "鮨 テスト太郎" in names
    assert "鮨 大阪テスト" in names


@pytest.mark.asyncio
async def test_browse_empty_area(client, base_url):
    """Verify browsing an area with no restaurants returns empty list."""
    restaurants = await client.browse_restaurants(f"{base_url}/ja/area/unknown")
    assert len(restaurants) == 0


@pytest.mark.asyncio
async def test_search_restaurants(client, base_url):
    """Verify keyword search returns matching restaurants."""
    results = await client.search_restaurants("鮨")
    assert len(results) >= 2

    results = await client.search_restaurants("天ぷら")
    assert len(results) >= 1
    assert any("天ぷら" in r.name for r in results)


@pytest.mark.asyncio
async def test_search_no_results(client, base_url):
    """Verify search with no matches returns empty list."""
    results = await client.search_restaurants("存在しない料理")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_restaurant_info_fields(client, base_url):
    """Verify restaurant info has correct metadata."""
    restaurants = await client.browse_restaurants(f"{base_url}/ja/area/tokyo")

    sushi = next(r for r in restaurants if "テスト太郎" in r.name)
    assert sushi.url.endswith("/r/rest001")
