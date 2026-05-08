import sys
import time
import argparse
from datetime import datetime, timedelta, date
import EventKit
import Foundation

WORK_BLOCKS = [
    (8,  0,  2.0),   # 08:00 - 10:00
    (10, 30, 2.0),   # 10:30 - 12:30
    (13, 30, 2.0),   # 13:30 - 15:30
    (15, 30, 1.5),   # 15:30 - 17:00
]


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


def main():
    parser = argparse.ArgumentParser(
        prog="work_planner.py",
        description="Schedule work blocks in macOS Calendar.",
        epilog="Example: python work_planner.py --project 'API migration' --hours 12 --deadline 25-05"
    )
    parser.add_argument("--project",  required=True, help="Project name")
    parser.add_argument("--hours",    required=True, type=float, help="Total hours to schedule")
    parser.add_argument("--deadline", required=True, help="Deadline: DD-MM | DD-MM-YYYY | YYYY-MM-DD")
    args = parser.parse_args()

    if args.hours <= 0:
        sys.exit("❌  --hours must be a positive number.")

    deadline = parse_deadline(args.deadline)
    today    = date.today()
    start_day  = today + timedelta(days=1)

    if deadline < start_day:
        sys.exit("❌  Deadline is in the past or too close.")

    store = build_store()
    cal   = get_cal(store)
    rem   = args.hours
    day   = start_day
    n     = 0

    print(f"\n  Project  : {args.project}")
    print(f"  Hours    : {args.hours}h")
    print(f"  Deadline : {deadline.strftime('%A, %B %d %Y')}\n")

    while rem > 0 and day <= deadline:
        if day.weekday() <= 4:                          # Monday–Friday
            for sh, sm, bh in WORK_BLOCKS:
                if rem <= 0:
                    break
                used  = min(bh, rem)
                start = datetime(day.year, day.month, day.day, sh, sm)
                end   = start + timedelta(hours=used)
                notes = (f"Project: {args.project}\n"
                         f"Block: {used:.1f}h of {bh}h\n"
                         f"Deadline: {deadline}")

                if save_event(store, cal, f"[Work] {args.project}", start, end, notes):
                    print(f"  ✅  {day.strftime('%a %b %d')}  "
                          f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}  "
                          f"({used:.1f}h)")
                    n  += 1
                    rem = round(rem - used, 2)
                else:
                    print(f"  ⚠️   Could not save event on {day}")

        day += timedelta(days=1)

    print()
    if rem > 0:
        print(f"⚠️  {rem:.1f}h could not fit before the deadline.")
    else:
        print(f"🎉  Done — {n} event(s) added to 'Work' calendar.")


if __name__ == "__main__":
    main()