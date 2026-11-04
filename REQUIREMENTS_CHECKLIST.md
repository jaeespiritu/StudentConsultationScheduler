# Midterm Mini-SRS alignment checklist

Reference: **MT LAB SD.pdf** (6 pages), "Student Consultation Scheduler". This checklist describes the local features and the remaining monitoring and uptime requirements when deployed to Railway.

| Source section | Expected behavior / constraint | Implementation | Status |
| --- | --- | --- | --- |
| P1 / problem | Prevent students arriving when an instructor is unexpectedly unavailable | Live status cards, explicit not-available warning on a confirmed student's dashboard, saved notification history | Implemented locally |
| P2 / scope | Student digital scheduling, availability, notifications; instructor status updates and approvals | Student/instructor role-specific views | Implemented |
| P2 / exclusions | No grades, classes, enrollment, attendance, video consultations | No such modules | Respected |
| FR-001 | 3 exact availability values | SQLite CHECK, role-protected PUT, `status_log` | Implemented, tested |
| FR-002 | Notify only affected students with Confirmed bookings when status changes | `notification` rows with required status-log FK, connected SSE and inbox | Implemented for local browser/in-app notifications |
| FR-003 | Show each instructor's live status | Dashboard and SSE changes, 4s polling fallback | Implemented for local browser |
| FR-004 | Reject overlap with existing Confirmed instructor slot; reject second active request from same student/instructor | API check on creation and approval plus SQL triggers | Implemented, tested |
| FR-005 | Instructor approves Pending before Confirmed | Role + ownership checks | Implemented, tested |
| NFR-001 | <=5 seconds notification, when student has active internet | SSE immediate trigger, 4s fallback; observed SSE update well under 1 second in isolated local test | Mechanism implemented; formal timing guarantee not established |
| NFR-002 | Browser access 24/7, >=99.9% academic term uptime | Railway deployment supports remote access with a persistent database volume; 24/7/99.9% uptime still requires monitoring and evidence | **Not yet verified**: Railway deployment is configured, but guaranteed 99.9% uptime requires measurement and an appropriate service plan |
| P3 / 5 UML classes | Student, Instructor, ConsultationRequest, StatusLog, Notification | Corresponding persistent SQLite tables and API behavior | Functionally mapped (Python uses DB-backed handlers, not explicit OO classes) |
| P3 / associations | Student 1→0..* request, Instructor 1→0..* request, Instructor 1→0..* status log, log 1→0..* notification, student 1→0..* notification | Foreign keys and relationships | Implemented |
| P4-5 / primary and foreign keys | Auto-increment PK, NOT NULL FKs, cascade delete/update, valid status CHECK, time ordering, unique email | SQLite schema + triggers, foreign_keys ON | Implemented semantically, with native SQLite representations |
| P4 / `notification.log_id` | NOT NULL foreign key | `notification.log_id` NOT NULL; booking decisions use separate extension table | Implemented in clean DB and migrated old DB |
| P6 / consistency | Same nouns and states across requirement/UI/database | `Pending`, `Confirmed`, `Declined`, `Cancelled`; `Available`, `Unavailable`, `In a Meeting` | Implemented |

**Clarifications / implementation differences:** In SQLite, `DATE`, `TIME` and `DATETIME` do not provide strict native date/time behavior, so the application stores ISO date text, minutes-since-midnight INTEGER start/end times, and ISO timestamp text. There is an additional `booking_notice` table for booking-decision messages. The student university ID is stored separately from the database's autoincrement PK. The interface does not expose class schedules, coursework or university administration. On Railway the site can be accessed remotely, but no claim of meeting 99.9% uptime is made without monitoring the actual hosted deployment.

### Verified adjustments in this release

- **FR-004 migration fix:** Existing SQLite installations used to retain their older trigger logic because `CREATE TRIGGER IF NOT EXISTS` would skip a replacement. Startup now drops and rebuilds only the consultation-validation triggers. A direct SQL insert of a `Pending` request into an occupied `Confirmed` instructor slot is rejected on both new and upgraded databases. Existing appointments are not deleted.
- **Booking data safeguards:** Consultation dates must be ISO-shaped valid dates; start/end values must be integer minute offsets; consultation reasons cannot be empty or whitespace-only. The API validates actual calendar dates and blocks a time slot that has already started on the day of booking (Philippine time). A confirm action is rejected for an outdated slot.
- **UX validation:** Login and booking submission buttons use disabled states until required fields are satisfied, with clear visual states. Screen transitions use short motion, and reduced-motion settings suppress those animations. These usability rules supplement rather than replace FR-001–FR-005.
- **Testing scope:** Automated backend checks and a separate mocked-browser interaction test passed. All six accounts remain preloaded, database integrity and foreign keys are valid, and the Windows launcher still requires only already-installed Python 3.9+. NFR-001 is not a hard network guarantee; NFR-002 still requires hosted uptime monitoring and cannot be guaranteed on the Free/Trial plan.
