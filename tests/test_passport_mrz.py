from app.services.passport_mrz import detect_passport, find_mrz_lines, parse_mrz

_MRZ_LINE1 = "P<ESPVINIEGRA<PEREZ<OLAGARAY<<ESTEBAN<<<<<<<"
_MRZ_LINE2 = "XDF2352177ESP0109017M2911124RE20240704132446"

# Real sample provided by the user: correct visible-zone text matching the MRZ above.
_MATCHING_TEXT = (
    "ESPAÑA\nREINO DE ESPANA\nPASAPORTE\nТіро/Туре/Туре\nCodigo Code/Code\nP\nESP\n"
    "(1) ApelAdos/Somams/Nom\nVINIEGRA\nPEREZ OLAGARAY\n"
    "(2) Nombre Gren Names/Prénoma\nESTEBAN\n"
    "(3) Nacionalidad/Nationnily/NatonaRte\nESPAÑOLA\n(5) Sexo Sex/Sere\nM\n"
    "(8) Lugar de nacimiento/Place of bith/Lieu de cness\nbarce\nMEXICO, D.F.\n(MEXICO)\n"
    "17) Fecha de expedición/Date of issun/Date de dilvrarios\n13\n11 2024\n"
    "(10) Firma del titular Holder's signature/Signature du litulairy\nPASSPORT\n"
    "PASAPORTE N°/PASSPORT No/PASSEPORT Nº\nXDF235217\n"
    "(4) Feche de nacimiento/Date of bith/Date, de naissarice\n01 09\n2001\n"
    "(11) Id. No\nRE202407041324\nDato al expir\n6 'охрігабоп\n12 11 2029\n"
    "(9) Autorida\nd/Authonty/Autorie\nC. G. MEXICO\n385416\n"
    f"{_MRZ_LINE1}\n{_MRZ_LINE2}\nEPSON\nL355"
)


def test_find_mrz_lines_detects_real_sample() -> None:
    found = find_mrz_lines(_MATCHING_TEXT)
    assert found == (_MRZ_LINE1, _MRZ_LINE2)


def test_find_mrz_lines_returns_none_for_non_passport_text() -> None:
    assert find_mrz_lines("factura de compra\ntotal: $150.00\ngracias por su compra") is None


def test_parse_mrz_extracts_correct_fields() -> None:
    mrz = parse_mrz(_MRZ_LINE1, _MRZ_LINE2)

    assert mrz.document_code == "P"
    assert mrz.issuing_country == "ESP"
    assert mrz.nationality == "ESP"
    assert mrz.passport_number == "XDF235217"
    assert mrz.surname == "VINIEGRA PEREZ OLAGARAY"
    assert mrz.given_names == "ESTEBAN"
    assert mrz.sex == "M"
    assert mrz.date_of_birth == "2001-09-01"
    assert mrz.date_of_expiry == "2029-11-12"
    assert mrz.personal_number == "RE202407041324"
    assert mrz.checksum_valid is True


def test_parse_mrz_detects_invalid_checksum() -> None:
    corrupted_line2 = _MRZ_LINE2[:9] + "9" + _MRZ_LINE2[10:]  # flip the passport check digit
    mrz = parse_mrz(_MRZ_LINE1, corrupted_line2)
    assert mrz.checksum_valid is False


def test_detect_passport_returns_none_when_no_mrz_present() -> None:
    assert detect_passport("un documento cualquiera sin MRZ") is None


def test_detect_passport_matches_visible_text_on_real_sample() -> None:
    result = detect_passport(_MATCHING_TEXT)

    assert result is not None
    assert result.mrz.passport_number == "XDF235217"
    assert result.mrz.checksum_valid is True
    assert result.matches_visible_text is True
    assert result.validation_error is None


def test_detect_passport_reports_mismatch_with_custom_error_message() -> None:
    # count=1: only tampers the visible-zone occurrence (it appears earlier in the
    # text than the MRZ block), so the MRZ itself stays intact and parses correctly
    # while now disagreeing with the visible field — the actual scenario being tested.
    tampered_text = _MATCHING_TEXT.replace("XDF235217", "ZZZ999999", 1)

    result = detect_passport(tampered_text)

    assert result is not None
    assert result.matches_visible_text is False
    assert result.validation_error is not None
    assert "no coinciden" in result.validation_error
    assert "XDF235217" in result.validation_error
