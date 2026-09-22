from app.core.storage import SqliteConversationStore


def _store(tmp_path):
    return SqliteConversationStore(tmp_path / "test.db")


def test_create_conversation_and_list(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    conversations = store.list_conversations()
    assert len(conversations) == 1
    assert conversations[0].id == conv_id
    assert conversations[0].title == "New conversation"


def test_append_message_persists_and_derives_title_from_first_user_message(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    store.append_message(conv_id, "user", "what's the status of PS 400001438900 at plant 0780?")
    store.append_message(conv_id, "assistant", "It failed with a Business Error.")

    history = store.get_history(conv_id)
    assert [(m.role, m.content) for m in history] == [
        ("user", "what's the status of PS 400001438900 at plant 0780?"),
        ("assistant", "It failed with a Business Error."),
    ]

    conversations = store.list_conversations()
    assert conversations[0].title == "what's the status of PS 400001438900 at plant 0780?"


def test_unique_first_message_gets_a_clean_title_with_no_suffix(tmp_path):
    """Regression test: caught live via QA testing -- always appending a
    timestamp/id suffix (an earlier fix for title collisions) made the
    common case, where nothing actually collides, "close to useless" with
    cryptic cruft on every title. Only a real collision should trigger it."""
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    store.append_message(conv_id, "user", "Hi")

    assert store.list_conversations()[0].title == "Hi"


def test_two_conversations_with_the_same_first_message_get_distinguishable_titles(tmp_path):
    """Two conversations both opening with "Hi" must not render identically
    in the sidebar -- the second one gets a disambiguating suffix once the
    collision is detected."""
    store = _store(tmp_path)
    conv_a = store.create_conversation()
    conv_b = store.create_conversation()
    store.append_message(conv_a, "user", "Hi")
    store.append_message(conv_b, "user", "Hi")

    titles = {c.id: c.title for c in store.list_conversations()}
    assert titles[conv_a] != titles[conv_b]
    assert titles[conv_b].startswith("Hi (")


def test_long_first_message_truncates_title(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    long_message = "why is this packaging specification stuck in the pipeline and not reaching the target system " * 2
    store.append_message(conv_id, "user", long_message)

    title = store.list_conversations()[0].title
    assert "..." in title
    assert len(title) <= 63  # base truncated to 60 chars + "..."


def test_title_only_set_from_first_user_message_not_later_ones(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    store.append_message(conv_id, "user", "first question")
    store.append_message(conv_id, "assistant", "an answer")
    store.append_message(conv_id, "user", "a follow-up question")

    assert store.list_conversations()[0].title == "first question"


def test_get_messages_includes_timestamps(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    store.append_message(conv_id, "user", "hello")

    messages = store.get_messages(conv_id)
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "hello"
    assert messages[0].created_at


def test_list_conversations_ordered_by_most_recently_updated(tmp_path):
    store = _store(tmp_path)
    first = store.create_conversation()
    second = store.create_conversation()
    store.append_message(first, "user", "touch first again")  # bumps first's updated_at to be latest

    ids_in_order = [c.id for c in store.list_conversations()]
    assert ids_in_order[0] == first
    assert ids_in_order[1] == second


def test_delete_conversation_removes_conversation_and_messages(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    store.append_message(conv_id, "user", "hello")

    store.delete_conversation(conv_id)

    assert store.list_conversations() == []
    assert store.get_messages(conv_id) == []


def test_record_issue_returns_id_and_does_not_raise_without_conversation(tmp_path):
    store = _store(tmp_path)
    conv_id = store.create_conversation()
    issue_id = store.record_issue(conv_id, "the answer seemed wrong")
    assert issue_id == 1

    issue_id_2 = store.record_issue(None, "general feedback, no specific conversation")
    assert issue_id_2 == 2


def test_two_store_instances_share_the_same_db_file(tmp_path):
    db_path = tmp_path / "shared.db"
    store_a = SqliteConversationStore(db_path)
    conv_id = store_a.create_conversation()
    store_a.append_message(conv_id, "user", "hello from instance A")

    store_b = SqliteConversationStore(db_path)
    history = store_b.get_history(conv_id)
    assert history[0].content == "hello from instance A"
