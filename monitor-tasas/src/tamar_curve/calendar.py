"""Bank-business-day handling for contractual TAMAR fixing windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping


class CalendarIncompleteError(ValueError):
    """Raised instead of silently estimating an unapproved bank calendar."""


def _gregorian_easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the Meeus/Jones/Butcher algorithm."""

    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _move_transferable_holiday(original: date) -> date:
    """Apply the deterministic weekday transfer rule from Law 27.399, art. 6."""

    if original.weekday() in (1, 2):  # Tuesday or Wednesday: previous Monday.
        return original - timedelta(days=original.weekday())
    if original.weekday() in (3, 4):  # Thursday or Friday: following Monday.
        return original + timedelta(days=7 - original.weekday())
    return original


def estimate_argentine_national_holidays(year: int) -> dict[date, str]:
    """Estimate statutory Argentine national holidays for a year.

    This is a fallback when BCRA has not published its bank-holiday table. It
    covers the national holidays and the deterministic transfers in Law 27.399;
    it intentionally excludes annually decreed tourism days and discretionary
    weekend transfers, which are not knowable ahead of their publication.
    """

    easter = _gregorian_easter_sunday(year)
    holidays = {
        date(year, 1, 1): "Año Nuevo",
        easter - timedelta(days=48): "Carnaval",
        easter - timedelta(days=47): "Carnaval",
        date(year, 3, 24): "Día Nacional de la Memoria por la Verdad y la Justicia",
        easter - timedelta(days=2): "Viernes Santo",
        date(year, 4, 2): "Día del Veterano y de los Caídos en la Guerra de Malvinas",
        date(year, 5, 1): "Día del Trabajo",
        date(year, 5, 25): "Día de la Revolución de Mayo",
        date(year, 6, 20): "Paso a la Inmortalidad del General Manuel Belgrano",
        date(year, 7, 9): "Día de la Independencia",
        date(year, 12, 8): "Día de la Inmaculada Concepción de María",
        date(year, 12, 25): "Navidad",
    }
    for month, day, name in (
        (6, 17, "Paso a la Inmortalidad del General Martín Miguel de Güemes"),
        (8, 17, "Paso a la Inmortalidad del General José de San Martín"),
        (10, 12, "Día del Respeto a la Diversidad Cultural"),
        (11, 20, "Día de la Soberanía Nacional"),
    ):
        holidays[_move_transferable_holiday(date(year, month, day))] = name
    return holidays


@dataclass(frozen=True)
class BankBusinessCalendar:
    """Observed past fixing dates plus official BCRA holiday calendars ahead."""

    observed_fixing_dates: frozenset[date]
    fixing_as_of: date
    holidays_by_year: Mapping[int, frozenset[date]]

    def is_business_day(self, candidate: date) -> bool:
        if candidate <= self.fixing_as_of:
            return candidate in self.observed_fixing_dates
        try:
            holidays = self.holidays_by_year[candidate.year]
        except KeyError as exc:
            raise CalendarIncompleteError(
                f"Falta el calendario oficial de feriados bancarios BCRA para {candidate.year}"
            ) from exc
        return candidate.weekday() < 5 and candidate not in holidays

    def shift(self, starting_date: date, business_days: int) -> date:
        """Excel WORKDAY-style shift: the starting date is not counted."""

        if business_days == 0:
            return starting_date
        step = 1 if business_days > 0 else -1
        remaining = abs(business_days)
        cursor = starting_date
        while remaining:
            cursor += timedelta(days=step)
            if self.is_business_day(cursor):
                remaining -= 1
        return cursor

    def business_days_inclusive(self, start: date, end: date) -> list[date]:
        if end < start:
            raise ValueError(f"Ventana TAMAR invertida: {start.isoformat()} > {end.isoformat()}")
        days: list[date] = []
        cursor = start
        while cursor <= end:
            if self.is_business_day(cursor):
                days.append(cursor)
            cursor += timedelta(days=1)
        return days


def make_bank_calendar(
    fixing_dates: Iterable[date],
    holidays_by_year: Mapping[int, Iterable[date]],
) -> BankBusinessCalendar:
    observed = frozenset(fixing_dates)
    if not observed:
        raise ValueError("No hay fechas observadas de la serie TAMAR")
    return BankBusinessCalendar(
        observed_fixing_dates=observed,
        fixing_as_of=max(observed),
        holidays_by_year={year: frozenset(days) for year, days in holidays_by_year.items()},
    )
