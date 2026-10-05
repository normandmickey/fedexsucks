from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_owners(apps, schema_editor):
    """Assign every pre-tenancy row to the oldest superuser (the original user)."""
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    owner = (
        user_model.objects.filter(is_superuser=True).order_by('id').first()
        or user_model.objects.order_by('id').first()
    )
    if owner is None:
        return
    apps.get_model('tracker', 'Package').objects.filter(owner__isnull=True).update(owner=owner)
    apps.get_model('tracker', 'SavedReference').objects.filter(owner__isnull=True).update(owner=owner)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0003_alter_package_tracking_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='packages', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='savedreference',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='saved_references', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(backfill_owners, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='package',
            name='tracking_number',
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name='savedreference',
            name='reference_value',
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AddConstraint(
            model_name='package',
            constraint=models.UniqueConstraint(fields=('owner', 'tracking_number'), name='uniq_package_owner_tracking'),
        ),
        migrations.AddConstraint(
            model_name='savedreference',
            constraint=models.UniqueConstraint(fields=('owner', 'reference_value'), name='uniq_savedreference_owner_value'),
        ),
    ]
