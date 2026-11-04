# Campus Consultations — Responsive Localhost + Railway Edition

Student Consultation Scheduler (CPE 304L Software Design Laboratory, Bulacan State University).

## Start with one double-click

1. Extract the whole ZIP into a folder on Windows.
2. Double-click **START_HERE.bat**.
3. The app opens at **http://127.0.0.1:8443** (or enter this address manually).
4. Keep the terminal open while using the app. Close it to stop.

**Prerequisite:** Windows must already have **Python 3.9 or newer** (`py` or `python`). This is the same kind of prerequisite as the supplied BLOOM `START.bat`. The launcher does **not** install Python. **No Node.js, npm, MongoDB, pip, Flask, or internet access** is required at runtime. The built-in HTTP server and SQLite run locally. This is **not** an install-free `.exe`. **Railway deployment** instructions are in `DEPLOY_RAILWAY.md`.

## Preloaded classroom test accounts

All six accounts (three students and three instructors) are automatically seeded into SQLite on first start. Use the **same Student IDs/emails and passwords previously supplied for the classroom demonstration**. No passwords are stored in plaintext in source code or SQLite; initial hashes are bundled with the seed definitions.

**Do not store real student consultation records on this demonstration deployment.** Keep your GitHub repository private and share only with your professor.

## Interface

- Responsive desktop website with a full sidebar, wider dashboard, instructor cards and consultation views.
- Responsive tablet and mobile view with compact bottom navigation. No 500-pixel desktop phone frame.
- Consistent inline SVG icons instead of unsupported Unicode glyphs; blue-and-white Lab 5-inspired design.
- Role-specific dashboard, consultation requests, instructor availability, notification inbox, and account information.
- A warning banner appears if a student holds a **Confirmed** request with an instructor currently marked **Unavailable** or **In a Meeting**.
- Students see a shortcut to their existing active request instead of being prompted to submit a duplicate.

## Requirements traceability — MT LAB SD.pdf, pp. 1–5

| PDF requirement | Implementation / validation |
| --- | --- |
| FR-001: Instructor can change Available / Unavailable / In a Meeting anytime | Instructor dashboard sends an authenticated PUT; `instructor.current_status` uses a CHECK and a `status_log` records each actual change. |
| FR-002: A student with a Confirmed booking is notified when that instructor changes status | An event-linked row is inserted in `notification`, scoped to confirmed students with current/future booking dates. The open student's inbox receives updates through SSE; inactive browser notifications are persisted for later viewing. |
| FR-003: Live availability is visible to students | Dashboard fetches all three instructors and live updates via server-sent events, with a 4-second refresh fallback. |
| FR-004: Reject overlapping Confirmed consultation time or the same student's second Pending/Confirmed request with that instructor | Pre-insert API checks, instructor-confirmation checks, and additional **SQLite BEFORE INSERT / UPDATE triggers** enforce both rules. |
| FR-005: Requests require instructor approval | New requests default to **Pending**. Only the assigned instructor can change a Pending request to **Confirmed** or **Declined**. Students may only cancel their own Pending / Confirmed request. |
| NFR-001: Status-change notification within 5 seconds while online | Connected local browser sessions use **server-sent events** (normally near-instant). A 4-second refresh fallback is included. The backend SSE path was tested successfully, but the 5-second objective is not formally guaranteed on slow devices or connections. |
| NFR-002: Available 24/7 via standard browser and >=99.9% term uptime | The app opens in modern standard browsers, but **localhost cannot meet this uptime promise while the host PC is off**, and no 24/7 hosting or availability measurement has been implemented. This NFR remains **not achieved** until the service is deployed and monitored. |

**Scope:** Student digital requests, instructor availability, status notifications, and instructor approval. No class schedules, grades, enrollment, attendance, video calls, or unrelated university services are included.

## PDF structural/database relationship mapping

**Core tables (same names as the PDF):** `student`, `instructor`, `consultation_request`, `status_log`, `notification`.

- Each consultation request has one required student and one required instructor. A student/instructor can have zero or many requests.
- Every status log belongs to one instructor and is cascade-deleted with that instructor (composition semantics).
- Every `notification` has a required foreign key `student_id` AND a **required** foreign key `log_id` referencing a `status_log`, exactly matching the PDF's notification relationship.
- Foreign keys are enabled on every SQLite connection, with NOT NULL / UNIQUE / CHECK, default values, and cascade rules.
- `consultation_request` has required date, start/end, status and creation timestamp. Time windows are stored as **integer minutes after midnight** (SQLite does not have a native `TIME` type), and date/timestamps as ISO strings. This differs physically from the PDF's generic `TIME` / `DATETIME` columns but preserves the intended values and comparison rules.
- `student.university_id` stores the ten-digit institutional ID separately from the integer auto-increment `student.student_id` primary key in the PDF.
- Additional fields `password_hash`, `password_salt`, `reason`, and `email` support local authentication and consultation workflows. These are implementation extensions.
- One **additional** table, `booking_notice`, stores booking-approval/decline notices without incorrectly setting a null `notification.log_id`. Status notifications remain strictly linked to a status log.
- An existing older SQLite database is migrated automatically without deleting bookings; older booking messages with no status log link are migrated to `booking_notice`.

## Test flow

1. Sign in as **Oliver**; check three instructor cards and create a request for a future day.
2. Try a second request to the same instructor; it must be rejected (FR-004).
3. Sign in as the selected instructor in an **incognito/private** browser session and confirm Oliver's request (FR-005).
4. From another student account, try booking the same confirmed time slot. It must be rejected (FR-004).
5. As the instructor, change availability to **In a Meeting**. Oliver should receive a status notification, and the warning is visible on his dashboard (FR-001, -002, -003).
6. Sign out, restart `START_HERE.bat`, and log in again. Requests and notifications should remain saved.

## Preserving an older local database

1. **Stop both versions** of the app.
2. Back up the old `data` folder.
3. Extract this release into a new folder.
4. **Before starting it**, copy the old `consultations.sqlite` file (and any related `-wal` / `-shm` files if present) to the new `data` folder, replacing the newly generated DB.
5. Launch `START_HERE.bat`. Any needed database migration runs on startup. Existing appointments should remain.

To start fresh, back up, close the app, delete `data/consultations.sqlite` (and any SQLite `-wal` and `-shm` files), and launch again; the six seeded accounts will be recreated automatically. This also deletes previous bookings, so do not reset without backing up.

## Files

- `START_HERE.bat` — Windows one-click launcher
- `app.py` — Python standard-library HTTP server, APIs and SQLite database migrations
- `data/consultations.sqlite` — generated automatically on first start, with 3 students and 3 instructors
- `static/index.html`, `static/app.js`, `static/style.css` — responsive interface, no frontend build/install
- `REQUIREMENTS_CHECKLIST.md` — detailed verification checklist for the midterm PDF

**Note:** This release is intended for **localhost or small classroom Railway demos**. Treat the sample accounts and data as test-only. Its session management, credentials and plain HTTP are not a substitute for a production security review.

## Login form validation (updated)

The **Sign in securely** button starts disabled and visually muted. It becomes enabled only after both the account ID/email and password fields contain non-whitespace text, disables again if either field is cleared, and stays disabled while a login request is processing. Incorrect credentials continue to show the existing error and allow a retry without refreshing.

## UX polish and stricter booking validation (this release)

- Fast 170–240 ms hover and selection transitions for role buttons, sidebar links, filters, status choices, and actions. Page entrances are animated **only on navigation**, not on every live-data update. A reduced-motion preference disables animation.
- Switching Student/Instructor does **not** rebuild the entire login page. It switches the field label and clears the previous account and password, with the selected icon and role highlighted.
- The login button stays disabled until both login fields have real input. The consultation submit button stays disabled until a valid date, future time slot, and nonblank reason (at most 500 characters) are present.
- Time slots that have already begun on the selected Philippine-local calendar day are disabled. The server also rejects requests for the past, regardless of browser-side validation. An instructor cannot confirm an outdated appointment.
- SQLite date/time type/format and nonblank-reason triggers now supplement the documented PDF constraints. **Old trigger definitions are replaced during startup** to fix an upgrade defect where older databases could allow a Pending booking to overlap a Confirmed booking.
- Each request remains scoped to exactly one student and instructor. Notifications remain linked to the correct student and status log.
- Optional: double-click `VERIFY_SYSTEM.bat` to check key database constraints in a temporary SQLite database **without changing any current bookings**.

**Validation performed:** All 6 logins, request ownership, booking conflict behavior, notifications, foreign keys, date/time checks, raw-SQL trigger enforcement, automatic migration preserving an existing booking, and desktop/mobile interaction states passed isolated tests. Desktop/mobile frontends were checked with mocked API data. Windows `START_HERE.bat` and actual performance under a school network were not tested in this environment. The PDF's 99.9% 24/7 uptime requirement remains unfulfilled on localhost.
