"""Экспорт, шаблон и импорт прайса услуг в Excel (openpyxl)."""

import logging
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import Service

logger = logging.getLogger(__name__)

HEADERS = ["Название", "Цена", "Себестоимость", "Длительность, мин", "Активна"]
MAX_MONEY = Decimal("10000000.00")
ZERO = Decimal("0.00")
MAX_HEADER_SCAN = 15
MAX_SKIP_DETAILS = 50

NAME_KEYS = ("название", "наименование", "услуга", "name", "service")
PRICE_KEYS = ("цена", "стоимость", "price")
COST_KEYS = ("себестоимость", "закупка", "расходники", "cost", "cost_price")
DURATION_KEYS = (
    "длительность",
    "длительность мин",
    "минуты",
    "время",
    "duration",
    "duration_minutes",
)
ACTIVE_KEYS = ("активна", "активность", "показывать", "active", "is_active")

CURRENCY_TOKENS = ("₽", "руб.", "руб", "р.", "мин.", "мин")
TRUE_TOKENS = {"да", "1", "true", "истина", "yes", "y", "активна", "+", "on"}
FALSE_TOKENS = {"нет", "0", "false", "ложь", "no", "n", "неактивна", "-", "off"}


def _build_workbook(services) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Услуги"
    sheet.append(HEADERS)

    for service in services:
        sheet.append(
            [
                service.name,
                float(service.price),
                float(service.cost_price),
                service.duration_minutes,
                "да" if service.is_active else "нет",
            ]
        )

    header_font = Font(bold=True, color="1E3A8A")
    header_fill = PatternFill(fill_type="solid", fgColor="EFF6FF")
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    sheet.row_dimensions[1].height = 24
    widths = {"A": 42, "B": 14, "C": 16, "D": 18, "E": 12}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    if sheet.max_row > 1:
        sheet.auto_filter.ref = f"A1:E{sheet.max_row}"

    for row in sheet.iter_rows(min_row=2, min_col=2, max_col=3):
        for cell in row:
            cell.number_format = "#,##0.00"

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def export_workbook(owner) -> BytesIO:
    return _build_workbook(Service.objects.filter(owner=owner).order_by("name"))


def template_workbook() -> BytesIO:
    """Пустой файл с правильными колонками для заполнения."""
    return _build_workbook([])


def _normalize_header(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("\ufeff", "")
    for token in CURRENCY_TOKENS:
        text = text.replace(token, " ")
    text = " ".join(text.split())
    return text.strip(" .,:;")


def _column_index(header, keys) -> int | None:
    normalized = [_normalize_header(cell) for cell in header]
    for index, title in enumerate(normalized):
        if title in keys:
            return index
    for index, title in enumerate(normalized):
        if title and any(title.startswith(key) for key in keys):
            return index
    return None


def _layout_from_header(header) -> dict:
    return {
        "name": _column_index(header, NAME_KEYS),
        "price": _column_index(header, PRICE_KEYS),
        "cost": _column_index(header, COST_KEYS),
        "duration": _column_index(header, DURATION_KEYS),
        "active": _column_index(header, ACTIVE_KEYS),
    }


def _row_is_empty(row) -> bool:
    if row is None:
        return True
    for cell in row:
        if cell is None:
            continue
        if str(cell).strip():
            return False
    return True


def _looks_like_header(row) -> bool:
    layout = _layout_from_header(row)
    return layout["name"] is not None and layout["price"] is not None


def _reset_dimensions(sheet) -> None:
    reset = getattr(sheet, "reset_dimensions", None)
    if callable(reset):
        reset()


def _find_header(sheet):
    rows = sheet.iter_rows(min_row=1, max_row=MAX_HEADER_SCAN, values_only=True)
    for number, row in enumerate(rows, start=1):
        if _row_is_empty(row):
            continue
        if _looks_like_header(row):
            return number, _layout_from_header(row)
    return None, None


def _data_rows_after_header(sheet, header_row: int) -> int:
    count = 0
    rows = sheet.iter_rows(
        min_row=header_row + 1,
        max_row=header_row + MAX_HEADER_SCAN,
        values_only=True,
    )
    for row in rows:
        if not _row_is_empty(row):
            count += 1
    return count


def _pick_sheet(workbook):
    candidates = []
    for sheet in workbook.worksheets:
        _reset_dimensions(sheet)
        header_row, layout = _find_header(sheet)
        if header_row is not None and layout is not None:
            candidates.append(
                (_data_rows_after_header(sheet, header_row), sheet, header_row, layout)
            )

    for score, sheet, header_row, layout in candidates:
        if score > 0:
            return sheet, header_row, layout
    if candidates:
        _, sheet, header_row, layout = candidates[0]
        return sheet, header_row, layout

    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(min_row=1, max_row=MAX_HEADER_SCAN, values_only=True):
            if not _row_is_empty(row):
                return sheet, None, None

    return workbook.active, None, None


def _to_decimal(value) -> Decimal:
    """Число из ячейки: поддерживает 1 234,56, 1234.56, «100 ₽»."""
    if isinstance(value, bool):
        raise InvalidOperation
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            raise InvalidOperation
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if value is None:
        raise InvalidOperation

    text = str(value).strip().lower()
    if not text:
        raise InvalidOperation

    for token in CURRENCY_TOKENS:
        text = text.replace(token, "")
    text = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not text:
        raise InvalidOperation

    if text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + "." + tail

    return Decimal(text).quantize(Decimal("0.01"))


def _cell(row, index):
    if index is None or index >= len(row):
        return None
    return row[index]


def _parse_duration(value) -> int | None:
    """Пустая ячейка — 60 минут; некорректная — None (строка пропускается)."""
    if value is None or not str(value).strip():
        return 60
    try:
        number = _to_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number < 1 or number > 1440:
        return None
    return int(number)


def _parse_active(value, default: bool = True) -> bool:
    if value is None or not str(value).strip():
        return default
    text = str(value).strip().casefold()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    return default


def import_workbook(file_obj, owner) -> dict:
    """Импорт прайса мастера. Обновляет совпадения по названию, создаёт новые."""
    workbook = load_workbook(file_obj, data_only=True, read_only=True)
    created = updated = skipped = total = 0
    skipped_rows = []

    def skip(row_number: int, name: str, reason: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(skipped_rows) < MAX_SKIP_DETAILS:
            skipped_rows.append(
                {"row": row_number, "name": name or "—", "reason": reason}
            )
        logger.info(
            "Импорт услуг: строка %s (%s) пропущена: %s",
            row_number,
            name or "—",
            reason,
        )

    try:
        sheet, header_row, layout = _pick_sheet(workbook)
        if layout is None:
            layout = {
                "name": 0,
                "price": 1,
                "cost": 2,
                "duration": 3,
                "active": 4,
            }

        start_row = 1 if header_row is None else header_row + 1
        rows = sheet.iter_rows(min_row=start_row, values_only=True)

        existing_services = {
            service.name.strip().casefold(): service
            for service in Service.objects.filter(owner=owner)
        }

        for offset, row in enumerate(rows):
            row_number = start_row + offset
            if _row_is_empty(row):
                continue

            total += 1

            raw_name = _cell(row, layout["name"])
            name = str(raw_name or "").strip()
            if not name:
                skip(row_number, "", "пустое название")
                continue
            if len(name) > 160:
                skip(row_number, name[:60], "название длиннее 160 символов")
                continue

            try:
                price = _to_decimal(_cell(row, layout["price"]))
            except (InvalidOperation, TypeError, ValueError):
                skip(row_number, name, "цена не число")
                continue
            if price < 0 or price > MAX_MONEY:
                skip(row_number, name, "цена вне допустимого диапазона")
                continue

            cost = None
            raw_cost = _cell(row, layout["cost"])
            if raw_cost is not None and str(raw_cost).strip():
                try:
                    cost = _to_decimal(raw_cost)
                except (InvalidOperation, TypeError, ValueError):
                    skip(row_number, name, "себестоимость не число")
                    continue
                if cost < 0 or cost > MAX_MONEY:
                    skip(row_number, name, "себестоимость вне допустимого диапазона")
                    continue

            duration = _parse_duration(_cell(row, layout["duration"]))
            if duration is None:
                skip(row_number, name, "длительность должна быть от 1 до 1440 минут")
                continue

            active = _parse_active(_cell(row, layout["active"]), default=True)

            existing = existing_services.get(name.casefold())
            try:
                if existing:
                    changed = []
                    if existing.price != price:
                        existing.price = price
                        changed.append("price")
                    if cost is not None and existing.cost_price != cost:
                        existing.cost_price = cost
                        changed.append("cost_price")
                    if existing.duration_minutes != duration:
                        existing.duration_minutes = duration
                        changed.append("duration_minutes")
                    if existing.is_active != active:
                        existing.is_active = active
                        changed.append("is_active")

                    if changed:
                        existing.save(update_fields=[*changed, "updated_at"])
                        updated += 1
                    else:
                        skip(row_number, name, "без изменений")
                else:
                    service = Service.objects.create(
                        owner=owner,
                        name=name,
                        price=price,
                        cost_price=cost if cost is not None else ZERO,
                        duration_minutes=duration,
                        is_active=active,
                    )
                    existing_services[name.casefold()] = service
                    created += 1
            except Exception as error:  # noqa: BLE001 - одна строка не должна ломать импорт
                logger.exception("Импорт услуг: ошибка строки %s", row_number)
                skip(row_number, name, f"ошибка сохранения: {error}")
    finally:
        workbook.close()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": total,
        "skipped_rows": skipped_rows,
    }
