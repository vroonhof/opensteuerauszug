import importlib
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from opensteuerauszug.model.ech0196 import TaxStatement
from opensteuerauszug.render.translations import DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)


@dataclass
class ImporterRegistryEntry:
    name: str
    importer_class_path: str
    settings_class_path: str
    input_type: str  # "dir" or "file"
    supports_strict_consistency: bool
    supports_render_language: bool

    def get_importer_class(self) -> Type[Any]:
        if self.name == "ibkr":
            try:
                import ibflex

                ibflex.enable_unknown_attribute_tolerance()
            except (ImportError, AttributeError):
                pass
        module_name, class_name = self.importer_class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def get_settings_class(self) -> Type[Any]:
        module_name, class_name = self.settings_class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)


_REGISTRY: Dict[str, ImporterRegistryEntry] = {
    "schwab": ImporterRegistryEntry(
        name="schwab",
        importer_class_path="opensteuerauszug.importers.schwab.schwab_importer.SchwabImporter",
        settings_class_path="opensteuerauszug.config.models.SchwabAccountSettings",
        input_type="dir",
        supports_strict_consistency=True,
        supports_render_language=True,
    ),
    "fidelity": ImporterRegistryEntry(
        name="fidelity",
        importer_class_path="opensteuerauszug.importers.fidelity.fidelity_importer.FidelityImporter",
        settings_class_path="opensteuerauszug.config.models.FidelityAccountSettings",
        input_type="dir",
        supports_strict_consistency=True,
        supports_render_language=True,
    ),
    "ibkr": ImporterRegistryEntry(
        name="ibkr",
        importer_class_path="opensteuerauszug.importers.ibkr.ibkr_importer.IbkrImporter",
        settings_class_path="opensteuerauszug.config.models.IbkrAccountSettings",
        input_type="file",
        supports_strict_consistency=False,
        supports_render_language=True,
    ),
    "degiro": ImporterRegistryEntry(
        name="degiro",
        importer_class_path="opensteuerauszug.importers.degiro.degiro_importer.DegiroImporter",
        settings_class_path="opensteuerauszug.config.models.DegiroAccountSettings",
        input_type="dir",
        supports_strict_consistency=False,
        supports_render_language=False,
    ),
}


def get_importer_entry(name: str) -> ImporterRegistryEntry:
    """Look up an importer entry by name."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Importer '{name}' is not registered. Registered importers: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def create_importer(
    name: str,
    period_from: date,
    period_to: date,
    account_settings_list: List[Any],
    strict_consistency: bool = True,
    render_language: str = DEFAULT_LANGUAGE,
) -> Any:
    """Dynamically instantiate an importer based on its registered parameters."""
    entry = get_importer_entry(name)
    importer_cls = entry.get_importer_class()

    kwargs: Dict[str, Any] = {
        "period_from": period_from,
        "period_to": period_to,
        "account_settings_list": account_settings_list,
    }

    if entry.supports_strict_consistency:
        kwargs["strict_consistency"] = strict_consistency

    if entry.supports_render_language:
        kwargs["render_language"] = render_language

    return importer_cls(**kwargs)


def run_import(
    name: str,
    importer: Any,
    input_file: Path,
    corrections_flex: Optional[List[Path]] = None,
) -> TaxStatement:
    """Execute import on the instantiated importer based on its input type."""
    entry = get_importer_entry(name)

    if entry.input_type == "dir":
        if not input_file.is_dir():
            raise ValueError(
                f"Input for {name} importer must be a directory, but got: {input_file}"
            )
        return importer.import_dir(str(input_file))

    elif entry.input_type == "file":
        if not input_file.is_file():
            raise ValueError(f"Input for {name} importer must be a file, but got: {input_file}")

        if name == "ibkr":
            corrections_filenames = [str(p) for p in corrections_flex] if corrections_flex else None
            return importer.import_files(
                [str(input_file)], corrections_filenames=corrections_filenames
            )
        else:
            return importer.import_files([str(input_file)])

    else:
        raise ValueError(
            f"Unsupported input type '{entry.input_type}' in registry entry for '{name}'"
        )
