"""Экспорт операций в CSV и Excel (ТЗ п. 3.12).

Экспорт бесплатный и без ограничений. Файл отправляется в MAX как
вложение ``file`` (через ``POST /uploads``).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from decimal import Decimal

from bot.constants import SOURCE_LABELS, TRANSACTION_TYPE_LABELS
from bot.db import Database

logger = logging.getLogger(__name__)

CSV_HEADER = (
    "ID",
    "Тип",
    "Сумма",
    "Валюта",
    "Категория",
    "Дата",
    "Комментарий",
    "Источник",
    "Создана",
)


def _rows(db_rows: list) -> list[tuple]:
    """Преобразовать записи БД в строки экспорта."""
    result = []
    for row in db_rows:
        result.append(
            (
                row["id"],
                TRANSACTION_TYPE_LABELS.get(row["type"], row["type"]),
                row["amount"],
                row["currency"],
                row["category_name"] or "Без категории",
                row["transaction_date"].isoformat(),
                row["comment"] or "",
                SOURCE_LABELS.get(row["source"], row["source"]),
                row["created_at"].strftime("%d.%m.%Y %H:%M") if row["created_at"] else "",
            )
        )
    return result


class ExportService:
    """Выгрузка операций пользователя."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def _fetch(self, user_id: int, date_from: date | None, date_to: date | None) -> list:
        return await self._db.fetch(
            """
            SELECT t.id, t.type, t.amount, t.currency, c.name AS category_name,
                   t.transaction_date, t.comment, t.source, t.created_at
              FROM transactions t
              LEFT JOIN categories c ON c.id = t.category_id
             WHERE t.user_id = $1
               AND ($2::date IS NULL OR t.transaction_date >= $2)
               AND ($3::date IS NULL OR t.transaction_date <= $3)
             ORDER BY t.transaction_date, t.created_at
            """,
            user_id,
            date_from,
            date_to,
        )

    async def to_csv(
        self, user_id: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> tuple[bytes, int]:
        """CSV-файл (UTF-8 с BOM, чтобы Excel открывал кириллицу корректно)."""
        rows = _rows(list(await self._fetch(user_id, date_from, date_to)))
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow(
                [str(value) if isinstance(value, Decimal) else value for value in row]
            )
        content = "\ufeff" + buffer.getvalue()
        return content.encode("utf-8"), len(rows)

    async def to_excel(
        self, user_id: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> tuple[bytes, int]:
        """Excel-файл (.xlsx) через openpyxl."""
        from openpyxl import Workbook
        from openpyxl.styles import Font

        records = list(await self._fetch(user_id, date_from, date_to))
        rows = _rows(records)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Операции"
        sheet.append(list(CSV_HEADER))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append([float(value) if isinstance(value, Decimal) else value for value in row])

        widths = (8, 10, 14, 8, 24, 12, 40, 12, 18)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
        sheet.freeze_panes = "A2"

        # Итоги: доходы, расходы, баланс.
        total_income = sum(
            (record["amount"] for record in records if record["type"] == "income"),
            start=Decimal("0.00"),
        )
        total_expense = sum(
            (record["amount"] for record in records if record["type"] == "expense"),
            start=Decimal("0.00"),
        )
        summary = workbook.create_sheet("Итоги")
        summary.append(["Показатель", "Сумма"])
        summary.append(["Доходы", float(total_income)])
        summary.append(["Расходы", float(total_expense)])
        summary.append(["Баланс", float(total_income - total_expense)])
        summary.append(["Операций", len(records)])
        for cell in summary[1]:
            cell.font = Font(bold=True)

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue(), len(records)


def export_filename(ext: str, date_from: date | None = None, date_to: date | None = None) -> str:
    """Имя файла вида ``wallet_2026-11-01_2026-11-06.csv``."""
    today = date.today().isoformat()
    if date_from and date_to:
        return f"wallet_{date_from.isoformat()}_{date_to.isoformat()}.{ext}"
    return f"wallet_{today}.{ext}"
