from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TextIO


GPS_CSV_COLUMNS = ("time_stamp", "lat", "lon", "alt", "alt_mode")
GPS_CSV_LEGACY_COLUMNS = GPS_CSV_COLUMNS[:4]
GPS_CSV_HEADER = ",".join(GPS_CSV_COLUMNS)


class GpsCsvSchemaError(ValueError):
    pass


def _schema_error(columns: Sequence[str] | None) -> GpsCsvSchemaError:
    actual = ",".join(columns or ()) or "<empty>"
    return GpsCsvSchemaError(
        f"gps.csv header must be {GPS_CSV_HEADER}; got {actual}"
    )


def _read_header(handle) -> list[str] | None:
    try:
        return next(csv.reader(handle, strict=True), None)
    except csv.Error as exc:
        raise GpsCsvSchemaError(f"gps.csv header is invalid: {exc}") from exc


def _validate_header(columns: Sequence[str] | None) -> None:
    if tuple(columns or ()) != GPS_CSV_COLUMNS:
        raise _schema_error(columns)


def validate_gps_csv(path: Path | str) -> None:
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            _validate_header(_read_header(handle))
    except UnicodeDecodeError as exc:
        raise GpsCsvSchemaError("gps.csv must use UTF-8 encoding") from exc


def validate_gps_csv_bytes(data: bytes) -> None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GpsCsvSchemaError("gps.csv must use UTF-8 encoding") from exc
    _validate_header(_read_header(io.StringIO(text, newline="")))


def ensure_gps_csv(path: Path | str) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and csv_path.stat().st_size:
        validate_gps_csv(csv_path)
        return
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(GPS_CSV_COLUMNS)


def _end_line(csv_path: Path) -> None:
    if not csv_path.stat().st_size:
        return
    with csv_path.open("rb") as handle:
        handle.seek(-1, 2)
        last = handle.read(1)
    if last not in {b"\n", b"\r"}:
        with csv_path.open("ab") as handle:
            handle.write(b"\n")


@contextmanager
def open_gps_csv_for_append(path: Path | str) -> Iterator[TextIO]:
    csv_path = Path(path)
    ensure_gps_csv(csv_path)
    _end_line(csv_path)
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        yield handle


def append_gps_row(path: Path | str, row: Iterable[object]) -> None:
    values = list(row)
    if len(values) != len(GPS_CSV_COLUMNS):
        raise ValueError(f"gps.csv row must contain {len(GPS_CSV_COLUMNS)} values")
    with open_gps_csv_for_append(path) as handle:
        csv.writer(handle).writerow(values)
