from datetime import date

from app.core.utils import phone_variants, normalize_phone, due_date_for, add_months, brl
from app.services.bot import detect_intent


def test_phone_variants_nono_digito():
    assert set(phone_variants("5511988887777")) == {"5511988887777", "551188887777"}
    assert set(phone_variants("551188887777")) == {"5511988887777", "551188887777"}
    assert normalize_phone("+55 (92) 99999-8888") == "5592999998888"
    assert normalize_phone("92999998888") == "5592999998888"


def test_due_date_mes_curto():
    assert due_date_for(2026, 2, 31) == date(2026, 2, 28)
    assert due_date_for(2028, 2, 30) == date(2028, 2, 29)
    assert due_date_for(2026, 4, 31) == date(2026, 4, 30)
    assert add_months(2026, 12, 1) == (2027, 1)


def test_brl():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(160) == "R$ 160,00"


def test_intents():
    assert detect_intent("quero o pix") == "pix"
    assert detect_intent("1") == "pix"
    assert detect_intent("MENU_STATUS") == "status"
    assert detect_intent("estou em dia?") == "status"
    assert detect_intent("Falar com professor") == "human"
    assert detect_intent("Já paguei") == "paid"
    assert detect_intent("oi") == "menu"
