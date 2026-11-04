# Changes — UX and constraint audit

## User interface

- Smooth short selection, button, card, filter, toast, and navigation animations.
- Respects operating-system **Reduce motion** accessibility setting.
- Keeps Student and Instructor icons (graduation cap and briefcase) from the requested login reference.
- Switching sign-in roles updates in place without reloading the whole form.
- Prevents submitting blank login forms and invalid consultation requests.
- Shows live remaining-character guidance for consultation reasons.
- Disables elapsed consultation slots on the current date, using Philippine time.
- Delays background redraws while editing to avoid unexpectedly erasing an active input.

## Backend/database fixes

- Blocks same-day past appointment submissions server-side, not just with browser rules.
- Prevents instructors from approving appointments whose time is already in the past.
- Adds SQL triggers for structurally valid date/time fields and nonblank reasons.
- **Repairs older SQLite triggers on upgrade** so Pending bookings cannot overlap previously Confirmed time slots (FR-004).
- Preserves old appointment data during migration; no table reset is required.
- Makes a live notification stream terminate when its session is logged out.

## Verification

- Six logins: successful.
- Role-based consultation access and approval restrictions: successful.
- Invalid date/time, blank purpose, duplicates, confirmed-slot overlaps: rejected.
- Status-change notifications and required status-log foreign key: verified.
- Fresh SQLite database integrity and foreign key checks: passed.
- Existing database migration preserves a confirmed booking and updates its triggers.
- Desktop and mobile interactive form states: passed in isolated mock browser.
- Respect for reduced-motion preference: verified.

## Known limits

- This is a localhost-only Python+SQLite classroom project. Python 3.9+ must already exist.
- No Windows GUI integration test of `START_HERE.bat` was possible in this environment.
- Live SSE performance is not a formal guarantee of delivery within five seconds across networks.
- 99.9% term uptime cannot be demonstrated on an ordinary localhost computer.
