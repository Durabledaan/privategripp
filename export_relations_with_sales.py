#!/usr/bin/env python3
"""Maak een export van relaties met geaccordeerde offertes én opdrachten.

Het script kan werken met lokale CSV-bestanden *of* rechtstreeks met de
Gripp-API. Daarmee kun je een herhaalbare export automatiseren zonder handmatig
CSV's te genereren. Voor API-gebruik heb je een API-token nodig zoals beschreven
in de Gripp documentatie (``https://api.gripp.com/public/api3.php``).

Voorbeelden::

    # Gebruik van bestaande CSV-exports
    python export_relations_with_sales.py \
        --relations relaties.csv \
        --offers offertes.csv \
        --assignments opdrachten.csv \
        --output relaties_met_sales.csv

    # Rechtstreeks via de API
    python export_relations_with_sales.py \
        --api-token ${GRIPP_API_TOKEN} \
        --output relaties_met_sales.csv

Wanneer zowel CSV-bestanden als een API-token worden opgegeven, krijgen de
bestanden voorrang. Zo kun je bijvoorbeeld een lokaal bestand met relaties
gebruiken en de gekoppelde offertes via de API ophalen.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

try:
    input  # type: ignore[name-defined]
except NameError:  # pragma: no cover - voor typecheckers
    from builtins import input

try:  # pragma: no cover - optionele dependency
    import requests
except ModuleNotFoundError:  # pragma: no cover - wordt later afgehandeld
    requests = None  # type: ignore[assignment]


@dataclass
class OfferMatch:
    """Information about accepted offers linked to a relation."""

    relation_id: str
    offer_ids: List[str]


@dataclass
class AssignmentMatch:
    """Information about assignments linked to a relation."""

    relation_id: str
    assignment_ids: List[str]


class GrippAPIError(RuntimeError):
    """Raised when the Gripp API returns an error or unexpected payload."""


class GrippClient:
    """Kleine helper om lijsten via de Gripp API op te halen."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.gripp.com/public/api3.php",
        timeout: int = 30,
        page_size: int = 250,
        limit_param: Optional[str] = "limit",
        offset_param: Optional[str] = "offset",
    ) -> None:
        if requests is None:
            raise ModuleNotFoundError(
                "Voor API-gebruik is het pakket 'requests' vereist. Installeer het met 'python -m pip install requests'."
            )
        self._token = token
        self._base_url = base_url
        self._timeout = timeout
        self._page_size = page_size
        self._limit_param = limit_param
        self._offset_param = offset_param
        self._session = requests.Session()

    def call(self, function: str, **params: object) -> Mapping[str, object]:
        payload = {"token": self._token, "function": function, **params}
        response = self._session.post(self._base_url, json=payload, timeout=self._timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - defensief
            raise GrippAPIError(f"HTTP fout bij functie '{function}': {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensief
            raise GrippAPIError(
                f"Kon JSON-respons niet parsen voor functie '{function}': {response.text[:200]}"
            ) from exc

        if isinstance(data, Mapping) and data.get("success") is False:
            message = data.get("error") or data.get("message") or "Onbekende fout"
            raise GrippAPIError(f"Gripp API fout ({function}): {message}")
        return data

    def iter_collection(
        self,
        function: str,
        data_path: Sequence[str] | None = None,
        **params: object,
    ) -> Iterator[Mapping[str, object]]:
        page = 1
        path = list(data_path or [])
        while True:
            payload = dict(params)
            if self._limit_param:
                payload.setdefault(self._limit_param, self._page_size)
            if self._offset_param:
                if self._offset_param.lower() == "page":
                    payload.setdefault(self._offset_param, page)
                else:
                    payload.setdefault(self._offset_param, (page - 1) * self._page_size)
            result = self.call(function, **payload)

            records: Optional[Iterable[Mapping[str, object]]] = None
            if isinstance(result, Mapping):
                if path:
                    records = _extract_from_path(result, path)
                else:
                    if isinstance(result.get("data"), list):
                        records = result["data"]
                    elif isinstance(result.get("items"), list):
                        records = result["items"]
                    elif isinstance(result.get("result"), list):
                        records = result["result"]
                    else:
                        # Zoek naar de eerste lijstwaarde in de payload.
                        for value in result.values():
                            if isinstance(value, list) and value and isinstance(value[0], Mapping):
                                records = value
                                break

            if not records:
                break

            fetched = 0
            for row in records:
                fetched += 1
                yield row

            if self._limit_param is None or self._offset_param is None:
                break
            if fetched < self._page_size:
                break
            page += 1

    def preview_collection(
        self,
        function: str,
        data_path: Sequence[str] | None = None,
        **params: object,
    ) -> Tuple[Optional[Mapping[str, object]], Mapping[str, object]]:
        """Retourneer een voorbeeldrecord en de volledige API-respons."""

        result = self.call(function, **params)

        records: Optional[Iterable[Mapping[str, object]]] = None
        if isinstance(result, Mapping):
            if data_path:
                records = _extract_from_path(result, list(data_path))
            else:
                if isinstance(result.get("data"), list):
                    records = result["data"]
                elif isinstance(result.get("items"), list):
                    records = result["items"]
                elif isinstance(result.get("result"), list):
                    records = result["result"]
                else:
                    for value in result.values():
                        if isinstance(value, list) and value and isinstance(value[0], Mapping):
                            records = value
                            break

        first_record: Optional[Mapping[str, object]] = None
        if records:
            for row in records:
                if isinstance(row, Mapping):
                    first_record = row
                    break

        return first_record, result


def _extract_from_path(
    payload: Mapping[str, object], path: Sequence[str]
) -> Optional[Iterable[Mapping[str, object]]]:
    current: object = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, list):
        list_values = [item for item in current if isinstance(item, Mapping)]
        if not list_values:
            return None
        return list_values
    if isinstance(current, Mapping):
        for value in current.values():
            if isinstance(value, list) and value and isinstance(value[0], Mapping):
                return value
    return None


def read_csv(path: Path) -> Iterable[Dict[str, str]]:
    """Yield rows from *path* as dictionaries."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Bestand '{path}' bevat geen kolomkoppen.")
        reader.fieldnames = [field.strip() for field in reader.fieldnames]
        for row in reader:
            yield {key.strip(): value for key, value in row.items()}


def index_relations(
    rows: Iterable[Mapping[str, object]], relation_id_field: str
) -> Dict[str, Dict[str, str]]:
    """Build an index of relations by their identifier."""

    relations: Dict[str, Dict[str, str]] = {}
    for row in rows:
        relation_id = str(row.get(relation_id_field) or "").strip()
        if not relation_id:
            raise KeyError(
                f"Kolom '{relation_id_field}' ontbreekt of is leeg in een rij van de relaties-export."
            )
        if relation_id in relations:
            raise ValueError(
                f"Dubbele relation_id '{relation_id}' gevonden. Controleer je export of gebruik een unieker veld."
            )
        relations[relation_id] = {key: _normalise_value(value) for key, value in row.items()}
    return relations


def _normalise_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def find_accepted_offers(
    rows: Iterable[Mapping[str, object]],
    relation_id_field: str,
    offer_id_field: str,
    status_field: str,
    accepted_statuses: Sequence[str],
) -> Dict[str, OfferMatch]:
    """Return a mapping of relation id to accepted offers."""

    accepted: Dict[str, OfferMatch] = {}
    accepted_status_set = {status.lower() for status in accepted_statuses}
    for row in rows:
        relation_id = str(row.get(relation_id_field) or "").strip()
        if not relation_id:
            continue
        status = str(row.get(status_field) or "").strip().lower()
        if status not in accepted_status_set:
            continue
        offer_id = str(row.get(offer_id_field) or "").strip()
        match = accepted.setdefault(relation_id, OfferMatch(relation_id, []))
        if offer_id:
            match.offer_ids.append(offer_id)
    return accepted


def find_assignments(
    rows: Iterable[Mapping[str, object]], relation_id_field: str, assignment_id_field: str
) -> Dict[str, AssignmentMatch]:
    """Return a mapping of relation id to assignments."""

    assignments: Dict[str, AssignmentMatch] = {}
    for row in rows:
        relation_id = str(row.get(relation_id_field) or "").strip()
        if not relation_id:
            continue
        assignment_id = str(row.get(assignment_id_field) or "").strip()
        match = assignments.setdefault(relation_id, AssignmentMatch(relation_id, []))
        if assignment_id:
            match.assignment_ids.append(assignment_id)
    return assignments


def filter_relations(
    relations: Mapping[str, Mapping[str, str]],
    offers: Mapping[str, OfferMatch],
    assignments: Mapping[str, AssignmentMatch],
) -> List[Dict[str, str]]:
    """Return relations that have both accepted offers and assignments."""

    matched_relations: List[Dict[str, str]] = []
    for relation_id, relation_row in relations.items():
        if relation_id in offers and relation_id in assignments:
            offer_ids = ", ".join(offers[relation_id].offer_ids)
            assignment_ids = ", ".join(assignments[relation_id].assignment_ids)
            row_with_meta = dict(relation_row)
            row_with_meta["Aantal geaccordeerde offertes"] = str(len(offers[relation_id].offer_ids))
            row_with_meta["Offerte-ID's"] = offer_ids
            row_with_meta["Aantal opdrachten"] = str(len(assignments[relation_id].assignment_ids))
            row_with_meta["Opdracht-ID's"] = assignment_ids
            matched_relations.append(row_with_meta)
    return matched_relations


def write_csv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    """Write *rows* to *path* preserving the column order of the first row."""

    if not rows:
        raise ValueError("Er zijn geen overeenkomende relaties gevonden; outputbestand wordt niet aangemaakt.")

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_key_value_pairs(pairs: Sequence[str]) -> Dict[str, str]:
    filters: Dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Filter '{item}' heeft geen '=' teken.")
        key, value = item.split("=", 1)
        filters[key] = value
    return filters


def _parse_data_path(value: Optional[str]) -> Sequence[str] | None:
    if not value:
        return None
    parts = [segment.strip() for segment in value.split(".") if segment.strip()]
    return parts or None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relations", type=Path, help="CSV-bestand met relaties.")
    parser.add_argument("--offers", type=Path, help="CSV-bestand met offertes.")
    parser.add_argument("--assignments", type=Path, help="CSV-bestand met opdrachten.")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Pad naar het CSV-bestand waarin de gefilterde relaties worden opgeslagen.",
    )
    parser.add_argument(
        "--relations-id-field",
        default="Relatie ID",
        help="Kolomnaam in het relaties-bestand die de unieke identifier bevat.",
    )
    parser.add_argument(
        "--offer-relation-field",
        default="Relatie ID",
        help="Kolomnaam in het offertes-bestand die verwijst naar de relatie.",
    )
    parser.add_argument(
        "--offer-id-field",
        default="Offerte ID",
        help="Kolomnaam in het offertes-bestand met de offerte identifier.",
    )
    parser.add_argument(
        "--offer-status-field",
        default="Status",
        help="Kolomnaam in het offertes-bestand die de status bevat.",
    )
    parser.add_argument(
        "--accepted-status",
        action="append",
        default=["Geaccordeerd"],
        help=(
            "Een statuswaarde die als geaccordeerd moet worden beschouwd. "
            "Je kunt deze optie meerdere keren opgeven. Standaard alleen 'Geaccordeerd'."
        ),
    )
    parser.add_argument(
        "--assignment-relation-field",
        default="Relatie ID",
        help="Kolomnaam in het opdrachten-bestand die verwijst naar de relatie.",
    )
    parser.add_argument(
        "--assignment-id-field",
        default="Opdracht ID",
        help="Kolomnaam in het opdrachten-bestand met de opdracht identifier.",
    )
    parser.add_argument(
        "--api-token",
        default=os.getenv("GRIPP_API_TOKEN"),
        help="Token voor de Gripp API. Wordt automatisch opgehaald uit de omgeving wanneer niet opgegeven.",
    )
    parser.add_argument(
        "--api-base-url",
        default="https://api.gripp.com/public/api3.php",
        help="Basis-URL van de Gripp API.",
    )
    parser.add_argument(
        "--relations-function",
        default="relations.list",
        help="API-functie waarmee relaties worden opgehaald.",
    )
    parser.add_argument(
        "--offers-function",
        default="offers.list",
        help="API-functie waarmee offertes worden opgehaald.",
    )
    parser.add_argument(
        "--assignments-function",
        default="assignments.list",
        help="API-functie waarmee opdrachten worden opgehaald.",
    )
    parser.add_argument(
        "--api-filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra parameters die naar de API worden gestuurd (bijv. 'status=Actief'). Kan meerdere keren.",
    )
    parser.add_argument(
        "--relations-filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Filters die alleen op de API-aanroep voor relaties worden toegepast.",
    )
    parser.add_argument(
        "--offers-filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Filters die alleen op de API-aanroep voor offertes worden toegepast.",
    )
    parser.add_argument(
        "--assignments-filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Filters die alleen op de API-aanroep voor opdrachten worden toegepast.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=250,
        help="Aantal records per API-aanroep bij gebruik van de API.",
    )
    parser.add_argument(
        "--limit-param",
        default="limit",
        help="Parameternaam voor het maximum aantal records per API-aanroep (stel leeg in voor geen paginering).",
    )
    parser.add_argument(
        "--offset-param",
        default="offset",
        help="Parameternaam voor het startpunt van de volgende pagina (stel leeg in voor geen paginering).",
    )
    parser.add_argument(
        "--relations-data-path",
        help="JSON-pad (puntnotatie) naar de lijst met relaties in de API-respons.",
    )
    parser.add_argument(
        "--offers-data-path",
        help="JSON-pad (puntnotatie) naar de lijst met offertes in de API-respons.",
    )
    parser.add_argument(
        "--assignments-data-path",
        help="JSON-pad (puntnotatie) naar de lijst met opdrachten in de API-respons.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logniveau voor voortgangsmeldingen.",
    )
    parser.add_argument(
        "--wizard",
        action="store_true",
        help="Start een interactieve wizard om de juiste velden automatisch te selecteren (API vereist).",
    )
    return parser.parse_args(argv)


def load_rows(
    csv_path: Optional[Path],
    api_function: str,
    client: Optional[GrippClient],
    api_filters: Mapping[str, str],
    data_path: Sequence[str] | None,
) -> Iterable[Mapping[str, object]]:
    if csv_path:
        logging.info("Lees gegevens uit %s", csv_path)
        return list(read_csv(csv_path))
    if client is None:
        raise ValueError(
            "Geen CSV-pad opgegeven en geen API-token beschikbaar. Geef een bestand op of gebruik --api-token."
        )
    logging.info("Haal gegevens op via API-functie %s", api_function)
    return list(client.iter_collection(api_function, data_path=data_path, **api_filters))


def _suggest_field(sample: Mapping[str, object], candidates: Sequence[str], fallback: str) -> str:
    for candidate in candidates:
        if candidate in sample:
            return candidate
    return fallback


def _format_preview(record: Mapping[str, object]) -> str:
    preview_items = []
    for idx, (key, value) in enumerate(record.items()):
        if idx >= 10:
            preview_items.append("…")
            break
        preview_items.append(f"{key}={value!r}")
    return ", ".join(preview_items)


def _prompt(prompt: str, default: str) -> str:
    response = input(f"{prompt} [{default}]: ")
    response = response.strip()
    return response or default


def _prompt_data_path(name: str, raw_response: Mapping[str, object]) -> Sequence[str] | None:
    top_level_keys = ", ".join(raw_response.keys())
    print(f"Beschikbare top-level keys voor {name}: {top_level_keys or '(geen)'}")
    new_path = input(
        "Voer een JSON-pad in (bijv. data.items) om de lijst te bereiken of laat leeg om niets te wijzigen: "
    ).strip()
    if not new_path:
        return None
    return _parse_data_path(new_path)


def _wizard_configure_resource(
    client: GrippClient,
    name: str,
    function: str,
    data_path: Sequence[str] | None,
    filters: Mapping[str, str],
) -> Tuple[Sequence[str] | None, Optional[Mapping[str, object]], Mapping[str, object]]:
    current_path = data_path
    while True:
        sample, raw = client.preview_collection(function, data_path=current_path, **filters)
        if sample:
            print(f"\nVoorbeeldrecord voor {name}: {_format_preview(sample)}")
            return current_path, sample, raw
        print(
            f"\nKon geen records ophalen voor {name}. Controleer filters of pas het JSON-pad aan."
        )
        if not isinstance(raw, Mapping):
            raise GrippAPIError(f"Onverwachte API-respons voor {name}: {raw!r}")
        new_path = _prompt_data_path(name, raw)
        if new_path is None:
            return current_path, None, raw
        current_path = new_path


def run_wizard(
    args: argparse.Namespace,
    client: GrippClient,
    relations_filters: Mapping[str, str],
    offers_filters: Mapping[str, str],
    assignments_filters: Mapping[str, str],
    relations_path: Sequence[str] | None,
    offers_path: Sequence[str] | None,
    assignments_path: Sequence[str] | None,
) -> Tuple[Sequence[str] | None, Sequence[str] | None, Sequence[str] | None]:
    print("Start interactieve wizard. Druk op Ctrl+C om af te breken.\n")

    relations_path, relations_sample, _ = _wizard_configure_resource(
        client,
        "relaties",
        args.relations_function,
        relations_path,
        relations_filters,
    )
    if relations_sample:
        suggested_relation_id = _suggest_field(
            relations_sample,
            [
                "id",
                "relation_id",
                "relatie_id",
                "Relatie ID",
                "RelatieID",
            ],
            args.relations_id_field,
        )
        args.relations_id_field = _prompt(
            "Kolomnaam met unieke relatie-ID", suggested_relation_id
        )

    offers_path, offers_sample, _ = _wizard_configure_resource(
        client,
        "offertes",
        args.offers_function,
        offers_path,
        offers_filters,
    )
    if offers_sample:
        args.offer_id_field = _prompt(
            "Kolomnaam met offerte-ID",
            _suggest_field(
                offers_sample,
                ["id", "offer_id", "offerte_id", "Offerte ID", "OfferteID"],
                args.offer_id_field,
            ),
        )
        args.offer_relation_field = _prompt(
            "Kolomnaam met relatieverwijzing in offertes",
            _suggest_field(
                offers_sample,
                ["relation_id", "relatie_id", "Relatie ID", "RelatieID", "relation"],
                args.offer_relation_field,
            ),
        )
        args.offer_status_field = _prompt(
            "Kolomnaam met offertestatus",
            _suggest_field(
                offers_sample,
                ["status", "Status"],
                args.offer_status_field,
            ),
        )

    assignments_path, assignments_sample, _ = _wizard_configure_resource(
        client,
        "opdrachten",
        args.assignments_function,
        assignments_path,
        assignments_filters,
    )
    if assignments_sample:
        args.assignment_id_field = _prompt(
            "Kolomnaam met opdracht-ID",
            _suggest_field(
                assignments_sample,
                ["id", "assignment_id", "opdracht_id", "Opdracht ID", "OpdrachtID"],
                args.assignment_id_field,
            ),
        )
        args.assignment_relation_field = _prompt(
            "Kolomnaam met relatieverwijzing in opdrachten",
            _suggest_field(
                assignments_sample,
                ["relation_id", "relatie_id", "Relatie ID", "RelatieID", "relation"],
                args.assignment_relation_field,
            ),
        )

    if args.accepted_status:
        print(
            f"\nHuidige geaccordeerde statussen: {', '.join(args.accepted_status)}"
        )
    status_input = input(
        "Voer komma-gescheiden statussen in die als geaccordeerd tellen (leeg voor geen wijziging): "
    ).strip()
    if status_input:
        args.accepted_status = [
            status.strip() for status in status_input.split(",") if status.strip()
        ]

    print("\nSamenvatting configuratie:")
    print(f"  Relatie-ID kolom: {args.relations_id_field}")
    print(
        f"  Offerte-ID kolom: {args.offer_id_field}, relatiekolom: {args.offer_relation_field}, statuskolom: {args.offer_status_field}"
    )
    print(
        f"  Opdracht-ID kolom: {args.assignment_id_field}, relatiekolom: {args.assignment_relation_field}"
    )
    print(f"  Geaccordeerde statussen: {', '.join(args.accepted_status) or '(geen)'}")

    proceed = input("Doorgaan met export? (j/N): ").strip().lower()
    if proceed not in {"j", "ja", "y", "yes"}:
        raise SystemExit("Export afgebroken door gebruiker.")

    return relations_path, offers_path, assignments_path


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    api_filters = parse_key_value_pairs(args.api_filter)
    relations_filters = dict(api_filters)
    relations_filters.update(parse_key_value_pairs(args.relations_filter))
    offers_filters = dict(api_filters)
    offers_filters.update(parse_key_value_pairs(args.offers_filter))
    assignments_filters = dict(api_filters)
    assignments_filters.update(parse_key_value_pairs(args.assignments_filter))

    relations_path = _parse_data_path(args.relations_data_path)
    offers_path = _parse_data_path(args.offers_data_path)
    assignments_path = _parse_data_path(args.assignments_data_path)

    client: Optional[GrippClient] = None
    if any(path is None for path in (args.relations, args.offers, args.assignments)):
        if not args.api_token:
            raise ValueError(
                "Voor API-gebruik is een token vereist. Stel GRIPP_API_TOKEN in of gebruik --api-token."
            )
        client = GrippClient(
            args.api_token,
            base_url=args.api_base_url,
            page_size=args.page_size,
            limit_param=args.limit_param or None,
            offset_param=args.offset_param or None,
        )

    if args.wizard:
        if client is None:
            raise ValueError("De wizard kan alleen gebruikt worden met de Gripp API. Geef een API-token op.")
        relations_path, offers_path, assignments_path = run_wizard(
            args,
            client,
            relations_filters,
            offers_filters,
            assignments_filters,
            relations_path,
            offers_path,
            assignments_path,
        )

    relations_rows = load_rows(
        args.relations,
        args.relations_function,
        client,
        relations_filters,
        relations_path,
    )
    relations = index_relations(relations_rows, args.relations_id_field)

    offers_rows = load_rows(
        args.offers,
        args.offers_function,
        client,
        offers_filters,
        offers_path,
    )
    offers = find_accepted_offers(
        offers_rows,
        relation_id_field=args.offer_relation_field,
        offer_id_field=args.offer_id_field,
        status_field=args.offer_status_field,
        accepted_statuses=args.accepted_status,
    )

    assignments_rows = load_rows(
        args.assignments,
        args.assignments_function,
        client,
        assignments_filters,
        assignments_path,
    )
    assignments = find_assignments(
        assignments_rows,
        relation_id_field=args.assignment_relation_field,
        assignment_id_field=args.assignment_id_field,
    )

    filtered_relations = filter_relations(relations, offers, assignments)
    write_csv(args.output, filtered_relations)


if __name__ == "__main__":
    main()
