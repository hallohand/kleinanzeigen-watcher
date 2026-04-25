from kleinanzeigen_watcher.url_builder import build_search_url


BASE = "https://www.kleinanzeigen.de"


def test_query_only() -> None:
    assert build_search_url(query="office monitor") == f"{BASE}/s-office-monitor/k0?sortingField=SORTING_DATE"


def test_query_lowercased_and_slugged() -> None:
    assert build_search_url(query="Office Monitor") == f"{BASE}/s-office-monitor/k0?sortingField=SORTING_DATE"


def test_umlauts_resolved_in_slug() -> None:
    assert build_search_url(query="Bücher für Kinder") == f"{BASE}/s-buecher-fuer-kinder/k0?sortingField=SORTING_DATE"


def test_query_with_plz_and_radius() -> None:
    assert (
        build_search_url(query="office monitor", plz="01067", radius_km=20)
        == f"{BASE}/s-01067/office-monitor/k0l1r20?sortingField=SORTING_DATE"
    )


def test_plz_without_radius_uses_l1_only() -> None:
    assert (
        build_search_url(query="office monitor", plz="01067")
        == f"{BASE}/s-01067/office-monitor/k0l1?sortingField=SORTING_DATE"
    )


def test_price_range() -> None:
    assert (
        build_search_url(query="office monitor", price_min=50, price_max=200)
        == f"{BASE}/s-preis:50:200/office-monitor/k0?sortingField=SORTING_DATE"
    )


def test_price_min_only_leaves_max_open() -> None:
    assert (
        build_search_url(query="office monitor", price_min=50)
        == f"{BASE}/s-preis:50:/office-monitor/k0?sortingField=SORTING_DATE"
    )


def test_price_max_only_leaves_min_open() -> None:
    assert (
        build_search_url(query="office monitor", price_max=200)
        == f"{BASE}/s-preis::200/office-monitor/k0?sortingField=SORTING_DATE"
    )


def test_shipping_yes_added_as_path_token() -> None:
    assert (
        build_search_url(query="office monitor", shipping="ja")
        == f"{BASE}/s-office-monitor/versand:ja/k0?sortingField=SORTING_DATE"
    )


def test_shipping_any_omits_token() -> None:
    assert (
        build_search_url(query="office monitor", shipping="any")
        == f"{BASE}/s-office-monitor/k0?sortingField=SORTING_DATE"
    )


def test_category_id_replaces_k0() -> None:
    assert (
        build_search_url(query="office monitor", category_id=225)
        == f"{BASE}/s-office-monitor/c225?sortingField=SORTING_DATE"
    )


def test_condition_appended_to_category() -> None:
    assert (
        build_search_url(query="office monitor", category_id=225, condition="new")
        == f"{BASE}/s-office-monitor/c225+global.zustand:new?sortingField=SORTING_DATE"
    )


def test_condition_appended_to_k0() -> None:
    assert (
        build_search_url(query="office monitor", condition="like_new")
        == f"{BASE}/s-office-monitor/k0+global.zustand:like_new?sortingField=SORTING_DATE"
    )


def test_pagination_inserted_as_seite_token() -> None:
    assert (
        build_search_url(query="office monitor", page=2)
        == f"{BASE}/s-seite:2/office-monitor/k0?sortingField=SORTING_DATE"
    )


def test_combined_filters() -> None:
    assert (
        build_search_url(
            query="office monitor",
            plz="01067",
            radius_km=20,
            price_min=50,
            price_max=200,
            shipping="ja",
            page=2,
        )
        == f"{BASE}/s-seite:2/01067/preis:50:200/office-monitor/versand:ja/k0l1r20?sortingField=SORTING_DATE"
    )


def test_sort_disabled_omits_query() -> None:
    assert build_search_url(query="office monitor", sort_by_date=False) == f"{BASE}/s-office-monitor/k0"


def test_radius_without_plz_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="radius"):
        build_search_url(query="x", radius_km=20)


def test_query_or_category_required() -> None:
    import pytest

    with pytest.raises(ValueError, match="query"):
        build_search_url()
