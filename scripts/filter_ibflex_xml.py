import argparse
import logging
import sys
from pathlib import Path

import lxml.etree as ET


ACCOUNT_INFO_ALLOWED_ATTRIBUTES = {
    "accountId",
    "acctAlias",
    "currency",
    "stateResidentialAddress",
}

ACCOUNT_INFO_ANONYMIZED_VALUES = {
    "accountId": "U0000000",
}


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def normalize_id(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().upper()


def parse_filter_ids(raw_values: list[str]) -> set[str]:
    filter_ids: set[str] = set()
    for raw_value in raw_values:
        for token in raw_value.split(","):
            normalized = normalize_id(token)
            if normalized:
                filter_ids.add(normalized)
    return filter_ids


def element_matches_isin(element: ET._Element, target_isins: set[str]) -> bool:
    isin = normalize_id(element.get("isin"))
    security_id = normalize_id(element.get("securityID"))
    security_id_type = (element.get("securityIDType") or "").strip().upper()
    underlying_security_id = normalize_id(element.get("underlyingSecurityID"))

    if isin and isin in target_isins:
        return True
    if security_id_type == "ISIN" and security_id and security_id in target_isins:
        return True
    if underlying_security_id and underlying_security_id in target_isins:
        return True
    return False


def collect_linked_conids(statement: ET._Element, target_isins: set[str], target_conids: set[str]) -> set[str]:
    linked_conids: set[str] = set()
    for element in statement.iter():
        if not isinstance(element.tag, str):
            continue
        if not element_matches_isin(element, target_isins):
            continue
        for attribute_name in ("conid", "underlyingConid"):
            conid = (element.get(attribute_name) or "").strip()
            if conid:
                linked_conids.add(conid)

    # Include explicitly specified contract IDs
    linked_conids.update(target_conids)
    return linked_conids

def element_matches_targets(
    element: ET._Element,
    target_isins: set[str],
    linked_conids: set[str],
) -> bool:
    if element_matches_isin(element, target_isins):
        return True

    conid = (element.get("conid") or "").strip()
    if conid and conid in linked_conids:
        return True

    underlying_conid = (element.get("underlyingConid") or "").strip()
    if underlying_conid and underlying_conid in linked_conids:
        return True

    return False


def prune_non_matching_descendants(
    container: ET._Element,
    target_isins: set[str],
    linked_conids: set[str],
) -> None:
    for child in list(container):
        if not isinstance(child.tag, str):
            container.remove(child)
            continue

        prune_non_matching_descendants(child, target_isins, linked_conids)
        has_element_children = any(isinstance(grandchild.tag, str) for grandchild in child)

        if not element_matches_targets(child, target_isins, linked_conids) and not has_element_children:
            container.remove(child)

def sanitize_statement_information(statement: ET._Element) -> None:
    for name, value in ACCOUNT_INFO_ANONYMIZED_VALUES.items():
        if statement.get(name) is not None:
            statement.set(name, value)

def sanitize_account_information(statement: ET._Element) -> None:
    account_information = None
    for child in statement:
        if isinstance(child.tag, str) and local_name(child.tag) == "AccountInformation":
            account_information = child
            break

    if account_information is None:
        return

    allowed_attributes: dict[str, str] = {}
    for name in ACCOUNT_INFO_ALLOWED_ATTRIBUTES:
        value = account_information.get(name)
        if value is not None:
            allowed_attributes[name] = value

    for name, value in ACCOUNT_INFO_ANONYMIZED_VALUES.items():
        if name in allowed_attributes:
            allowed_attributes[name] = value

    account_information.attrib.clear()
    account_information.attrib.update(allowed_attributes)


def filter_statement(statement: ET._Element, target_isins: set[str], target_conids: set[str]) -> None:
    linked_conids = collect_linked_conids(statement, target_isins, target_conids)

    sanitize_statement_information(statement)

    for child in list(statement):
        if not isinstance(child.tag, str):
            statement.remove(child)
            continue

        if local_name(child.tag) == "AccountInformation":
            sanitize_account_information(statement)
            continue

        prune_non_matching_descendants(child, target_isins, linked_conids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a minimal IBKR Flex XML by keeping only entries linked to specific ISINs "
            "and anonymizing AccountInformation attributes."
        )
    )
    parser.add_argument("--input-file", required=True, help="Path to source IBKR Flex XML file.")
    parser.add_argument("--output-file", required=True, help="Path to write filtered XML file.")
    parser.add_argument(
        "--isins",
        nargs="+",
        help="ISINs to keep (space and/or comma separated).",
    )
    parser.add_argument(
        "--conids",
        nargs="+",
        help="Contract IDs to keep (space and/or comma separated).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    if args.isins is None and args.conids is None:
        logging.error("At least one of --isins or --conids must be provided.")
        return 1

    target_isins = parse_filter_ids(args.isins) if args.isins else set()
    target_conids = parse_filter_ids(args.conids) if args.conids else set()

    if not target_isins and not target_conids:
        logging.error("No valid ISINs or Contract IDs were provided.")
        return 1

    logging.info("Keeping %s ISIN(s): %s / %s Contract ID(s): %s", len(target_isins), sorted(target_isins), len(target_conids), sorted(target_conids))
    
    try:
        parser = ET.XMLParser(remove_blank_text=True)
        tree = ET.parse(args.input_file, parser)
    except (OSError, ET.XMLSyntaxError) as exc:
        logging.error("Failed to parse input XML '%s': %s", args.input_file, exc)
        return 1

    root = tree.getroot()
    statements = [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and local_name(element.tag) == "FlexStatement"
    ]

    if not statements:
        logging.error("No FlexStatement elements found in input XML.")
        return 1

    for index, statement in enumerate(statements, start=1):
        logging.info("Filtering FlexStatement %s/%s", index, len(statements))
        filter_statement(statement, target_isins, target_conids)

    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        tree.write(
            str(output_path),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    except OSError as exc:
        logging.error("Failed to write output XML '%s': %s", args.output_file, exc)
        return 1

    logging.info("Wrote filtered XML to %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
