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


def test_split_full_name_truncates_joint_account_at_separator():
    # English " and " - keep primary holder, drop the rest.
    assert split_full_name("Firstname Lastname and Othername Other-Lastname") == (
        "Firstname",
        "Lastname",
    )
    # German / Swiss-German " und " - same treatment.
    assert split_full_name("Firstname Lastname und Othername Other-Lastname") == (
        "Firstname",
        "Lastname",
    )
    # Case-insensitive uppercase separator.
    assert split_full_name("Alice Smith AND Bob Jones") == ("Alice", "Smith")
    # Leading/trailing whitespace and excess whitespace are normalised.
    assert split_full_name("  Alice Smith   and   Bob Jones  ") == ("Alice", "Smith")
    # No separator present at all - falls back to the regular split.
    assert split_full_name("John Quincy Adams") == ("John", "Quincy Adams")


def test_resolve_prefers_explicit_first_last():
    assert resolve_first_last_name(first_name="A", last_name="B") == ("A", "B")


def test_resolve_combines_first_with_full_name_surname():
    assert resolve_first_last_name(first_name="A", full_name="X Y Z") == ("A", "Y Z")


def test_resolve_falls_back_to_account_holder_name():
    assert resolve_first_last_name(account_holder_name="X Y") == ("X", "Y")


def test_resolve_joint_account_name_fits_in_last_name_schema():
    # The joint-account pattern would otherwise overflow the 30-char
    # lastName schema limit once the bare name field is used as a surname.
    first, last = resolve_first_last_name(
        full_name="Firstname Lastname and Othername Other-Lastname",
    )
    assert first == "Firstname"
    assert last is not None and len(last) <= 30


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
