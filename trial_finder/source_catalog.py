"""Registry source catalog for the on-demand finder."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SourceCatalogEntry:
    id: str
    name: str
    operator: str
    status: str
    default_selected: bool
    official_url: str
    limitations: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


SOURCE_CATALOG: tuple[SourceCatalogEntry, ...] = (
    SourceCatalogEntry(
        id="clinicaltrials_gov",
        name="ClinicalTrials.gov",
        operator="U.S. National Library of Medicine / NIH",
        status="connected",
        default_selected=True,
        official_url="https://clinicaltrials.gov/",
        limitations="Uses the public ClinicalTrials.gov API. Registry records can be stale or incomplete; verify details in the official record.",
    ),
    SourceCatalogEntry(
        id="anzctr",
        name="ANZCTR",
        operator="Australian New Zealand Clinical Trials Registry",
        status="planned",
        default_selected=False,
        official_url="https://www.anzctr.org.au/",
        limitations="Planned connector. Use the official registry until this source is validated.",
    ),
    SourceCatalogEntry(
        id="who_ictrp",
        name="WHO ICTRP",
        operator="World Health Organization",
        status="planned",
        default_selected=False,
        official_url="https://trialsearch.who.int/",
        limitations="Broad aggregator. Access terms and deduplication rules require review before product use.",
    ),
    SourceCatalogEntry(
        id="eu_ctis",
        name="EU CTIS / EU Clinical Trials",
        operator="European Medicines Agency",
        status="planned",
        default_selected=False,
        official_url="https://euclinicaltrials.eu/",
        limitations="Planned connector for EU/EEA trial records and location views.",
    ),
    SourceCatalogEntry(
        id="jprn",
        name="Japan Primary Registries Network",
        operator="Japan registry network",
        status="external_link_only",
        default_selected=False,
        official_url="https://rctportal.niph.go.jp/en/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
    SourceCatalogEntry(
        id="chictr",
        name="Chinese Clinical Trial Registry",
        operator="ChiCTR",
        status="external_link_only",
        default_selected=False,
        official_url="https://www.chictr.org.cn/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
    SourceCatalogEntry(
        id="ctri",
        name="Clinical Trials Registry - India",
        operator="Indian Council of Medical Research",
        status="external_link_only",
        default_selected=False,
        official_url="https://ctri.nic.in/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
    SourceCatalogEntry(
        id="drks",
        name="German Clinical Trials Register",
        operator="DRKS",
        status="external_link_only",
        default_selected=False,
        official_url="https://drks.de/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
    SourceCatalogEntry(
        id="rebec",
        name="Brazilian Clinical Trials Registry",
        operator="ReBEC",
        status="external_link_only",
        default_selected=False,
        official_url="https://ensaiosclinicos.gov.br/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
    SourceCatalogEntry(
        id="cris",
        name="Clinical Research Information Service",
        operator="Korea Disease Control and Prevention Agency",
        status="external_link_only",
        default_selected=False,
        official_url="https://cris.nih.go.kr/",
        limitations="Shown as an official source to check manually until a connector is validated.",
    ),
)


def list_sources() -> list[dict[str, object]]:
    return [entry.to_dict() for entry in SOURCE_CATALOG]


def source_by_id(source_id: str) -> SourceCatalogEntry | None:
    return next((entry for entry in SOURCE_CATALOG if entry.id == source_id), None)

