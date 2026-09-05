"""ICAO 9303 TD3 machine-readable-zone parsing.

Fixtures are the ICAO specimen and synthetic documents; no real identity
document appears here. Check digits are computed with the module's own
``checksum`` so a fixture can never carry hand-arithmetic errors.
"""

from __future__ import annotations

import pytest

from crewlisterpro.ocr import checksum, parse_mrz


def line2(
    number: str = "L898902C3",
    nationality: str = "UTO",
    birth: str = "740812",
    sex: str = "F",
    expiry: str = "320415",
    personal: str = "ZE184226B",
) -> str:
    """A well-formed TD3 second line with every check digit computed."""
    number_field = f"{number:<9}".replace(" ", "<")[:9]
    personal_field = f"{personal:<14}".replace(" ", "<")[:14]
    composite = (
        f"{number_field}{checksum(number_field)}"
        f"{birth}{checksum(birth)}{expiry}{checksum(expiry)}"
        f"{personal_field}{checksum(personal_field)}"
    )
    return (
        f"{number_field}{checksum(number_field)}{nationality}"
        f"{birth}{checksum(birth)}{sex}{expiry}{checksum(expiry)}"
        f"{personal_field}{checksum(personal_field)}{checksum(composite)}"
    )


def line1(surname: str = "ERIKSSON", given: str = "ANNA<MARIA", nationality: str = "UTO") -> str:
    return f"P<{nationality}{surname}<<{given}".ljust(44, "<")


def mrz(**kwargs) -> str:
    return f"{line1()}\n{line2(**kwargs)}"


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_parses_the_icao_specimen():
    result = parse_mrz(mrz())
    assert result is not None
    assert result["document_number"] == "L898902C3"
    assert result["full_name"] == "ANNA MARIA ERIKSSON"
    assert result["birth_date"] == "1974-08-12"
    assert result["sex"] == "F"
    assert result["nationality"] == "UTO"
    assert result["document_type"] == "passport"


def test_ignores_surrounding_ocr_noise():
    noisy = f"PASSPORT\n{line1()}\n{line2()}\nSHOT ON MI 8 LITE"
    assert parse_mrz(noisy)["document_number"] == "L898902C3"


def test_rejects_plain_text():
    assert parse_mrz("nothing machine readable here at all") is None
    assert parse_mrz("") is None


# --------------------------------------------------------------------------
# Two-digit years
# --------------------------------------------------------------------------


def test_an_expiry_in_the_thirties_resolves_forward():
    """A fixed pivot at 30 read a 2035 expiry as 1935 — a valid passport
    presented as ninety years expired."""
    assert parse_mrz(mrz(expiry="350703"))["expiry_date"] == "2035-07-03"
    assert parse_mrz(mrz(expiry="310930"))["expiry_date"] == "2031-09-30"


def test_an_expiry_inside_the_current_decade_is_unchanged():
    assert parse_mrz(mrz(expiry="290528"))["expiry_date"] == "2029-05-28"


def test_a_recently_expired_document_stays_in_the_past():
    assert parse_mrz(mrz(expiry="200101"))["expiry_date"] == "2020-01-01"


def test_a_birth_date_is_never_resolved_into_the_future():
    assert parse_mrz(mrz(birth="841216"))["birth_date"] == "1984-12-16"
    assert parse_mrz(mrz(birth="130309"))["birth_date"] == "2013-03-09"


def test_no_parsed_expiry_precedes_its_birth_date():
    result = parse_mrz(mrz(birth="900629", expiry="310930"))
    assert result["birth_date"] < result["expiry_date"]


@pytest.mark.parametrize("value", ["749912", "840231", "840012"])
def test_impossible_calendar_dates_are_rejected(value):
    assert parse_mrz(mrz(birth=value)) is None


# --------------------------------------------------------------------------
# Line 2 stands on its own
# --------------------------------------------------------------------------


def test_a_garbled_name_line_does_not_discard_the_machine_readable_zone():
    """Line 2 carries its own check digits; line 1 carries none. Half of a
    real photographed set had a perfect line 2 beside a ruined line 1."""
    garbled = f"PEUKRMINCHUK<<OLSANDAAAAAAA1<1X11111111155\n{line2()}"
    result = parse_mrz(garbled)
    assert result is not None
    assert result["document_number"] == "L898902C3"
    assert result["birth_date"] == "1974-08-12"


def test_a_missing_name_line_still_yields_the_rest():
    result = parse_mrz(line2())
    assert result is not None
    assert result["document_number"] == "L898902C3"
    assert result["nationality"] == "UTO"
    assert result.get("full_name", "") == ""


def test_a_name_line_below_line_two_is_accepted():
    assert parse_mrz(f"{line2()}\n{line1()}")["full_name"] == "ANNA MARIA ERIKSSON"


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------


def test_a_name_line_containing_digits_is_not_turned_into_a_name():
    """Security print misread as characters must not become a legal name."""
    result = parse_mrz(f"P<UKRMINCHUK<<OLSANDAAAAAAA1<1X11111111155\n{line2()}")
    assert result is not None
    assert result.get("full_name", "") == ""


def test_filler_after_the_name_is_discarded():
    noisy = f"P<UKRMINCHUK<<MAKSYM<<<KKKKKKKRKRS<<<<<<<<<<\n{line2()}"
    assert parse_mrz(noisy)["full_name"] == "MAKSYM MINCHUK"


def test_multiple_given_names_are_kept():
    assert parse_mrz(mrz())["full_name"] == "ANNA MARIA ERIKSSON"


# --------------------------------------------------------------------------
# Every check digit on line 2
# --------------------------------------------------------------------------


def test_a_corrupted_document_number_check_digit_is_rejected():
    good = line2()
    bad = good[:9] + str((int(good[9]) + 1) % 10) + good[10:]
    assert parse_mrz(f"{line1()}\n{bad}") is None


def test_a_corrupted_birth_date_check_digit_is_rejected():
    good = line2()
    bad = good[:19] + str((int(good[19]) + 1) % 10) + good[20:]
    assert parse_mrz(f"{line1()}\n{bad}") is None


def test_a_corrupted_expiry_check_digit_is_rejected():
    good = line2()
    bad = good[:27] + str((int(good[27]) + 1) % 10) + good[28:]
    assert parse_mrz(f"{line1()}\n{bad}") is None


def test_an_all_filler_document_number_is_rejected():
    assert parse_mrz(f"{line1()}\n{line2(number='<<<<<<<<<')}") is None


def test_a_separator_misread_as_k_is_repaired():
    """OCR reads the "<<" separator as "K<" often enough to be worth repairing."""
    noisy = f"P<UKRSTETSENKOK<DIANA<K<<<<<<<<<<<KKKKKCKK<<\n{line2()}"
    assert parse_mrz(noisy)["full_name"] == "DIANA STETSENKO"


def test_a_surname_ending_in_k_survives_the_repair():
    noisy = f"P<UKRMINCHUK<<MAKSYM<<<<<<<<<<<<<<<<<<<<<<<\n{line2()}"
    assert parse_mrz(noisy)["full_name"] == "MAKSYM MINCHUK"


def test_a_zero_misread_for_the_letter_o_is_repaired_not_rejected():
    """A TD3 name zone is alphabetic; "0" is a routine misread of "O"."""
    noisy = f"P<UKRL0B0ZYNSKA<<KATERYNA<<<<<<<<<<<<<<<<<<<\n{line2()}"
    assert parse_mrz(noisy)["full_name"] == "KATERYNA LOBOZYNSKA"


def test_other_digits_still_disqualify_the_name_line():
    noisy = f"P<UKRBODNIA<<IRYNA1X1111<<<<<<<<<<<<<<<<<<<\n{line2()}"
    assert parse_mrz(noisy).get("full_name", "") == ""
