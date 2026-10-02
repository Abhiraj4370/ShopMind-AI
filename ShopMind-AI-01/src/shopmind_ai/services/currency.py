"""Worldwide region and currency utilities for ShopMind AI."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request as URLRequest
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Country -> Currency
#
# ISO 3166-1 alpha-2 country codes.
# Default currency is based on the user's country/region.
# ---------------------------------------------------------------------------

COUNTRY_CURRENCY: dict[str, str] = {
    "AF": "AFN",
    "AL": "ALL",
    "DZ": "DZD",
    "AS": "USD",
    "AD": "EUR",
    "AO": "AOA",
    "AI": "XCD",
    "AG": "XCD",
    "AR": "ARS",
    "AM": "AMD",
    "AW": "AWG",
    "AU": "AUD",
    "AT": "EUR",
    "AZ": "AZN",
    "BS": "BSD",
    "BH": "BHD",
    "BD": "BDT",
    "BB": "BBD",
    "BY": "BYN",
    "BE": "EUR",
    "BZ": "BZD",
    "BJ": "XOF",
    "BM": "BMD",
    "BT": "BTN",
    "BO": "BOB",
    "BA": "BAM",
    "BW": "BWP",
    "BR": "BRL",
    "BN": "BND",
    "BG": "BGN",
    "BF": "XOF",
    "BI": "BIF",
    "CV": "CVE",
    "KH": "KHR",
    "CM": "XAF",
    "CA": "CAD",
    "KY": "KYD",
    "CF": "XAF",
    "TD": "XAF",
    "CL": "CLP",
    "CN": "CNY",
    "CO": "COP",
    "KM": "KMF",
    "CG": "XAF",
    "CD": "CDF",
    "CR": "CRC",
    "CI": "XOF",
    "HR": "EUR",
    "CU": "CUP",
    "CY": "EUR",
    "CZ": "CZK",
    "DK": "DKK",
    "DJ": "DJF",
    "DM": "XCD",
    "DO": "DOP",
    "EC": "USD",
    "EG": "EGP",
    "SV": "USD",
    "GQ": "XAF",
    "ER": "ERN",
    "EE": "EUR",
    "SZ": "SZL",
    "ET": "ETB",
    "FJ": "FJD",
    "FI": "EUR",
    "FR": "EUR",
    "GA": "XAF",
    "GM": "GMD",
    "GE": "GEL",
    "DE": "EUR",
    "GH": "GHS",
    "GR": "EUR",
    "GD": "XCD",
    "GT": "GTQ",
    "GN": "GNF",
    "GW": "XOF",
    "GY": "GYD",
    "HT": "HTG",
    "HN": "HNL",
    "HK": "HKD",
    "HU": "HUF",
    "IS": "ISK",
    "IN": "INR",
    "ID": "IDR",
    "IR": "IRR",
    "IQ": "IQD",
    "IE": "EUR",
    "IL": "ILS",
    "IT": "EUR",
    "JM": "JMD",
    "JP": "JPY",
    "JO": "JOD",
    "KZ": "KZT",
    "KE": "KES",
    "KI": "AUD",
    "KP": "KPW",
    "KR": "KRW",
    "KW": "KWD",
    "KG": "KGS",
    "LA": "LAK",
    "LV": "EUR",
    "LB": "LBP",
    "LS": "LSL",
    "LR": "LRD",
    "LY": "LYD",
    "LI": "CHF",
    "LT": "EUR",
    "LU": "EUR",
    "MO": "MOP",
    "MG": "MGA",
    "MW": "MWK",
    "MY": "MYR",
    "MV": "MVR",
    "ML": "XOF",
    "MT": "EUR",
    "MH": "USD",
    "MR": "MRU",
    "MU": "MUR",
    "MX": "MXN",
    "FM": "USD",
    "MD": "MDL",
    "MC": "EUR",
    "MN": "MNT",
    "ME": "EUR",
    "MA": "MAD",
    "MZ": "MZN",
    "MM": "MMK",
    "NA": "NAD",
    "NR": "AUD",
    "NP": "NPR",
    "NL": "EUR",
    "NZ": "NZD",
    "NI": "NIO",
    "NE": "XOF",
    "NG": "NGN",
    "MK": "MKD",
    "NO": "NOK",
    "OM": "OMR",
    "PK": "PKR",
    "PW": "USD",
    "PA": "PAB",
    "PG": "PGK",
    "PY": "PYG",
    "PE": "PEN",
    "PH": "PHP",
    "PL": "PLN",
    "PT": "EUR",
    "QA": "QAR",
    "RO": "RON",
    "RU": "RUB",
    "RW": "RWF",
    "KN": "XCD",
    "LC": "XCD",
    "VC": "XCD",
    "WS": "WST",
    "SM": "EUR",
    "ST": "STN",
    "SA": "SAR",
    "SN": "XOF",
    "RS": "RSD",
    "SC": "SCR",
    "SL": "SLE",
    "SG": "SGD",
    "SK": "EUR",
    "SI": "EUR",
    "SB": "SBD",
    "SO": "SOS",
    "ZA": "ZAR",
    "SS": "SSP",
    "ES": "EUR",
    "LK": "LKR",
    "SD": "SDG",
    "SR": "SRD",
    "SE": "SEK",
    "CH": "CHF",
    "SY": "SYP",
    "TW": "TWD",
    "TJ": "TJS",
    "TZ": "TZS",
    "TH": "THB",
    "TL": "USD",
    "TG": "XOF",
    "TO": "TOP",
    "TT": "TTD",
    "TN": "TND",
    "TR": "TRY",
    "TM": "TMT",
    "TV": "AUD",
    "UG": "UGX",
    "UA": "UAH",
    "AE": "AED",
    "GB": "GBP",
    "US": "USD",
    "UY": "UYU",
    "UZ": "UZS",
    "VU": "VUV",
    "VA": "EUR",
    "VE": "VES",
    "VN": "VND",
    "YE": "YER",
    "ZM": "ZMW",
    "ZW": "ZWG",
}


# ---------------------------------------------------------------------------
# Currency symbols
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "NPR": "रू",
    "RUB": "₽",
    "JPY": "¥",
    "CNY": "¥",
    "KRW": "₩",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "SGD": "S$",
    "HKD": "HK$",
    "AED": "د.إ",
    "SAR": "﷼",
    "QAR": "﷼",
    "KWD": "د.ك",
    "BHD": ".د.ب",
    "OMR": "﷼",
    "PKR": "₨",
    "BDT": "৳",
    "LKR": "Rs",
    "BRL": "R$",
    "MXN": "MX$",
    "ZAR": "R",
    "TRY": "₺",
    "THB": "฿",
    "VND": "₫",
    "IDR": "Rp",
    "MYR": "RM",
    "PHP": "₱",
    "PLN": "zł",
    "CZK": "Kč",
    "HUF": "Ft",
    "RON": "lei",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "ISK": "kr",
    "CHF": "CHF",
}


# ---------------------------------------------------------------------------
# Currency metadata
# ---------------------------------------------------------------------------

CURRENCY_NAMES: dict[str, str] = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "INR": "Indian Rupee",
    "NPR": "Nepalese Rupee",
    "RUB": "Russian Ruble",
    "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan",
    "KRW": "South Korean Won",
    "AUD": "Australian Dollar",
    "CAD": "Canadian Dollar",
    "NZD": "New Zealand Dollar",
    "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar",
    "AED": "UAE Dirham",
    "SAR": "Saudi Riyal",
    "QAR": "Qatari Riyal",
    "KWD": "Kuwaiti Dinar",
    "BHD": "Bahraini Dinar",
    "OMR": "Omani Rial",
    "PKR": "Pakistani Rupee",
    "BDT": "Bangladeshi Taka",
    "LKR": "Sri Lankan Rupee",
    "BRL": "Brazilian Real",
    "MXN": "Mexican Peso",
    "ZAR": "South African Rand",
    "TRY": "Turkish Lira",
    "THB": "Thai Baht",
    "VND": "Vietnamese Dong",
    "IDR": "Indonesian Rupiah",
    "MYR": "Malaysian Ringgit",
    "PHP": "Philippine Peso",
    "PLN": "Polish Zloty",
    "CZK": "Czech Koruna",
    "HUF": "Hungarian Forint",
    "RON": "Romanian Leu",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "DKK": "Danish Krone",
    "ISK": "Icelandic Krona",
    "CHF": "Swiss Franc",
}


def normalize_country_code(
    country_code: str | None,
) -> str | None:
    """Normalize an ISO country code."""

    if not country_code:
        return None

    value = country_code.strip().upper()

    if len(value) != 2:
        return None

    return value if value in COUNTRY_CURRENCY else None


def currency_for_country(
    country_code: str | None,
) -> str:
    """Return the default currency for a country.

    Falls back to USD when the country cannot be determined.
    """

    country = normalize_country_code(
        country_code
    )

    if not country:
        return "USD"

    return COUNTRY_CURRENCY.get(
        country,
        "USD",
    )


def currency_symbol(
    currency: str,
) -> str:
    """Return a display symbol."""

    return CURRENCY_SYMBOLS.get(
        currency.upper(),
        currency.upper(),
    )


def detect_currency_from_text(text: str | None) -> str | None:
    """Detect an explicit currency marker in a shopping query."""
    import re

    if not text:
        return None

    normalized = text.lower()
    patterns = [
        (r"₹|\binr\b|\brupees?\b|\brs\.?\b", "INR"),
        (r"\bnpr\b|\bnepal(?:ese)? rupees?\b|रू", "NPR"),
        (r"₽|\brub\b|\brubles?\b|\brussian rubles?\b", "RUB"),
        (r"\$|\busd\b|\bus dollars?\b", "USD"),
        (r"£|\bgbp\b|\bpounds?\b", "GBP"),
        (r"€|\beur\b|\beuros?\b", "EUR"),
        (r"¥|\bjpy\b|\byen\b", "JPY"),
        (r"\bcad\b|\bcanadian dollars?\b", "CAD"),
        (r"\baud\b|\baustralian dollars?\b", "AUD"),
        (r"\baed\b|د\.إ", "AED"),
    ]

    for pattern, currency in patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return currency

    return None


def currency_name(
    currency: str,
) -> str:
    """Return a human-readable currency name."""

    return CURRENCY_NAMES.get(
        currency.upper(),
        currency.upper(),
    )


def detect_country_from_accept_language(
    accept_language: str | None,
) -> str | None:
    """Try to extract country from an Accept-Language header.

    Examples:
        en-IN -> IN
        en-US -> US
        de-DE -> DE
        ne-NP -> NP
    """

    if not accept_language:
        return None

    # Prefer language-region combinations.
    for part in accept_language.split(","):
        token = part.split(";")[0].strip()

        if "-" in token:
            country = token.rsplit("-", 1)[-1].upper()

            if len(country) == 2:
                normalized = normalize_country_code(
                    country
                )

                if normalized:
                    return normalized

        if "_" in token:
            country = token.rsplit("_", 1)[-1].upper()

            if len(country) == 2:
                normalized = normalize_country_code(
                    country
                )

                if normalized:
                    return normalized

    return None


async def detect_country_from_ip(
    ip_address: str | None,
) -> str | None:
    """Best-effort IP geolocation.

    Private/local addresses are ignored.

    Uses ipwho.is when available. Failure simply returns None.
    """

    if not ip_address:
        return None

    private_prefixes = (
        "127.",
        "10.",
        "192.168.",
        "172.16.",
        "172.17.",
        "172.18.",
        "172.19.",
        "172.20.",
        "172.21.",
        "172.22.",
        "172.23.",
        "172.24.",
        "172.25.",
        "172.26.",
        "172.27.",
        "172.28.",
        "172.29.",
        "172.30.",
        "172.31.",
        "::1",
    )

    if ip_address.startswith(private_prefixes):
        return None

    def _lookup() -> str | None:
        try:
            request = URLRequest(
                f"https://ipwho.is/{ip_address}",
                headers={
                    "User-Agent": "ShopMind-AI/1.0",
                },
            )

            with urlopen(
                request,
                timeout=3,
            ) as response:
                data: dict[str, Any] = json.loads(
                    response.read().decode("utf-8")
                )

            if not data.get("success", True):
                return None

            return normalize_country_code(
                data.get("country_code")
            )

        except Exception:
            return None

    return await asyncio.to_thread(
        _lookup
    )


async def reverse_geocode_coordinates(
    latitude: float,
    longitude: float,
) -> dict[str, str] | None:
    """Best-effort reverse geocoding for browser-provided coordinates.

    This is used only to choose the correct regional source/currency and to
    make quick-commerce searches location-aware. Exact inventory/ETA is never
    inferred from coordinates alone.
    """
    import asyncio
    import json
    from urllib.parse import urlencode
    from urllib.request import Request as URLRequest, urlopen

    if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
        return None

    def _lookup() -> dict[str, str] | None:
        try:
            query = urlencode({
                "format": "jsonv2",
                "lat": f"{float(latitude):.6f}",
                "lon": f"{float(longitude):.6f}",
                "zoom": "10",
                "addressdetails": "1",
            })
            request = URLRequest(
                f"https://nominatim.openstreetmap.org/reverse?{query}",
                headers={
                    "User-Agent": "ShopMind-AI/1.0 (regional-shopping)",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))

            address = data.get("address") or {}
            country = str(address.get("country_code") or "").upper()
            if len(country) != 2:
                return None

            city = (
                address.get("city")
                or address.get("town")
                or address.get("municipality")
                or address.get("village")
                or address.get("county")
                or ""
            )
            region = address.get("state") or address.get("state_district") or ""
            label = ", ".join(x for x in (str(city).strip(), str(region).strip(), country) if x)

            return {
                "country_code": country,
                "city": str(city).strip(),
                "region": str(region).strip(),
                "postal_code": str(address.get("postcode") or "").strip(),
                "label": label,
            }
        except Exception:
            return None

    return await asyncio.to_thread(_lookup)


async def resolve_region(
    *,
    country_code: str | None = None,
    accept_language: str | None = None,
    ip_address: str | None = None,
    preferred_currency: str | None = None,
) -> tuple[str | None, str]:
    """Resolve country and display currency.

    Priority:
        1. Explicit currency
        2. Explicit country
        3. Accept-Language
        4. IP geolocation
        5. USD fallback
    """

    # Explicit currency wins.
    if preferred_currency:
        currency = preferred_currency.strip().upper()

        if currency in CURRENCY_NAMES or currency in set(COUNTRY_CURRENCY.values()):
            country = normalize_country_code(
                country_code
            )

            if not country:
                country = (
                    detect_country_from_accept_language(
                        accept_language
                    )
                )

            if not country:
                country = await detect_country_from_ip(
                    ip_address
                )

            return country, currency

    # Explicit country.
    country = normalize_country_code(
        country_code
    )

    if country:
        return (
            country,
            currency_for_country(country),
        )

    # Browser language/locale.
    country = detect_country_from_accept_language(
        accept_language
    )

    if country:
        return (
            country,
            currency_for_country(country),
        )

    # IP fallback.
    country = await detect_country_from_ip(
        ip_address
    )

    if country:
        return (
            country,
            currency_for_country(country),
        )

    # Safe fallback.
    return None, "USD"


# ---------------------------------------------------------------------------
# Exchange rate client
# ---------------------------------------------------------------------------


class CurrencyConverter:
    """Live currency conversion service."""

    def __init__(
        self,
        timeout: float = 5.0,
    ) -> None:
        self.timeout = timeout
        self._cache: dict[
            tuple[str, str],
            float,
        ] = {}

    async def get_rate(
        self,
        from_currency: str,
        to_currency: str,
    ) -> float:
        """Get a live exchange rate.

        Uses Open Exchange Rates style public endpoint:
        open.er-api.com.

        Falls back to 1.0 for same currency.
        """

        source = from_currency.upper()
        target = to_currency.upper()

        if source == target:
            return 1.0

        cache_key = (
            source,
            target,
        )

        if cache_key in self._cache:
            return self._cache[cache_key]

        rate = await self._fetch_rate(
            source,
            target,
        )

        self._cache[cache_key] = rate

        return rate

    async def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> float:
        """Convert an amount to another currency."""

        rate = await self.get_rate(
            from_currency,
            to_currency,
        )

        return round(
            amount * rate,
            2,
        )

    async def _fetch_rate(
        self,
        source: str,
        target: str,
    ) -> float:
        """Fetch a live exchange rate."""

        def _request() -> float:
            url = (
                "https://open.er-api.com/v6/latest/"
                f"{source}"
            )

            request = URLRequest(
                url,
                headers={
                    "User-Agent": "ShopMind-AI/1.0",
                },
            )

            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                data: dict[str, Any] = json.loads(
                    response.read().decode("utf-8")
                )

            if data.get("result") != "success":
                raise RuntimeError(
                    "Currency API returned an error."
                )

            rates = data.get(
                "rates",
                {},
            )

            rate = rates.get(
                target
            )

            if rate is None:
                raise RuntimeError(
                    f"No exchange rate found for "
                    f"{source} -> {target}"
                )

            return float(rate)

        try:
            return await asyncio.to_thread(
                _request
            )

        except Exception:
            # Do not break shopping completely because
            # currency conversion failed.
            return 1.0