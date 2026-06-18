"""TDD RED-phase tests for blocked_by feature.

All tests are expected to FAIL because the Python serialization and API
logic for blocked_by/is_blocked is not yet implemented. The blocked_by
column already exists in the DB schema (added ahead of the migration),
but _load_board, _item_by_id, POST, and PATCH do not read or write it.
"""

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).parent.parent
SERVER_PATH = REPO_ROOT / "amux-server.py"


@pytest.fixture(scope="module")
def amux_server():
    """Load amux-server.py as a module without running its HTTP server."""
    os.environ["AMUX_HOME"] = tempfile.mkdtemp(prefix="amux_test_")
    os.environ.setdefault("AMUX_AUTH_TOKEN", "none")
    spec = importlib.util.spec_from_file_location("amux_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None, f"could not load {SERVER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["amux_server"] = mod
    spec.loader.exec_module(mod)
    mod.AUTH_TOKEN = ""
    mod._S3_BUCKET = ""
    mod._GCAL_ID = ""
    return mod


@pytest.fixture
def db(amux_server):
    """Provide a temporary SQLite database with initialized schema and migrations."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    orig_db_path = amux_server._DB_PATH
    amux_server._DB_PATH = Path(db_path)

    # Reset thread-local connection
    if hasattr(amux_server._db_local, "conn"):
        delattr(amux_server._db_local, "conn")

    # Initialize schema and migrations
    amux_server._init_db()

    # Reset thread-local again so tests get fresh connection
    if hasattr(amux_server._db_local, "conn"):
        delattr(amux_server._db_local, "conn")

    yield db_path

    # Cleanup
    amux_server._DB_PATH = orig_db_path
    if hasattr(amux_server._db_local, "conn"):
        delattr(amux_server._db_local, "conn")
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def mock_handler(amux_server):
    """Factory for mock HTTP request handlers."""

    def _make(body=None, path="/", headers=None):
        handler = MagicMock()
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = headers or {}
        handler._read_body.return_value = body or {}

        handler._json_calls = []

        def capture_json(data, status=200):
            handler._json_calls.append((data, status))
            handler._resp_status = status

        handler._json.side_effect = capture_json
        handler._cors = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        # Bind _route_inner from CCHandler to our mock instance
        handler._route_inner = amux_server.CCHandler._route_inner.__get__(
            handler, type(handler)
        )

        return handler

    return _make


# ── Helpers ──────────────────────────────────────────────────────────────────


def _insert_item(db_path, **kwargs):
    """Insert an issue directly into the temp database."""
    defaults = {
        "id": "MP-1",
        "title": "Test item",
        "desc": "",
        "status": "todo",
        "session": None,
        "creator": "",
        "due": None,
        "created": 1234567890,
        "updated": 1234567890,
        "deleted": None,
        "owner_type": "human",
        "blocked_by": "",
    }
    defaults.update(kwargs)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(["?"] * len(defaults))
    conn.execute(
        f"INSERT INTO issues ({cols}) VALUES ({placeholders})", tuple(defaults.values())
    )
    conn.commit()
    conn.close()


def _get_db_item(db_path, item_id):
    """Fetch a single issue row directly from the temp database."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _reset_db_conn(amux_server):
    """Reset thread-local DB connection so get_db() creates a fresh one."""
    if hasattr(amux_server._db_local, "conn"):
        delattr(amux_server._db_local, "conn")


# ── Serialization tests ──────────────────────────────────────────────────────


def test_load_board_has_blocked_by_key(amux_server, db):
    """_load_board returns items with blocked_by key (list)."""
    _insert_item(db, id="MP-1", title="Test")
    _reset_db_conn(amux_server)

    items = amux_server._load_board(done_limit=0)
    assert len(items) == 1
    assert "blocked_by" in items[0]


def test_load_board_has_is_blocked_key(amux_server, db):
    """_load_board returns items with is_blocked key (bool)."""
    _insert_item(db, id="MP-1", title="Test")
    _reset_db_conn(amux_server)

    items = amux_server._load_board(done_limit=0)
    assert len(items) == 1
    assert "is_blocked" in items[0]


def test_item_by_id_has_blocked_by_key(amux_server, db):
    """_item_by_id returns single item with blocked_by (list)."""
    _insert_item(db, id="MP-1", title="Test")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert item is not None
    assert "blocked_by" in item


def test_item_by_id_has_is_blocked_key(amux_server, db):
    """_item_by_id returns single item with is_blocked (bool)."""
    _insert_item(db, id="MP-1", title="Test")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert item is not None
    assert "is_blocked" in item


def test_blocked_by_is_list_type(amux_server, db):
    """blocked_by is returned as a list, not a string."""
    _insert_item(db, id="MP-1", title="Test", blocked_by="MP-2,MP-3")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert isinstance(item["blocked_by"], list)


def test_is_blocked_is_bool_type(amux_server, db):
    """is_blocked is returned as a boolean."""
    _insert_item(db, id="MP-1", title="Test")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert isinstance(item["is_blocked"], bool)


def test_blocked_by_empty_default(amux_server, db):
    """Empty blocked_by in DB → [] in JSON."""
    _insert_item(db, id="MP-1", title="Test", blocked_by="")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert item["blocked_by"] == []


def test_blocked_by_comma_split(amux_server, db):
    """Comma-separated blocked_by in DB → list in JSON."""
    _insert_item(db, id="MP-1", title="Test", blocked_by="MP-2,MP-3")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-1")
    assert item["blocked_by"] == ["MP-2", "MP-3"]


def test_is_blocked_true_when_blocker_not_done(amux_server, db):
    """is_blocked=True when a blocker is not in done/verified/discarded status."""
    _insert_item(db, id="MP-1", title="Blocker", status="todo")
    _insert_item(db, id="MP-2", title="Blocked", blocked_by="MP-1")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-2")
    assert item["is_blocked"] is True


def test_is_blocked_false_when_all_blockers_done(amux_server, db):
    """is_blocked=False when all blockers are done/verified/discarded."""
    _insert_item(db, id="MP-1", title="Blocker", status="done")
    _insert_item(db, id="MP-2", title="Blocked", blocked_by="MP-1")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-2")
    assert item["is_blocked"] is False


def test_is_blocked_false_when_blocker_not_exist(amux_server, db):
    """is_blocked=False when blocker reference is stale (item doesn't exist)."""
    _insert_item(db, id="MP-2", title="Blocked", blocked_by="MP-99")
    _reset_db_conn(amux_server)

    item = amux_server._item_by_id("MP-2")
    assert item["is_blocked"] is False


# ── API tests ────────────────────────────────────────────────────────────────


def test_post_board_accepts_blocked_by(amux_server, db, mock_handler):
    """POST with blocked_by:["MP-1"] → 201, returns blocked_by array."""
    _insert_item(db, id="MP-1", title="Blocker")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"title": "New task", "blocked_by": ["MP-1"]},
        path="/api/board",
    )
    handler._route_inner("POST", "/api/board", {})

    assert handler._json_calls[-1][1] == 201
    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == ["MP-1"]


def test_post_board_defaults_blocked_by_empty(amux_server, db, mock_handler):
    """POST without blocked_by → 201, blocked_by defaults to []."""
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"title": "New task"},
        path="/api/board",
    )
    handler._route_inner("POST", "/api/board", {})

    assert handler._json_calls[-1][1] == 201
    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == []


def test_patch_board_updates_blocked_by(amux_server, db, mock_handler):
    """PATCH blocked_by:["MP-2"] → 200, reflected in response."""
    _insert_item(db, id="MP-1", title="Task")
    _insert_item(db, id="MP-2", title="Blocker")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": ["MP-2"]},
        path="/api/board/MP-1",
    )
    handler._route_inner("PATCH", "/api/board/MP-1", {})

    assert handler._json_calls[-1][1] == 200
    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == ["MP-2"]


def test_patch_board_clears_blocked_by(amux_server, db, mock_handler):
    """PATCH blocked_by:[] → 200, clears the field."""
    _insert_item(db, id="MP-1", title="Task", blocked_by="MP-2")
    _insert_item(db, id="MP-2", title="Blocker")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": []},
        path="/api/board/MP-1",
    )
    handler._route_inner("PATCH", "/api/board/MP-1", {})

    assert handler._json_calls[-1][1] == 200
    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == []


def test_patch_board_rejects_nonexistent_id(amux_server, db, mock_handler):
    """PATCH blocked_by:["FAKE-999"] → 400 when referenced item doesn't exist."""
    _insert_item(db, id="MP-1", title="Task")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": ["FAKE-999"]},
        path="/api/board/MP-1",
    )
    handler._route_inner("PATCH", "/api/board/MP-1", {})

    assert handler._json_calls[-1][1] == 400


def test_patch_board_rejects_self_dependency(amux_server, db, mock_handler):
    """PATCH blocked_by:["SELF-ID"] → 400 (can't block yourself)."""
    _insert_item(db, id="MP-1", title="Task")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": ["MP-1"]},
        path="/api/board/MP-1",
    )
    handler._route_inner("PATCH", "/api/board/MP-1", {})

    assert handler._json_calls[-1][1] == 400


def test_patch_board_rejects_direct_cycle(amux_server, db, mock_handler):
    """A→B→A cycle → 400."""
    _insert_item(db, id="MP-1", title="Task A", blocked_by="MP-2")
    _insert_item(db, id="MP-2", title="Task B")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": ["MP-1"]},
        path="/api/board/MP-2",
    )
    handler._route_inner("PATCH", "/api/board/MP-2", {})

    assert handler._json_calls[-1][1] == 400


def test_patch_board_rejects_indirect_cycle(amux_server, db, mock_handler):
    """A→B→C→A cycle → 400."""
    _insert_item(db, id="MP-1", title="Task A", blocked_by="MP-2")
    _insert_item(db, id="MP-2", title="Task B", blocked_by="MP-3")
    _insert_item(db, id="MP-3", title="Task C")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": ["MP-1"]},
        path="/api/board/MP-3",
    )
    handler._route_inner("PATCH", "/api/board/MP-3", {})

    assert handler._json_calls[-1][1] == 400


def test_claim_rejects_blocked_task(amux_server, db, mock_handler):
    """blocked task claim → 409."""
    _insert_item(db, id="MP-1", title="Blocker", status="todo")
    _insert_item(
        db, id="MP-2", title="Blocked", status="todo", owner_type="agent", blocked_by="MP-1"
    )
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"session": "test-session"},
        path="/api/board/MP-2/claim",
    )
    handler._route_inner("POST", "/api/board/MP-2/claim", {})

    assert handler._json_calls[-1][1] == 409


def test_claim_allows_when_blocker_done(amux_server, db, mock_handler):
    """blocker done → claim succeeds → 200, and is_blocked is False in response."""
    _insert_item(db, id="MP-1", title="Blocker", status="done")
    _insert_item(
        db, id="MP-2", title="Blocked", status="todo", owner_type="agent", blocked_by="MP-1"
    )
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"session": "test-session"},
        path="/api/board/MP-2/claim",
    )
    handler._route_inner("POST", "/api/board/MP-2/claim", {})

    assert handler._json_calls[-1][1] == 200
    response = handler._json_calls[-1][0]
    assert response["is_blocked"] is False


# ── Sanitization tests ───────────────────────────────────────────────────────


def test_blocked_by_deduplicates(amux_server, db, mock_handler):
    """["MP-1","MP-1"] → ["MP-1"]."""
    _insert_item(db, id="MP-1", title="Blocker")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"title": "New task", "blocked_by": ["MP-1", "MP-1"]},
        path="/api/board",
    )
    handler._route_inner("POST", "/api/board", {})

    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == ["MP-1"]


def test_blocked_by_trims_whitespace(amux_server, db, mock_handler):
    """[" MP-1 ","MP-3"] → ["MP-1","MP-3"]."""
    _insert_item(db, id="MP-1", title="Blocker")
    _insert_item(db, id="MP-3", title="Blocker 3")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"title": "New task", "blocked_by": [" MP-1 ", "MP-3"]},
        path="/api/board",
    )
    handler._route_inner("POST", "/api/board", {})

    response = handler._json_calls[-1][0]
    assert response["blocked_by"] == ["MP-1", "MP-3"]


def test_blocked_by_empty_array_clears(amux_server, db, mock_handler):
    """PATCH blocked_by:[] → empty string in DB."""
    _insert_item(db, id="MP-1", title="Task", blocked_by="MP-2")
    _insert_item(db, id="MP-2", title="Blocker")
    _reset_db_conn(amux_server)

    handler = mock_handler(
        body={"blocked_by": []},
        path="/api/board/MP-1",
    )
    handler._route_inner("PATCH", "/api/board/MP-1", {})

    # Verify DB state directly
    row = _get_db_item(db, "MP-1")
    assert row["blocked_by"] == ""
