"""Record which payload shape each event was hashed under.

Existing rows predate the patient reference, so they keep version 1 and continue to
verify against the payload they were actually hashed with. ADD COLUMN with a default is
DDL, so it does not trip the append-only trigger.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("audit", "0003_auditevent_patient")]

    operations = [
        migrations.AddField(
            model_name="auditevent",
            name="hash_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        # New rows use the current shape; only pre-existing rows stay on version 1.
        migrations.AlterField(
            model_name="auditevent",
            name="hash_version",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
