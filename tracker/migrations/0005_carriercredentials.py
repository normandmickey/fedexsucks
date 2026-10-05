from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [('tracker', '0004_multi_tenant')]

    operations = [
        migrations.CreateModel(
            name='CarrierCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('carrier', models.CharField(choices=[('fedex', 'FedEx'), ('ups', 'UPS'), ('usps', 'USPS')], db_index=True, max_length=20)),
                ('api_key_enc', models.TextField(blank=True)),
                ('secret_key_enc', models.TextField(blank=True)),
                ('account_number', models.CharField(blank=True, max_length=100)),
                ('base_url', models.CharField(blank=True, help_text='Optional API base URL override', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='carrier_credentials', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['carrier']},
        ),
        migrations.AddConstraint(
            model_name='carriercredential',
            constraint=models.UniqueConstraint(fields=('owner', 'carrier'), name='uniq_credential_owner_carrier'),
        ),
    ]
