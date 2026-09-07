"""AC-4 and AC-5: the audit log cannot be rewritten, and tampering is detectable."""
import pytest
from django.db import IntegrityError, connection, transaction

from audit.models import GENESIS_HASH, AuditEvent


def make_events(actor, count=3):
    return [
        AuditEvent.record(action=f"test.event.{index}", actor=actor, after={"index": index})
        for index in range(count)
    ]


@pytest.mark.django_db
def test_chain_links_each_event_to_the_previous_one(editor):
    events = make_events(editor)
    assert events[0].prev_hash == GENESIS_HASH
    for earlier, later in zip(events, events[1:]):
        assert later.prev_hash == earlier.row_hash
    ok, problems = AuditEvent.verify_chain()
    assert ok, problems


@pytest.mark.django_db
def test_the_orm_refuses_to_modify_an_event(editor):
    """AC-4 (negative)."""
    event = make_events(editor, 1)[0]
    event.action = "something.else"
    with pytest.raises(IntegrityError):
        event.save()


@pytest.mark.django_db
def test_the_orm_refuses_to_delete_an_event(editor):
    """AC-4 (negative)."""
    event = make_events(editor, 1)[0]
    with pytest.raises(IntegrityError):
        event.delete()


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_raw_sql_updates_and_deletes(editor):
    """AC-4 (negative): the guarantee does not depend on going through the ORM."""
    event = make_events(editor, 1)[0]

    with pytest.raises(Exception) as update_error:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_auditevent SET action = 'tampered' WHERE id = %s", [event.pk]
            )
    assert "append-only" in str(update_error.value)

    with pytest.raises(Exception) as delete_error:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_auditevent WHERE id = %s", [event.pk])
    assert "append-only" in str(delete_error.value)

    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_verification_detects_tampering_that_bypassed_the_trigger(editor):
    """AC-5: if someone disables the trigger and edits history, the chain still shows it."""
    events = make_events(editor, 3)
    target = events[1]

    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER audit_event_no_update_delete")
        cursor.execute(
            "UPDATE audit_auditevent SET action = 'quietly.changed' WHERE id = %s", [target.pk]
        )
        cursor.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER audit_event_no_update_delete")

    ok, problems = AuditEvent.verify_chain()
    assert not ok
    assert any(f"event {target.pk}" in problem and "altered" in problem for problem in problems)


@pytest.mark.django_db
def test_an_actor_who_has_acted_cannot_be_deleted(editor):
    """Audit rows outlive the account. Deactivate, do not delete."""
    make_events(editor, 1)
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        editor.delete()
