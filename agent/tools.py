"""Tools que el agente Rai puede invocar.

Ejemplo pedagógico de cómo se define una tool en OpenAI Agents SDK:
- decorador `@function_tool`
- función async con type hints
- parámetro tipado `Literal[...]` para que el modelo vea las opciones válidas
- el docstring se convierte automáticamente en la descripción visible al modelo
"""
from __future__ import annotations

from typing import Literal

import httpx
from agents import function_tool

City = Literal[
    "Buenos Aires",
    "Córdoba",
    "Rosario",
    "Mendoza",
    "São Paulo",
    "Santiago de Chile",
    "Madrid",
    "Nueva York",
    "Londres",
    "Tokio",
]

CITY_COORDS: dict[str, tuple[float, float]] = {
    "Buenos Aires": (-34.6037, -58.3816),
    "Córdoba": (-31.4201, -64.1888),
    "Rosario": (-32.9442, -60.6505),
    "Mendoza": (-32.8895, -68.8458),
    "São Paulo": (-23.5505, -46.6333),
    "Santiago de Chile": (-33.4489, -70.6693),
    "Madrid": (40.4168, -3.7038),
    "Nueva York": (40.7128, -74.0060),
    "Londres": (51.5074, -0.1278),
    "Tokio": (35.6762, 139.6503),
}

# Open-Meteo WMO weather codes → descripción corta en castellano.
# Lista completa: https://open-meteo.com/en/docs (sección "Weather variable documentation").
WEATHER_CODES: dict[int, str] = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina con escarcha",
    51: "llovizna ligera",
    53: "llovizna moderada",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia moderada",
    65: "lluvia intensa",
    71: "nieve ligera",
    73: "nieve moderada",
    75: "nieve intensa",
    80: "chubascos ligeros",
    81: "chubascos moderados",
    82: "chubascos intensos",
    95: "tormenta",
    96: "tormenta con granizo ligero",
    99: "tormenta con granizo intenso",
}


@function_tool
async def get_weather(city: City) -> str:
    """Devuelve el clima actual de una de las 10 ciudades soportadas.

    Usalo cuando el usuario pregunte por temperatura, clima, tiempo o pronóstico
    para alguna de estas ciudades: Buenos Aires, Córdoba, Rosario, Mendoza,
    São Paulo, Santiago de Chile, Madrid, Nueva York, Londres o Tokio.

    Args:
        city: Nombre de la ciudad. Tiene que ser exactamente uno de los valores
            soportados (case-sensitive, con tildes).

    Returns:
        Un string en castellano con temperatura, sensación térmica, humedad,
        viento y condición meteorológica actual.
    """
    lat, lon = CITY_COORDS[city]
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return f"No pude consultar el clima de {city}: error de red ({exc})."
    except ValueError as exc:
        return f"No pude consultar el clima de {city}: respuesta inválida ({exc})."

    try:
        current = data["current"]
        temp = current["temperature_2m"]
        feels = current["apparent_temperature"]
        humidity = current["relative_humidity_2m"]
        wind = current["wind_speed_10m"]
        code = current["weather_code"]
    except KeyError as exc:
        return f"No pude leer el clima de {city}: falta campo {exc} en la respuesta."

    condition = WEATHER_CODES.get(code, f"código {code}")
    return (
        f"{city}: {temp}°C (sensación {feels}°C), {condition}, "
        f"humedad {humidity}%, viento {wind} km/h."
    )
