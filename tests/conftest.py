"""
Testes rodam 100% em modo simulação (sem chamar Meta nem Asaas), num banco SQLite temporário.
Rode com:  pytest -q
"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{os.path.join(_tmp, 'test.db')}",
    "WHATSAPP_TOKEN": "EAAG_SIMULATED_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID": "100000000000001",
    "WHATSAPP_APP_SECRET": "",
    "WHATSAPP_VERIFY_TOKEN": "verify-test",
    "ASAAS_API_KEY": "$aact_SIMULATED_KEY",
    "ASAAS_WEBHOOK_TOKEN": "",
    "ADMIN_API_KEY": "",
    "ADMIN_PHONE": "",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import init_db, SessionLocal, engine, Base  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    # Sem "with": não sobe o agendador nos testes
    return TestClient(app)
