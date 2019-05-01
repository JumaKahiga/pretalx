from collections import defaultdict
from contextlib import suppress
from urllib.parse import quote

import pytz
from django.db import models, transaction
from django.template.loader import get_template
from django.utils.functional import cached_property
from django.utils.timezone import now, override as tzoverride
from django.utils.translation import override, ugettext_lazy as _

from pretalx.common.mixins import LogMixin
from pretalx.common.urls import EventUrls
from pretalx.mail.context import template_context_from_event
from pretalx.person.models import User
from pretalx.submission.models import SubmissionStates


class Schedule(LogMixin, models.Model):
    """
    The Schedule model contains all scheduled
    :class:`~pretalx.schedule.models.slot.TalkSlot` objects (visible or not)
    for a schedule release for an :class:`~pretalx.event.models.event.Event`.

    :param published: ``None`` if the schedule has not been published yet.
    """
    event = models.ForeignKey(
        to='event.Event', on_delete=models.PROTECT, related_name='schedules'
    )
    version = models.CharField(
        max_length=190, null=True, blank=True, verbose_name=_('version')
    )
    published = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-published',)
        unique_together = (('event', 'version'),)

    class urls(EventUrls):
        public = '{self.event.urls.schedule}v/{self.url_version}/'

    @transaction.atomic
    def unfreeze(self, user=None):
        """Resets the current WIP schedule to an older schedule version."""
        from pretalx.schedule.models import TalkSlot

        if not self.version:
            raise Exception('Cannot unfreeze schedule version: not released yet.')

        # collect all talks, which have been added since this schedule (#72)
        submission_ids = self.talks.all().values_list('submission_id', flat=True)
        talks = self.event.wip_schedule.talks.exclude(
            submission_id__in=submission_ids
        ).union(self.talks.all())

        wip_schedule = Schedule.objects.create(event=self.event)
        new_talks = []
        for talk in talks:
            new_talks.append(talk.copy_to_schedule(wip_schedule, save=False))
        TalkSlot.objects.bulk_create(new_talks)

        self.event.wip_schedule.talks.all().delete()
        self.event.wip_schedule.delete()

        with suppress(AttributeError):
            del wip_schedule.event.wip_schedule

        return self, wip_schedule

    @cached_property
    def scheduled_talks(self):
        """Returns all :class:`~pretalx.schedule.models.slot.TalkSlot` objects that have been scheduled."""
        return self.talks.select_related(
            'submission', 'submission__event', 'room',
        ).filter(
            room__isnull=False, start__isnull=False, is_visible=True
        ).exclude(submission__state=SubmissionStates.DELETED)

    @cached_property
    def slots(self):
        """Returns all :class:`~pretalx.submission.models.submission.Submission` objects with :class:`~pretalx.schedule.models.slot.TalkSlot` objects in this schedule."""
        from pretalx.submission.models import Submission

        return Submission.objects.filter(
            id__in=self.scheduled_talks.values_list('submission', flat=True)
        )

    @cached_property
    def previous_schedule(self):
        """Returns the schedule released before this one, if any."""
        queryset = self.event.schedules.exclude(pk=self.pk)
        if self.published:
            queryset = queryset.filter(published__lt=self.published)
        return queryset.order_by('-published').first()

    @cached_property
    def tz(self):
        return pytz.timezone(self.event.timezone)

    @cached_property
    def warnings(self) -> dict:
        """A dictionary of warnings to be acknowledged pre-release.

        ``talk_warnings`` contains a list of talk-related warnings.
        ``unscheduled`` is the list of talks without a scheduled slot,
        ``unconfirmed`` is the list of submissions that will not be visible due
        to their unconfirmed status, and ``no_track`` are submissions without a
        track in a conference that uses tracks.
        """
        warnings = {
            'talk_warnings': [],
            'unscheduled': [],
            'unconfirmed': [],
            'no_track': [],
        }
        for talk in self.talks.all():
            if not talk.start:
                warnings['unscheduled'].append(talk)
            elif talk.warnings:
                warnings['talk_warnings'].append(talk)
            if talk.submission.state != SubmissionStates.CONFIRMED:
                warnings['unconfirmed'].append(talk)
            if talk.submission.event.settings.use_tracks and not talk.submission.track:
                warnings['no_track'].append(talk)
        return warnings

    @cached_property
    def url_version(self):
        return quote(self.version) if self.version else 'wip'

    @cached_property
    def is_archived(self):
        if not self.version:
            return False

        return self != self.event.current_schedule

    def __str__(self) -> str:
        """Help when debugging."""
        return f'Schedule(event={self.event.slug}, version={self.version})'
