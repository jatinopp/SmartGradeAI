import pytest
from core.weather import fetch_open_meteo


def test_weather_rejects_invalid_coordinates_without_network():
    with pytest.raises(ValueError):
        fetch_open_meteo(100, 0)
    with pytest.raises(ValueError):
        fetch_open_meteo(0, 200)
