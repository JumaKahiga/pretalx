from django.db import transaction
from pretalx.agenda.tasks import export_schedule_html
from django.utils.timezone import now
from pretalx.schedule.models import TalkSlot
from pretalx.mail.models import QueuedMail


@transaction.atomic
def freeze_schedule(*, schedule, name, user, notify_speakers=True):
    """Releases the current WIP schedule as a fixed schedule version.

    Returns the released schedule and the new WIP schedule.

    :param schedule: The schedule to be frozen.
    :param name: The new schedule name. May not be in use in this event, and
        cannot be 'wip' or 'latest'.
    :param user: The :class:`~pretalx.person.models.user.User` initiating the
        freeze.
    :param notify_speakers: Should notification emails for speakers with
        changed slots be generated?
    :rtype: list[Schedule, Schedule]
    """

    if name in ['wip', 'latest']:
        raise Exception(f'Cannot use reserved name "{name}" for schedule version.')
    if schedule.version:
        raise Exception(f'Cannot freeze schedule version: already versioned as "{schedule.version}".')
    if not name:
        raise Exception('Cannot create schedule version without a version name.')

    schedule.published = now()
    schedule.version = name
    schedule.save(update_fields=['published', 'version'])
    schedule.log_action('pretalx.schedule.release', person=user, orga=True)

    wip_schedule = Schedule.objects.create(event=schedule.event)

    # Set visibility
    schedule.talks.filter(
        start__isnull=False,
        submission__state=SubmissionStates.CONFIRMED,
        is_visible=False,
    ).update(is_visible=True)
    schedule.talks.filter(is_visible=True).exclude(
        start__isnull=False, submission__state=SubmissionStates.CONFIRMED
    ).update(is_visible=False)

    talks = []
    for talk in schedule.talks.select_related('submission', 'room').all():
        talks.append(talk.copy_to_schedule(wip_schedule, save=False))
    TalkSlot.objects.bulk_create(talks)

    if notify_speakers:
        create_release_notifications(schedule, commit=True)

    with suppress(AttributeError):
        del wip_schedule.event.wip_schedule
    with suppress(AttributeError):
        del wip_schedule.event.current_schedule

    if schedule.event.settings.export_html_on_schedule_release:
        export_schedule_html.apply_async(kwargs={'event_id': schedule.event.id})

    return schedule, wip_schedule


def create_release_notifications(schedule, commit: bool=False):
    """A list of unsaved :class:`~pretalx.mail.models.QueuedMail` objects to be sent on schedule release."""
    from pretalx.schedule.selectors import get_speakers_with_changed_slots
    mails = []
    speakers_concerned = get_speakers_with_changed_slots(schedule)
    for speaker in speakers_concerned:
        with override(speaker.locale), tzoverride(schedule.tz):
            notifications = get_template(
                'schedule/speaker_notification.txt'
            ).render({'speaker': speaker, **speakers_concerned[speaker]})
        context = template_context_from_event(schedule.event)
        context['notifications'] = notifications
        mails.append(
            schedule.event.update_template.to_mail(
                user=speaker, event=schedule.event, context=context, commit=False
            )
        )
    if commit:
        QueuedMail.bulk_create(mails)
    return mails
