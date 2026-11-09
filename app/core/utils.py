"""Funções utilitárias: telefone, datas e fuso horário."""
import calendar
import re
from datetime import date, datetime
from typing import List
from zoneinfo import ZoneInfo

from app.core.config import settings


def tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def today_local() -> date:
    """Data de hoje no fuso da academia (o servidor pode estar em UTC)."""
    return datetime.now(tz()).date()


def due_date_for(year: int, month: int, due_day: int) -> date:
    """Dia de vencimento no mês; se o dia não existir (ex.: 31/02), usa o último dia do mês."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, last_day))


def add_months(year: int, month: int, n: int):
    idx = year * 12 + (month - 1) + n
    return idx // 12, idx % 12 + 1


def normalize_phone(phone: str) -> str:
    """Remove tudo que não é dígito. Números brasileiros sem DDI (10/11 dígitos) ganham o 55."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def phone_variants(phone: str) -> List[str]:
    """
    Variações de um número brasileiro com e sem o nono dígito.

    O WhatsApp costuma entregar o 'wa_id' de celulares antigos SEM o 9
    (ex.: 551188887777), enquanto o cadastro costuma ter COM o 9
    (5511988887777). Sem esse tratamento o bot não reconhece o aluno.
    """
    p = normalize_phone(phone)
    variants = {p}
    if p.startswith("55"):
        ddd, local = p[2:4], p[4:]
        if len(local) == 9 and local.startswith("9"):
            variants.add(f"55{ddd}{local[1:]}")
        elif len(local) == 8 and local[0] in "6789":
            variants.add(f"55{ddd}9{local}")
    return sorted(variants)


def brl(value: float) -> str:
    """Formata valor em reais: 1234.5 -> 'R$ 1.234,50'."""
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"
