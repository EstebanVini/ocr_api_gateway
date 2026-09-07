import re
import unicodedata
from datetime import date

from app.models.passport import PassportData, PassportMrzData

_LINE1_RE = re.compile(r"^P[A-Z<]([A-Z<]{3})([A-Z<]{39})$")
_LINE2_RE = re.compile(
    r"^([A-Z0-9<]{9})([0-9])([A-Z<]{3})([0-9]{6})([0-9])([MFX<])"
    r"([0-9]{6})([0-9])([A-Z0-9<]{14})([0-9<])([0-9])$"
)


def _char_value(ch: str) -> int:
    if ch == "<":
        return 0
    if ch.isdigit():
        return int(ch)
    return ord(ch) - ord("A") + 10


def _check_digit(value: str) -> int:
    weights = (7, 3, 1)
    return sum(_char_value(c) * weights[i % 3] for i, c in enumerate(value)) % 10


def _yymmdd_to_iso(yymmdd: str, *, allow_future: bool) -> str | None:
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    reference_year = date.today().year
    year = (reference_year // 100) * 100 + yy
    if not allow_future and year > reference_year:
        year -= 100
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return None


def _decode_names(name_field: str) -> tuple[str, str]:
    surname_raw, _, given_raw = name_field.rstrip("<").partition("<<")
    surname = surname_raw.replace("<", " ").strip()
    given_names = given_raw.replace("<", " ").strip()
    return surname, given_names


def find_mrz_lines(text: str) -> tuple[str, str] | None:
    """Scans OCR text for two consecutive lines matching the TD3 passport MRZ format
    (2 lines x 44 chars, per ICAO 9303). Returns (line1, line2), or None if absent."""
    lines = [line.strip().upper() for line in text.splitlines()]
    for line1, line2 in zip(lines, lines[1:], strict=False):
        if _LINE1_RE.match(line1) and _LINE2_RE.match(line2):
            return line1, line2
    return None


def parse_mrz(line1: str, line2: str) -> PassportMrzData:
    line1_match = _LINE1_RE.match(line1)
    line2_match = _LINE2_RE.match(line2)
    if line1_match is None or line2_match is None:
        raise ValueError("Las lineas no cumplen el formato MRZ TD3.")

    country, name_field = line1_match.groups()
    (
        passport_no_raw,
        passport_check,
        nationality,
        dob_raw,
        dob_check,
        sex,
        expiry_raw,
        expiry_check,
        personal_no_raw,
        personal_check,
        composite_check,
    ) = line2_match.groups()

    surname, given_names = _decode_names(name_field)
    composite_input = line2[0:10] + line2[13:20] + line2[21:28] + line2[28:43]

    checksum_valid = (
        _check_digit(passport_no_raw) == int(passport_check)
        and _check_digit(dob_raw) == int(dob_check)
        and _check_digit(expiry_raw) == int(expiry_check)
        and (personal_check == "<" or _check_digit(personal_no_raw) == int(personal_check))
        and _check_digit(composite_input) == int(composite_check)
    )

    return PassportMrzData(
        document_code="P",
        issuing_country=country,
        nationality=nationality,
        passport_number=passport_no_raw.rstrip("<"),
        surname=surname,
        given_names=given_names,
        sex=sex if sex != "<" else "X",
        date_of_birth=_yymmdd_to_iso(dob_raw, allow_future=False),
        date_of_expiry=_yymmdd_to_iso(expiry_raw, allow_future=True),
        personal_number=personal_no_raw.rstrip("<") or None,
        checksum_valid=checksum_valid,
        raw_line1=line1,
        raw_line2=line2,
    )


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _flatten(text: str) -> str:
    return _strip_accents(" ".join(text.split())).upper()


def _flex_num(num_str: str) -> str:
    """Matches a zero-padded number with or without its leading zero (visible-zone
    dates aren't always zero-padded the same way the MRZ is)."""
    stripped = num_str.lstrip("0")
    return f"0?{stripped}" if stripped else "0"


def _appears_as_word(token: str, flat_text: str) -> bool:
    if not token:
        return True
    return re.search(rf"\b{re.escape(token)}\b", flat_text) is not None


def _date_appears(iso_date: str, flat_text: str) -> bool:
    year, month, day = iso_date.split("-")
    pattern = rf"\b{_flex_num(day)}\s*[/\-. ]\s*{_flex_num(month)}\s*[/\-. ]\s*{year}\b"
    return re.search(pattern, flat_text) is not None


def _validate_against_text(mrz: PassportMrzData, text: str) -> list[str]:
    flat = _flatten(text)
    mismatches: list[str] = []

    for word in mrz.surname.split():
        if not _appears_as_word(word, flat):
            mismatches.append(f"apellido '{word}' no encontrado en el texto visible")
    for word in mrz.given_names.split():
        if not _appears_as_word(word, flat):
            mismatches.append(f"nombre '{word}' no encontrado en el texto visible")
    if not _appears_as_word(mrz.passport_number, flat):
        mismatches.append(
            f"numero de pasaporte '{mrz.passport_number}' no encontrado en el texto visible"
        )
    if mrz.personal_number and not _appears_as_word(mrz.personal_number, flat):
        mismatches.append(
            f"numero de identificacion '{mrz.personal_number}' no encontrado en el texto visible"
        )
    if mrz.date_of_birth and not _date_appears(mrz.date_of_birth, flat):
        mismatches.append(
            f"fecha de nacimiento ({mrz.date_of_birth}) no encontrada en el texto visible"
        )
    if mrz.date_of_expiry and not _date_appears(mrz.date_of_expiry, flat):
        mismatches.append(
            f"fecha de vencimiento ({mrz.date_of_expiry}) no encontrada en el texto visible"
        )

    return mismatches


def detect_passport(text: str) -> PassportData | None:
    """Detects a TD3 passport MRZ in the OCR text and, if found, cross-validates the
    extracted fields against the free-text visible zone. Returns None when no MRZ is
    found — i.e. the document isn't a passport, or OCR didn't capture its MRZ.
    """
    found = find_mrz_lines(text)
    if found is None:
        return None

    mrz = parse_mrz(*found)
    mismatches = _validate_against_text(mrz, text)

    return PassportData(
        mrz=mrz,
        matches_visible_text=not mismatches,
        validation_error=(
            "Los datos del MRZ no coinciden con el texto visible del documento: "
            + "; ".join(mismatches)
            if mismatches
            else None
        ),
    )
