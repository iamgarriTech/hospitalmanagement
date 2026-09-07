"""Trigram search on the generated name column.

Powers both fuzzy patient search and duplicate detection. pg_trgm is created here rather
than assumed, so a fresh database is enough to run the project.
"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("patients", "0001_initial")]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="patient",
            index=GinIndex(
                name="patient_search_name_trgm",
                fields=["search_name"],
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
