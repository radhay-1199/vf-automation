# Generated by Django 4.2.20 on 2025-03-31 17:07

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Flight',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('flight_unique_id', models.CharField(max_length=100, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='MockConfiguration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('delay_between_events', models.IntegerField(default=5)),
                ('fast_forward', models.BooleanField(default=False)),
                ('manual_mode', models.BooleanField(default=False)),
                ('callback_url', models.URLField()),
                ('cleanup_before_start', models.BooleanField(default=True)),
                ('cleanup_query', models.TextField(blank=True, help_text='SQL query to run before starting mock')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('flight', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='event_manager.flight')),
            ],
        ),
        migrations.CreateModel(
            name='FlightEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_event', models.TextField()),
                ('flight_state', models.CharField(max_length=50)),
                ('priority', models.IntegerField()),
                ('identified_changes', models.TextField(blank=True)),
                ('is_played', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('flight', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='event_manager.flight')),
            ],
            options={
                'ordering': ['priority', 'created_at'],
            },
        ),
        migrations.CreateModel(
            name='AdditionalTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('task_type', models.CharField(choices=[('kafka', 'Kafka Event'), ('api', 'API Call'), ('cleanup', 'Cleanup Task')], max_length=20)),
                ('payload_template', models.TextField(help_text='JSON template for the task')),
                ('order', models.IntegerField(default=0)),
                ('is_enabled', models.BooleanField(default=True)),
                ('configuration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='event_manager.mockconfiguration')),
            ],
            options={
                'ordering': ['order'],
            },
        ),
    ]
