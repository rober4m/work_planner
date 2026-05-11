import sys
import time
import argparse
from datetime import datetime, timedelta, date
import EventKit
import Foundation

WORK_BLOCKS = [
    (8,  30, 2.0),   # 08:30 - 10:30
    (10, 30, 2.0),   # 10:30 - 12:30
    (13, 30, 2.0),   # 13:30 - 15:30
    (15, 30, 2.0),   # 15:30 - 17:30
]

HOURS_PER_DAY = 8   # total available work hours per day (8:30-17:30 minus break)

def build_store():
    store = EventKit.EKEventStore.alloc().init()
    granted_box, done_box = [False], [False]

    def cb(ok, err):
        granted_box[0] = bool(ok)
        done_box[0]    = True

    try:
        store.requestFullAccessToEventsWithCompletion_(cb)
    except AttributeError:
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent, cb
        )

    for _ in range(150):
        if done_box[0]:
            break
        time.sleep(0.1)

    if not granted_box[0]:
        sys.exit("❌  Calendar access denied.\n"
                 "    System Settings → Privacy & Security → Calendars")

    return store


def get_cal(store):
    for c in store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
        if c.title() == "Work":
            return c
    c = EventKit.EKCalendar.calendarForEntityType_eventStore_(
        EventKit.EKEntityTypeEvent, store
    )
    c.setTitle_("Work")
    c.setSource_(store.defaultCalendarForNewEvents().source())
    store.saveCalendar_commit_error_(c, True, None)
    return c


def is_overlapping(store, start: datetime, end: datetime) -> bool:
    """
    Returns True if any existing calendar event overlaps with [start, end).
    Checks ALL calendars so a work block won't clash with personal events either.
    """
    ns_start = Foundation.NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
    ns_end   = Foundation.NSDate.dateWithTimeIntervalSince1970_(end.timestamp())

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        ns_start, ns_end, None   # None = search all calendars
    )
    existing = store.eventsMatchingPredicate_(predicate)
    return len(existing) > 0


def find_free_slot(store, day: date, sh: int, sm: int, needed_hours: float):
    """
    Given a work block starting at (sh, sm) on `day`, find the first
    sub-slot within that block that is free.

    Returns (free_start, free_end, actual_hours) or None if block is fully booked.

    Strategy:
      - Query existing events that overlap the block window
      - Walk the block minute by minute in 30-min increments to find a gap
        large enough for at least 0.5 h (smallest meaningful chunk)
    """
    block_start = datetime(day.year, day.month, day.day, sh, sm)
    block_end   = block_start + timedelta(hours=needed_hours)

    # Fetch all events overlapping this block
    ns_bs = Foundation.NSDate.dateWithTimeIntervalSince1970_(block_start.timestamp())
    ns_be = Foundation.NSDate.dateWithTimeIntervalSince1970_(block_end.timestamp())
    pred  = store.predicateForEventsWithStartDate_endDate_calendars_(ns_bs, ns_be, None)
    busy  = store.eventsMatchingPredicate_(pred)

    if not busy:
        # Entire block is free — use as much as needed
        used  = min(needed_hours, (block_end - block_start).seconds / 3600)
        return block_start, block_start + timedelta(hours=used), used

    # Build a sorted list of busy intervals within this block
    busy_intervals = []
    for ev in busy:
        ev_start = datetime.fromtimestamp(ev.startDate().timeIntervalSince1970())
        ev_end   = datetime.fromtimestamp(ev.endDate().timeIntervalSince1970())
        # Clamp to block boundaries
        s = max(ev_start, block_start)
        e = min(ev_end,   block_end)
        if s < e:
            busy_intervals.append((s, e))

    busy_intervals.sort(key=lambda x: x[0])

    # Find free gaps between busy intervals
    gaps = []
    cursor = block_start

    for bs, be in busy_intervals:
        if cursor < bs:
            gaps.append((cursor, bs))
        cursor = max(cursor, be)

    if cursor < block_end:
        gaps.append((cursor, block_end))

    # Pick the first gap that is >= 30 min
    min_chunk = timedelta(minutes=30)
    for gap_start, gap_end in gaps:
        gap_duration = gap_end - gap_start
        if gap_duration >= min_chunk:
            used = min(needed_hours, gap_duration.seconds / 3600)
            return gap_start, gap_start + timedelta(hours=used), used

    return None   # block is fully booked
# ── Time parsing (replaces --hours float) ────────────────────────────────────

def parse_time(raw: str) -> float:

    raw = raw.strip().lower()

    if raw.endswith('h'):
        try:
            return float(raw[:-1])
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"Cannot parse '{raw}'. Use format: 8h or 5d"
            )

    if raw.endswith('d'):
        try:
            days = float(raw[:-1])
            return days * HOURS_PER_DAY
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"Cannot parse '{raw}'. Use format: 8h or 5d"
            )

    raise argparse.ArgumentTypeError(
        f"Cannot parse '{raw}'. Use 'h' for hours or 'd' for days — e.g. 8h or 5d"
    )

def save_event(store, cal, title, start, end, notes):
    ev = EventKit.EKEvent.eventWithEventStore_(store)
    ev.setTitle_(title)
    ev.setStartDate_(Foundation.NSDate.dateWithTimeIntervalSince1970_(start.timestamp()))
    ev.setEndDate_(Foundation.NSDate.dateWithTimeIntervalSince1970_(end.timestamp()))
    ev.setCalendar_(cal)
    ev.setNotes_(notes)
    ev.addAlarm_(EventKit.EKAlarm.alarmWithRelativeOffset_(-900))
    return bool(store.saveEvent_span_commit_error_(ev, EventKit.EKSpanThisEvent, True, None))


def parse_deadline(raw):
    today = date.today()
    for fmt in ("%d-%m", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw, fmt).date()
            if "%Y" not in fmt:
                d = d.replace(year=today.year)
                if d < today:
                    d = d.replace(year=today.year + 1)
            return d
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Cannot parse '{raw}'. Use DD-MM, DD-MM-YYYY or YYYY-MM-DD."
    )

# ── Scheduling ────────────────────────────────────────────────────────────────

def do_work(store, project, total_hours, deadline):
    cal       = get_cal(store)
    rem       = total_hours
    day       = date.today() + timedelta(days=1)
    n         = 0

    if deadline < day:
        sys.exit("❌  Deadline must be at least 1 day from today.")

    print(f"\n  Project  : {project}")
    print(f"  Time     : {total_hours}h total")
    print(f"  Starting : {day.strftime('%A, %B %d %Y')}")
    print(f"  Deadline : {deadline.strftime('%A, %B %d %Y')}\n")

    while rem > 0 and day <= deadline:
        if day.weekday() <= 4:
            for sh, sm, bh in WORK_BLOCKS:
                if rem <= 0:
                    break

                slot = find_free_slot(store, day, sh, sm, min(bh, rem))

                if slot is None:
                    block_start = datetime(day.year, day.month, day.day, sh, sm)
                    block_end   = block_start + timedelta(hours=bh)
                    print(f"  ⏭️   {day.strftime('%a %b %d')}  "
                          f"{block_start.strftime('%I:%M %p')} - "
                          f"{block_end.strftime('%I:%M %p')}  (busy — skipped)")
                    continue

                free_start, free_end, used = slot
                notes = (f"Project: {project}\n"
                         f"Block: {used:.1f}h of {bh}h\n"
                         f"Deadline: {deadline}")

                if save_event(store, cal, f"{project}",
                              free_start, free_end, notes):
                    print(f"  ✅  {day.strftime('%a %b %d')}  "
                          f"{free_start.strftime('%I:%M %p')} - "
                          f"{free_end.strftime('%I:%M %p')}  ({used:.1f}h)")
                    n  += 1
                    rem = round(rem - used, 2)
                else:
                    print(f"  ⚠️   Could not save event on {day}")

        day += timedelta(days=1)

    print()
    if rem > 0:
        print(f"⚠️  {rem:.1f}h could not fit before the deadline.")
        print("   Try a later deadline or reduce total time.")
    else:
        print(f"🎉  Done — {n} event(s) added to 'Work' calendar.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="work_planner.py",
        description="Schedule work blocks in macOS Calendar.",
        epilog="Example: python work_planner.py --project 'API migration' --hours 12 --deadline 25-05"
    )
    parser.add_argument("--project",  required=True, help="Project name")
    parser.add_argument("--time", required=True, metavar="DURATION", help="Time to schedule: 8h (hours) or 5d (days)")
    parser.add_argument("--deadline", required=True, help="Deadline: DD-MM | DD-MM-YYYY | YYYY-MM-DD")
    args = parser.parse_args()

    # if args.hours <= 0:
    #     sys.exit("❌  --hours must be a positive number.")

    total_hours = parse_time(args.time)
    if total_hours <= 0:
        sys.exit("❌  --time must be a positive value.")

    deadline = parse_deadline(args.deadline)
    store    = build_store()

    do_work(store, args.project, total_hours, deadline)




if __name__ == "__main__":
    main()