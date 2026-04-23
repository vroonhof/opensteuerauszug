from opensteuerauszug.importers.common import (
    build_client,
    parse_swiss_canton,
    resolve_first_last_name,
    split_full_name,
)


def test_split_full_name_single_and_multi_token():
    assert split_full_name("Madonna") == (None, "Madonna")
    assert split_full_name("Firstname Lastname") == ("Firstname", "Lastname")
    assert split_full_name("  First Middle Last  ") == ("First", "Middle Last")


def test_resolve_prefers_explicit_first_last():
    assert resolve_first_last_name(first_name="A", last_name="B") == ("A", "B")


def test_resolve_combines_first_with_full_name_surname():
    assert resolve_first_last_name(first_name="A", full_name="X Y Z") == ("A", "Y Z")


def test_resolve_falls_back_to_account_holder_name():
    assert resolve_first_last_name(account_holder_name="X Y") == ("X", "Y")


def test_resolve_returns_none_when_nothing_valid():
    assert resolve_first_last_name() == (None, None)
    assert resolve_first_last_name(full_name="   ") == (None, None)


def test_parse_canton_plain_code_and_address_form():
    assert parse_swiss_canton("ZH") == "ZH"
    assert parse_swiss_canton("zh") == "ZH"
    assert parse_swiss_canton("CH-ZH") == "ZH"
    assert parse_swiss_canton(" CH-be ") == "BE"


def test_parse_canton_rejects_garbage_and_empty():
    assert parse_swiss_canton(None) is None
    assert parse_swiss_canton("") is None
    assert parse_swiss_canton("XX") is None
    assert parse_swiss_canton("US-CA") is None
    assert parse_swiss_canton("CH-XX") is None


def test_build_client_requires_client_number():
    assert build_client(None, "A", "B") is None
    assert build_client("", "A", "B") is None
    c = build_client("U12345", "A", "B")
    assert c is not None and c.clientNumber == "U12345"
    assert c.firstName == "A" and c.lastName == "B"
