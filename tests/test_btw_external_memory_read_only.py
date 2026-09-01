from api import streaming


def test_ephemeral_agent_disables_external_writes_and_background_review():
    kwargs = {"session_id": "btw-session"}
    supported = {"external_memory_read_only", "skip_background_review"}

    streaming._apply_ephemeral_agent_persistence_policy(
        kwargs,
        supported,
        ephemeral=True,
    )

    assert kwargs["external_memory_read_only"] is True
    assert kwargs["skip_background_review"] is True

    normal = {}
    streaming._apply_ephemeral_agent_persistence_policy(
        normal, supported, ephemeral=False
    )
    assert normal == {}


def test_ephemeral_state_db_target_is_temporary(tmp_path):
    path, owned = streaming._state_db_target_for_stream(tmp_path, ephemeral=True)
    assert owned is not None and owned in path.parents
    owned.rmdir()


def test_ephemeral_run_journal_is_disabled():
    assert streaming._run_journal_enabled_for_stream(ephemeral=True) is False
