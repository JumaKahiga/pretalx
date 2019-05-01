def speakers_with_changed_slots(schedule):
    """Returns a dictionary of speakers with their new and changed talks in this schedule.

    Each speaker is assigned a dictionary with ``create`` and ``update``
    fields, each containing a list of submissions.
    """
    changes = compare_schedule_with_predecessor(schedule)
    if changes['action'] == 'create':
        return {
            speaker: {
                'create': schedule.talks.filter(submission__speakers=speaker),
                'update': [],
            }
            for speaker in User.objects.filter(submissions__slots__schedule=schedule)
        }

    if changes['count'] == len(changes['canceled_talks']):
        return []

    speakers = defaultdict(lambda: {'create': [], 'update': []})
    for new_talk in changes['new_talks']:
        for speaker in new_talk.submission.speakers.all():
            speakers[speaker]['create'].append(new_talk)
    for moved_talk in changes['moved_talks']:
        for speaker in moved_talk['submission'].speakers.all():
            speakers[speaker]['update'].append(moved_talk)
    return speakers


def _handle_submission_move(submission_pk, old_slots, new_slots, tz):
    new = []
    canceled = []
    moved = []
    all_old_slots = list(old_slots.filter(submission__pk=submission_pk))
    all_new_slots = list(new_slots.filter(submission__pk=submission_pk))
    old_slots = [slot for slot in all_old_slots if not any(slot.is_same_slot(other_slot) for other_slot in all_new_slots)]
    new_slots = [slot for slot in all_new_slots if not any(slot.is_same_slot(other_slot) for other_slot in all_old_slots)]
    diff = len(old_slots) - len(new_slots)
    if diff > 0:
        canceled = old_slots[:diff]
        old_slots = old_slots[diff:]
    elif diff < 0:
        diff = -diff
        new = new_slots[:diff]
        new_slots = new_slots[diff:]
    for move in zip(old_slots, new_slots):
        old_slot = move[0]
        new_slot = move[1]
        moved.append({
            'submission': new_slot.submission,
            'old_start': old_slot.start.astimezone(tz),
            'new_start': new_slot.start.astimezone(tz),
            'old_room': old_slot.room.name,
            'new_room': new_slot.room.name,
            'new_info': new_slot.room.speaker_info,
        })
    return new, canceled, moved

def compare_schedule_with_predecessor(schedule) -> dict:
    """Returns a dictionary of changes when compared to the previous version.

    The ``action`` field is either ``create`` or ``update``. If it's an
    update, the ``count`` integer, and the ``new_talks``,
    ``canceled_talks`` and ``moved_talks`` lists are also present."""
    result = {
        'count': 0,
        'action': 'update',
        'new_talks': [],
        'canceled_talks': [],
        'moved_talks': [],
    }
    if not schedule.previous_schedule:
        result['action'] = 'create'
        return result

    old_slots = schedule.previous_schedule.scheduled_talks
    new_slots = schedule.scheduled_talks
    old_slot_set = set(old_slots.values_list('submission', 'room', 'start', named=True))
    new_slot_set = set(new_slots.values_list('submission', 'room', 'start', named=True))
    old_submissions = set(old_slots.values_list('submission__id', flat=True))
    new_submissions = set(new_slots.values_list('submission__id', flat=True))
    handled_submissions = set()

    moved_or_missing = old_slot_set - new_slot_set
    moved_or_new = new_slot_set - old_slot_set
    tz = schedule.tz

    for entry in moved_or_missing:
        if entry.submission in handled_submissions:
            continue
        if entry.submission not in new_submissions:
            result['canceled_talks'] += list(old_slots.filter(submission__pk=entry.submission))
        else:
            new, canceled, moved = _handle_submission_move(entry.submission, old_slots, new_slots, tz)
            result['new_talks'] += new
            result['canceled_talks'] += canceled
            result['moved_talks'] += moved
        handled_submissions.add(entry.submission)
    for entry in moved_or_new:
        if entry.submission in handled_submissions:
            continue
        if entry.submission not in old_submissions:
            result['new_talks'] += list(new_slots.filter(submission__pk=entry.submission))
        else:
            new, canceled, moved = _handle_submission_move(entry.submission, old_slots, new_slots, tz)
            result['new_talks'] += new
            result['canceled_talks'] += canceled
            result['moved_talks'] += moved
        handled_submissions.add(entry.submission)

    result['count'] = (
        len(result['new_talks'])
        + len(result['canceled_talks'])
        + len(result['moved_talks'])
    )
    return result
