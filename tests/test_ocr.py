from crewlisterpro.ocr import checksum, parse_mrz


def test_checksum_and_mrz_parse() -> None:
    result = parse_mrz(
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
    )
    assert checksum("L898902C3") == 6
    assert result is not None
    assert result["document_number"] == "L898902C3"
    assert result["full_name"] == "ANNA MARIA ERIKSSON"
