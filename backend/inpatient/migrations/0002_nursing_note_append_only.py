"""Refuse UPDATE and DELETE on nursing notes at the database level.

AC-79 asks for notes that are append-only "in effect". Refusing it in a
serializer would hold only for requests that come through the API; a note is
evidence, and a correction has to be a new note pointing at the original so the
earlier reading stays exactly as written.

The model has no mutable column by design, so nothing legitimate needs UPDATE.
Row-level only, so TRUNCATE still works and test databases can be flushed.
"""
from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION nursing_note_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'inpatient_nursingnote is append-only; correct a note by adding one that '
        'supersedes it (% is not permitted)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER nursing_note_no_update_delete
    BEFORE UPDATE OR DELETE ON inpatient_nursingnote
    FOR EACH ROW EXECUTE FUNCTION nursing_note_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS nursing_note_no_update_delete ON inpatient_nursingnote;
DROP FUNCTION IF EXISTS nursing_note_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("inpatient", "0001_initial")]

    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE)]
