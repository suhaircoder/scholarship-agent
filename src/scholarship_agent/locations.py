"""Country and region names found in titles, excerpts, and feed categories."""

from __future__ import annotations

import re

# Alias -> canonical label. Longer aliases are matched first.
_ALIASES: dict[str, str] = {
    "united states of america": "United States",
    "united states": "United States",
    "usa": "United States",
    "u.s.a": "United States",
    "u.s.": "United States",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "south korea": "South Korea",
    "korea": "South Korea",
    "north korea": "North Korea",
    "czech republic": "Czechia",
    "czechia": "Czechia",
    "the netherlands": "Netherlands",
    "netherlands": "Netherlands",
    "holland": "Netherlands",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "saudi arabia": "Saudi Arabia",
    "saudi": "Saudi Arabia",
    "saudia": "Saudi Arabia",
    "ksa": "Saudi Arabia",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "turkish": "Turkey",
    "istanbul": "Turkey",
    "istanbul": "Turkey",
    "italia": "Italy",
    "italian": "Italy",
    "chinese": "China",
    "south africa": "South Africa",
    "new zealand": "New Zealand",
    "hong kong": "Hong Kong",
    "papua new guinea": "Papua New Guinea",
    "equatorial guinea": "Equatorial Guinea",
    "costa rica": "Costa Rica",
    "sri lanka": "Sri Lanka",
    "sierra leone": "Sierra Leone",
    "burkina faso": "Burkina Faso",
    "european union": "European Union",
    "europe": "Europe",
}

for _name in (
    "Afghanistan", "Albania", "Algeria", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahrain", "Bangladesh", "Belgium", "Benin", "Bolivia", "Bosnia",
    "Botswana", "Brazil", "Bulgaria", "Cambodia", "Cameroon", "Canada", "Chile", "China",
    "Colombia", "Croatia", "Cuba", "Cyprus", "Denmark", "Ecuador", "Egypt", "Estonia",
    "Ethiopia", "Finland", "France", "Georgia", "Germany", "Ghana", "Greece", "Hungary",
    "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy",
    "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kuwait", "Latvia", "Lebanon",
    "Lithuania", "Luxembourg", "Malaysia", "Malta", "Mexico", "Morocco", "Nepal",
    "Nigeria", "Norway", "Oman", "Pakistan", "Palestine", "Peru", "Philippines", "Poland",
    "Portugal", "Qatar", "Romania", "Rwanda", "Senegal", "Serbia", "Singapore",
    "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland", "Taiwan", "Tanzania",
    "Thailand", "Tunisia", "Turkey", "Uganda", "Ukraine", "Uruguay", "Uzbekistan",
    "Vietnam", "Yemen", "Zambia", "Zimbabwe",
    "Andorra", "Angola", "Bahamas", "Barbados", "Belarus", "Belize", "Bhutan",
    "Brunei", "Burundi", "Chad", "Congo", "Djibouti", "Dominican Republic",
    "El Salvador", "Eritrea", "Fiji", "Gabon", "Gambia", "Guatemala", "Guinea",
    "Guyana", "Haiti", "Honduras", "Ivory Coast", "Kyrgyzstan", "Laos", "Liberia",
    "Libya", "Madagascar", "Malawi", "Maldives", "Mali", "Mauritania", "Mauritius",
    "Moldova", "Mongolia", "Montenegro", "Mozambique", "Myanmar", "Namibia",
    "Nicaragua", "Niger", "North Macedonia", "Panama", "Paraguay", "Samoa",
    "Senegal", "Somalia", "Sudan", "Suriname", "Syria", "Tajikistan", "Togo",
    "Trinidad and Tobago", "Turkmenistan", "Venezuela",
):
    _ALIASES.setdefault(_name.lower(), _name)

_SORTED = sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
_CANONICAL = {label.lower(): label for label in _ALIASES.values()}
for _alias, _label in _ALIASES.items():
    _CANONICAL[_alias] = _label


def all_country_names() -> list[str]:
    """Every country the finder can filter, in alphabetical order."""
    return sorted(set(_ALIASES.values()))


def canonicalize_country(value: str) -> str | None:
    return _CANONICAL.get(value.strip().lower())


def detect_countries(*parts: str) -> list[str]:
    text = " ".join(part for part in parts if part).lower()
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for alias, label in _SORTED:
        pattern = r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])"
        for match in re.finditer(pattern, text):
            span = match.span()
            if any(span[0] >= start and span[1] <= end for start, end in occupied):
                continue
            occupied.append(span)
            if label not in found:
                found.append(label)
    return found
