"""
Data structures and helpers for locale and geolocation info.
"""

import xml.etree.ElementTree as ET  # nosec
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from language_tags import tags

from .._warnings import LeakWarning
from ..assets import get_asset_by_name
from ..exceptions import InvalidLocale, UnknownLanguage, UnknownTerritory


@dataclass
class Locale:
    """
    Stores locale, region, and script information.
    """

    language: str
    region: str | None = None
    script: str | None = None

    @property
    def as_string(self) -> str:
        if self.region:
            return f"{self.language}-{self.region}"
        return self.language

    def as_config(self) -> dict[str, Any]:
        """
        Converts the locale to a nested profile dictionary.
        """
        assert self.region
        data = {"region": self.region, "language": self.language}
        if self.script:
            data["script"] = self.script
        return {"locale": data}


@dataclass(frozen=True)
class Geolocation:
    """
    Stores geolocation information.
    """

    locale: Locale
    longitude: float
    latitude: float
    timezone: str
    accuracy: float | None = None

    def as_config(self) -> dict[str, Any]:
        """
        Converts the geolocation to a nested profile dictionary.
        """
        data = {
            "geolocation": {
                "longitude": self.longitude,
                "latitude": self.latitude,
            },
            "timezone": self.timezone,
            **self.locale.as_config(),
        }
        if self.accuracy:
            data["geolocation"]["accuracy"] = self.accuracy
        return data


def verify_locale(loc: str) -> None:
    """
    Verifies that a locale is valid.
    Takes either language-region or language.
    """
    if tags.check(loc):
        return
    raise InvalidLocale.invalid_input(loc)


def normalize_locale(locale: str) -> Locale:
    """
    Normalizes and validates a locale code.
    """
    verify_locale(locale)

    parser = tags.tag(locale)
    if not parser.region:
        raise InvalidLocale.invalid_input(locale)

    record = parser.language.data["record"]
    return Locale(
        language=record["Subtag"],
        region=parser.region.data["record"]["Subtag"],
        script=record.get("Suppress-Script"),
    )


def handle_locale(locale: str, ignore_region: bool = False) -> Locale:
    """
    Handles a locale input, normalizing it if necessary.
    """
    if len(locale) > 3:
        return normalize_locale(locale)

    try:
        return SELECTOR.from_region(locale)
    except UnknownTerritory:
        pass

    if ignore_region:
        verify_locale(locale)
        return Locale(language=locale)

    try:
        language = SELECTOR.from_language(locale)
    except UnknownLanguage:
        pass
    else:
        LeakWarning.warn("no_region")
        return language

    raise InvalidLocale.invalid_input(locale)


def handle_locales(locales: str | list[str], config: Any) -> None:
    """
    Handles a list of locales.
    """
    if isinstance(locales, str):
        locales = [loc.strip() for loc in locales.split(",")]

    intl_locale = handle_locale(locales[0])
    if hasattr(config, "locale"):
        from .._generated_profile import LocaleProfile, NavigatorProfile

        config.locale = config.locale or LocaleProfile()
        config.navigator = config.navigator or NavigatorProfile()
        config.locale.language = intl_locale.language
        config.locale.region = intl_locale.region
        config.locale.script = intl_locale.script
        config.navigator.language = intl_locale.as_string
    else:
        config.setdefault("locale", {})
        config["locale"].update(intl_locale.as_config()["locale"])
        config.setdefault("navigator", {})
        config["navigator"]["language"] = intl_locale.as_string

    if len(locales) < 2:
        return

    all_locales = _join_unique(handle_locale(locale, ignore_region=True).as_string for locale in locales)
    if hasattr(config, "locale"):
        config.locale.all = all_locales
    else:
        config["locale"]["all"] = all_locales


def _join_unique(seq: Iterable[str]) -> str:
    """
    Joins a sequence of strings without duplicates
    """
    seen: set[str] = set()
    return ", ".join(x for x in seq if not (x in seen or seen.add(x)))


def get_unicode_info() -> ET.Element:
    """
    Fetches supplemental data from the territoryInfo.xml file.
    Source: https://raw.githubusercontent.com/unicode-org/cldr/master/common/supplemental/supplementalData.xml
    """
    with open(get_asset_by_name("territoryInfo.xml"), "rb") as f:
        data = ET.XML(f.read())
    assert data is not None, "Failed to load territoryInfo.xml"
    return data


def _as_float(element: ET.Element, attr: str) -> float:
    """
    Converts an attribute to a float.
    """
    return float(element.get(attr, 0))


class StatisticalLocaleSelector:
    """
    Selects a random locale based on statistical data.
    Takes either a territory code or a language code, and generates a Locale object.
    """

    def __init__(self):
        self.root = get_unicode_info()

    def _load_territory_data(self, iso_code: str) -> tuple[np.ndarray, np.ndarray]:
        """
        Calculates a random language based on the territory code,
        based on the probability that a person speaks the language in the territory.
        """
        territory = self.root.find(f"territory[@type='{iso_code}']")
        if territory is None:
            raise UnknownTerritory(f"Unknown territory: {iso_code}")

        lang_populations = territory.findall("languagePopulation")
        if not lang_populations:
            raise ValueError(f"No language data found for region: {iso_code}")

        languages = np.array([lang.get("type") for lang in lang_populations])
        percentages = np.array([_as_float(lang, "populationPercent") for lang in lang_populations])

        return self.normalize_probabilities(languages, percentages)

    def _load_language_data(self, language: str) -> tuple[np.ndarray, np.ndarray]:
        """
        Calculates a random region for a language
        based on the total speakers of the language in that region.
        """
        territories = self.root.findall(f'.//territory/languagePopulation[@type="{language}"]/..')
        if not territories:
            raise UnknownLanguage(f"No region data found for language: {language}")

        regions = []
        percentages = []

        for terr in territories:
            region = terr.get("type")
            if region is None:
                continue

            lang_pop = terr.find(f'languagePopulation[@type="{language}"]')
            if lang_pop is None:
                continue

            regions.append(region)
            percentages.append(
                _as_float(lang_pop, "populationPercent")
                * _as_float(terr, "literacyPercent")
                / 10_000
                * _as_float(terr, "population")
            )

        if not regions:
            raise ValueError(f"No valid region data found for language: {language}")

        return self.normalize_probabilities(np.array(regions), np.array(percentages))

    def normalize_probabilities(
        self,
        languages: np.ndarray,
        freq: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Normalize probabilities.
        """
        total = np.sum(freq)
        return languages, freq / total

    def from_region(self, region: str) -> Locale:
        """
        Get a random locale based on the territory ISO code.
        Returns as a Locale object.
        """
        languages, probabilities = self._load_territory_data(region)
        language = np.random.choice(languages, p=probabilities).replace("_", "-")
        return normalize_locale(f"{language}-{region}")

    def from_language(self, language: str) -> Locale:
        """
        Get a random locale based on the language.
        Returns as a Locale object.
        """
        regions, probabilities = self._load_language_data(language)
        region = np.random.choice(regions, p=probabilities)
        return normalize_locale(f"{language}-{region}")


SELECTOR = StatisticalLocaleSelector()
