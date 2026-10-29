import importlib
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('K2PH_DB', str(tmp_path / 'test.db'))
    monkeypatch.setenv('K2PH_UPLOADS', str(tmp_path / 'uploads'))
    for k in ('LLM_API_URL', 'LLM_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    import app as k2
    k2 = importlib.reload(k2)
    return k2.app.test_client()
