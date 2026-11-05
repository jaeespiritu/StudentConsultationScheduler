
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
# Railway automatically sets RAILWAY_VOLUME_MOUNT_PATH when a persistent volume is attached.
# All database writes must go there so appointments survive redeploys and restarts.
ON_RAILWAY = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_ID'))
DATA = Path(os.environ.get('SCHEDULER_DATA_DIR') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or str(ROOT / 'data'))
DB_FILE = DATA / 'consultations.sqlite'
HOST = '0.0.0.0' if ON_RAILWAY else '127.0.0.1'
PORT = int(os.environ.get('PORT', '8443'))
COOKIE_SECURE = ON_RAILWAY

LOCK = threading.RLock()
SESSIONS = {}
CHANGES = threading.Condition()
CHANGE_VERSION = 0

def broadcast():
    global CHANGE_VERSION
    with CHANGES:
        CHANGE_VERSION += 1
        CHANGES.notify_all()
SESSION_SECONDS = 8 * 3600
MANILA = timezone(timedelta(hours=8))
STATUS = ('Available', 'Unavailable', 'In a Meeting')
REQUEST_STATUSES = ('Pending', 'Confirmed', 'Declined', 'Cancelled')

# Demo accounts are pre-seeded with salted password *hashes*, not plaintext credentials.
STUDENTS = [
    ('9342832738', 'Oliver Aniate', '9342832738@ms.bulsu.edu.ph', '956e8fe75951e88ebc979ca99f8033ca', 'f2b0a7a9ef5a92dbc46fb4d7ee387d26b25d8d3fcf0a30bd3669064bafe0fed428493a53cb02a5fe21f1966094ecace442f2ddc6c88469f217430834076d58a2'),
    ('4944405311', 'Precious Abby De Castro', '4944405311@ms.bulsu.edu.ph', '2d53d3bb99bfd136ce09cfd3e3ad28c9', '4f19d4065120ad1c29173d489ad0423bc49b30bda165a6d1f5fab1631e918726799918595fda1d423962549fa0bf58b5f145bc11b43722cc73cefe91776df0c5'),
    ('9942988820', 'Jonathan Espiritu', '9942988820@ms.bulsu.edu.ph', 'd3e1f74a014612556b187b18dd79a0ed', '0b46573eb693830c055b61f4953e4f389b96b7b233c55126bc960545f2c7e1bfd9c19168f79ea21345b686ea2a2b5c68949d0bc7742df77c7cd645d12bb6ae42'),
]
INSTRUCTORS = [
    ('Dr. Monaliza Jimenez', 'monalizajimenez@ms.bulsu.edu.ph', '56838c6a7d5ec3a0f67df124e8643ad4', '96d7040b084cb1971ecf4eac32eab67d6c871d9965139fbe5a820b1d13571d390a2d9f722df2431fd015293d062d1ebbbc5a142e142fc9c03e0535bd247f2d7e'),
    ('Dr. Lech Walesa Navarra', 'lechwalesanavarra@ms.bulsu.edu.ph', '1b155da01e77b40f2600cb30e3094bb6', '6a51865642154af4909d0c5612389126526ca34f8c311a0af1f501991b6791a27b2d717094e5e0aa19f0b5863547ae0231a9379fa02530991ce87a4a0c0edab5'),
    ('Dr. Maria Lorena SP Villena', 'marialorenavillena@ms.bulsu.edu.ph', 'ad4868f0ca55a8d372ba8438aac723d0', 'd5880415e8958a9ec69fe58b39e9bf56667ae7402fea259538dbd56bd431b8df34d94c9f54f74e1ffd78a1f155f1d3d109ca21658232ab9283890f02552deedf'),
]

@contextmanager
def connect():
    conn = sqlite3.connect(DB_FILE, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 5000')
        with conn:
            yield conn
    finally:
        conn.close()


def password_parts(password):
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return salt.hex(), hashed.hex()


def verify_password(password, salt, hashed):
    try:
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64)
        return hmac.compare_digest(actual, bytes.fromhex(hashed))
    except (ValueError, TypeError):
        return False


def init_database():
    DATA.mkdir(parents=True, exist_ok=True)
    with LOCK, connect() as db:
        db.executescript('''
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS student (
          student_id INTEGER PRIMARY KEY AUTOINCREMENT,
          university_id TEXT NOT NULL UNIQUE,
          full_name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          program TEXT NOT NULL,
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS instructor (
          instructor_id INTEGER PRIMARY KEY AUTOINCREMENT,
          full_name TEXT NOT NULL,
          department TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          current_status TEXT NOT NULL DEFAULT 'Available'
            CHECK (current_status IN ('Available','Unavailable','In a Meeting')),
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS consultation_request (
          request_id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL REFERENCES student(student_id) ON DELETE CASCADE ON UPDATE CASCADE,
          instructor_id INTEGER NOT NULL REFERENCES instructor(instructor_id) ON DELETE CASCADE ON UPDATE CASCADE,
          request_date TEXT NOT NULL,
          start_time INTEGER NOT NULL,
          end_time INTEGER NOT NULL,
          reason TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'Pending'
            CHECK (status IN ('Pending','Confirmed','Declined','Cancelled')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CHECK(end_time > start_time)
        );
        CREATE INDEX IF NOT EXISTS idx_request_instructor_time
          ON consultation_request(instructor_id, request_date, start_time, end_time, status);
        CREATE INDEX IF NOT EXISTS idx_request_student
          ON consultation_request(student_id, instructor_id, status);
        CREATE TABLE IF NOT EXISTS status_log (
          log_id INTEGER PRIMARY KEY AUTOINCREMENT,
          instructor_id INTEGER NOT NULL REFERENCES instructor(instructor_id) ON DELETE CASCADE ON UPDATE CASCADE,
          previous_status TEXT NOT NULL,
          new_status TEXT NOT NULL,
          changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notification (
          notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL REFERENCES student(student_id) ON DELETE CASCADE ON UPDATE CASCADE,
          log_id INTEGER NOT NULL REFERENCES status_log(log_id) ON DELETE CASCADE ON UPDATE CASCADE,
          message TEXT NOT NULL,
          sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS booking_notice (
          notice_id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL REFERENCES student(student_id) ON DELETE CASCADE ON UPDATE CASCADE,
          request_id INTEGER REFERENCES consultation_request(request_id) ON DELETE CASCADE ON UPDATE CASCADE,
          message TEXT NOT NULL,
          sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1))
        );
        CREATE TRIGGER IF NOT EXISTS status_log_insert_values BEFORE INSERT ON status_log
        BEGIN
          SELECT RAISE(ABORT, 'Invalid instructor status change')
          WHERE NEW.previous_status NOT IN ('Available','Unavailable','In a Meeting')
             OR NEW.new_status NOT IN ('Available','Unavailable','In a Meeting');
        END;
        CREATE TRIGGER IF NOT EXISTS status_log_update_values BEFORE UPDATE ON status_log
        BEGIN
          SELECT RAISE(ABORT, 'Invalid instructor status change')
          WHERE NEW.previous_status NOT IN ('Available','Unavailable','In a Meeting')
             OR NEW.new_status NOT IN ('Available','Unavailable','In a Meeting');
        END;
        -- Replace historical trigger definitions on every startup; IF NOT EXISTS alone
        -- leaves older, weaker rules installed after an upgrade.
        DROP TRIGGER IF EXISTS prevent_duplicate_insert;
        DROP TRIGGER IF EXISTS prevent_duplicate_update;
        DROP TRIGGER IF EXISTS validate_request_values_insert;
        DROP TRIGGER IF EXISTS validate_request_values_update;
        -- Additional guards apply to direct database edits as well as the website.
        -- ISO-shaped dates, integral minute offsets, and nonblank purpose are mandatory.
        CREATE TRIGGER IF NOT EXISTS validate_request_values_insert
          BEFORE INSERT ON consultation_request
        BEGIN
          SELECT RAISE(ABORT, 'Invalid consultation date')
          WHERE typeof(NEW.request_date)!='text'
             OR NEW.request_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
             OR date(NEW.request_date) IS NULL
             OR date(NEW.request_date, '+0 days') != NEW.request_date;
          SELECT RAISE(ABORT, 'Invalid consultation time data')
          WHERE typeof(NEW.start_time)!='integer' OR typeof(NEW.end_time)!='integer';
          SELECT RAISE(ABORT, 'Consultation reason required')
          WHERE typeof(NEW.reason)!='text' OR length(trim(NEW.reason)) NOT BETWEEN 1 AND 500;
        END;
        CREATE TRIGGER IF NOT EXISTS validate_request_values_update
          BEFORE UPDATE OF request_date,start_time,end_time,reason ON consultation_request
        BEGIN
          SELECT RAISE(ABORT, 'Invalid consultation date')
          WHERE typeof(NEW.request_date)!='text'
             OR NEW.request_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
             OR date(NEW.request_date) IS NULL
             OR date(NEW.request_date, '+0 days') != NEW.request_date;
          SELECT RAISE(ABORT, 'Invalid consultation time data')
          WHERE typeof(NEW.start_time)!='integer' OR typeof(NEW.end_time)!='integer';
          SELECT RAISE(ABORT, 'Consultation reason required')
          WHERE typeof(NEW.reason)!='text' OR length(trim(NEW.reason)) NOT BETWEEN 1 AND 500;
        END;
        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_insert BEFORE INSERT ON consultation_request
        BEGIN
          SELECT RAISE(ABORT, 'Student already has an active request with this instructor')
            WHERE NEW.status IN ('Pending','Confirmed') AND EXISTS (
              SELECT 1 FROM consultation_request WHERE student_id=NEW.student_id AND instructor_id=NEW.instructor_id
                AND status IN ('Pending','Confirmed'));
          SELECT RAISE(ABORT, 'Time overlaps a confirmed consultation')
            WHERE NEW.status IN ('Pending','Confirmed') AND EXISTS (
              SELECT 1 FROM consultation_request WHERE instructor_id=NEW.instructor_id AND request_date=NEW.request_date
                AND status='Confirmed' AND start_time < NEW.end_time AND end_time > NEW.start_time);
          SELECT RAISE(ABORT, 'Invalid consultation time slot')
            WHERE NEW.start_time<480 OR NEW.end_time>1020 OR NEW.end_time-NEW.start_time<>30 OR NEW.start_time%30<>0;
        END;
        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_update
          BEFORE UPDATE OF status,student_id,instructor_id,request_date,start_time,end_time ON consultation_request
        BEGIN
          SELECT RAISE(ABORT, 'Student already has an active request with this instructor')
            WHERE NEW.status IN ('Pending','Confirmed') AND EXISTS (
              SELECT 1 FROM consultation_request WHERE request_id<>OLD.request_id AND student_id=NEW.student_id
                AND instructor_id=NEW.instructor_id AND status IN ('Pending','Confirmed'));
          SELECT RAISE(ABORT, 'Time overlaps a confirmed consultation')
            WHERE NEW.status IN ('Pending','Confirmed') AND EXISTS (
              SELECT 1 FROM consultation_request WHERE request_id<>OLD.request_id AND instructor_id=NEW.instructor_id
                AND request_date=NEW.request_date AND status='Confirmed'
                AND start_time < NEW.end_time AND end_time > NEW.start_time);
          SELECT RAISE(ABORT, 'Invalid consultation time slot')
            WHERE NEW.start_time<480 OR NEW.end_time>1020 OR NEW.end_time-NEW.start_time<>30 OR NEW.start_time%30<>0;
        END;
        ''')
        # Upgrade older local databases without dropping existing bookings or messages.
        info = db.execute("PRAGMA table_info(notification)").fetchall()
        log_column = next((col for col in info if col['name'] == 'log_id'), None)
        if log_column is not None and not log_column['notnull']:
            db.executescript('''
            INSERT INTO booking_notice(student_id,message,sent_at,is_read)
              SELECT student_id,message,sent_at,is_read FROM notification WHERE log_id IS NULL;
            CREATE TABLE notification_v3 (
              notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER NOT NULL REFERENCES student(student_id) ON DELETE CASCADE ON UPDATE CASCADE,
              log_id INTEGER NOT NULL REFERENCES status_log(log_id) ON DELETE CASCADE ON UPDATE CASCADE,
              message TEXT NOT NULL,
              sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1))
            );
            INSERT INTO notification_v3 SELECT * FROM notification WHERE log_id IS NOT NULL;
            DROP TABLE notification;
            ALTER TABLE notification_v3 RENAME TO notification;
            ''')
        for university_id, name, email, salt, hashed in STUDENTS:
            if not db.execute('SELECT 1 FROM student WHERE university_id=? OR lower(email)=?', (university_id, email)).fetchone():
                db.execute('INSERT INTO student (university_id,full_name,email,program,password_salt,password_hash) VALUES (?,?,?,?,?,?)',
                           (university_id, name, email, 'Computer Engineering', salt, hashed))
        for name, email, salt, hashed in INSTRUCTORS:
            if not db.execute('SELECT 1 FROM instructor WHERE lower(email)=?', (email,)).fetchone():
                db.execute('INSERT INTO instructor (full_name,department,email,password_salt,password_hash) VALUES (?,?,?,?,?)',
                           (name, 'Computer Engineering', email, salt, hashed))
        # Remove the obsolete generic demo student only when no history would be lost.
        db.execute('''DELETE FROM student WHERE university_id='20260001'
                      AND NOT EXISTS (SELECT 1 FROM consultation_request c WHERE c.student_id=student.student_id)''')
        db.execute('PRAGMA user_version = 3')
    print('SQLite database is ready.', flush=True)


class Problem(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def day_today():
    return datetime.now(MANILA).strftime('%Y-%m-%d')


def parse_date(date):
    if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise Problem(400, 'Choose a valid date.')
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        raise Problem(400, 'Choose a valid calendar date.')
    if date < day_today():
        raise Problem(400, 'Choose today or a future date (Philippine time).')
    return date


def check_future_slot(date, start):
    """Prevent bookings into a same-day time slot that has already started."""
    local_now = datetime.now(MANILA)
    if date == local_now.strftime('%Y-%m-%d') and start <= local_now.hour * 60 + local_now.minute:
        raise Problem(400, 'This time slot has already started. Please choose a later time or date.')


def parse_time(value):
    match = re.fullmatch(r'(1[0-2]|[1-9]):([0-5]\d) (AM|PM)', value) if isinstance(value, str) else None
    if match is None:
        raise Problem(400, 'Choose a valid consultation time.')
    hour = int(match.group(1)) % 12 + (12 if match.group(3) == 'PM' else 0)
    return hour * 60 + int(match.group(2))


def show_time(minutes):
    hour, mins = divmod(minutes, 60)
    return f'{hour % 12 or 12}:{mins:02d} {"PM" if hour >= 12 else "AM"}'


def visible_user(row, role):
    item = {'role': role, 'name': row['full_name'], 'email': row['email']}
    if role == 'student':
        item.update(studentId=row['university_id'], program=row['program'])
    else:
        item['department'] = row['department']
    return item


JOINED = '''SELECT c.*, s.full_name AS student_name, i.full_name AS instructor_name,
                  i.department AS department
           FROM consultation_request c
           JOIN student s ON s.student_id=c.student_id
           JOIN instructor i ON i.instructor_id=c.instructor_id'''


def display_consultation(row, role):
    when = datetime.strptime(row['request_date'], '%Y-%m-%d').strftime('%a, %b %-d, %Y') if sys.platform != 'win32' else datetime.strptime(row['request_date'], '%Y-%m-%d').strftime('%a, %b %#d, %Y')
    notes = {
        'Pending': 'Awaiting instructor approval. Do not travel yet.',
        'Confirmed': 'Confirmed. Check instructor availability before coming to campus.',
        'Declined': 'Declined. You may submit another request.',
        'Cancelled': 'Cancelled. You may submit another request.'
    }
    return {'id': str(row['request_id']), 'name': row['instructor_name'] if role == 'student' else row['student_name'],
            'date': f'{when} · {show_time(row["start_time"])}–{show_time(row["end_time"])}',
            'detail': row['department'], 'reason': row['reason'],
            'place': 'Faculty / Professors Lounge · In person',
            'note': notes[row['status']], 'status': row['status']}


def pair(row):
    return {'student': display_consultation(row, 'student'), 'instructor': display_consultation(row, 'instructor')}


def require_role(user, role):
    if user['role'] != role:
        raise Problem(403, 'This action is not allowed for your account.')


def notify(db, student_id, text, log_id):
    db.execute('INSERT INTO notification(student_id,log_id,message) VALUES (?,?,?)', (student_id, log_id, text))

def booking_notify(db, student_id, request_id, text):
    db.execute('INSERT INTO booking_notice(student_id,request_id,message) VALUES (?,?,?)', (student_id, request_id, text))


def api(method, url, body, user, token):
    route = urlparse(url).path
    query = parse_qs(urlparse(url).query)
    if method == 'GET' and route == '/api/health':
        with connect() as health_db:
            health_db.execute('SELECT 1').fetchone()
        return 200, {'status': 'ok', 'database': 'SQLite'}, None
    if method == 'POST' and route == '/api/auth/login':
        role, identifier, password = body.get('role'), body.get('identifier'), body.get('password')
        if role not in ('student', 'instructor') or not isinstance(identifier, str) or not isinstance(password, str) or not identifier.strip() or not password:
            raise Problem(400, 'Enter a valid account and password.')
        key = identifier.strip().lower()
        email = key if '@' in key else f'{key}@ms.bulsu.edu.ph'
        with connect() as db:
            if role == 'student':
                record = db.execute('SELECT * FROM student WHERE university_id=? OR lower(email)=?', (key, email)).fetchone()
                id_column = 'student_id'
            else:
                record = db.execute('SELECT * FROM instructor WHERE lower(email)=?', (email,)).fetchone()
                id_column = 'instructor_id'
        if record is None or not verify_password(password, record['password_salt'], record['password_hash']):
            raise Problem(401, 'Account or password is incorrect.')
        token = secrets.token_hex(32)
        SESSIONS[token] = {'id': record[id_column], 'role': role,
                           'expires': time.time() + SESSION_SECONDS,
                           'display': visible_user(record, role)}
        cookie = f'scheduler_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}' + ('; Secure' if COOKIE_SECURE else '')
        return 200, {'user': SESSIONS[token]['display']}, cookie
    if method == 'GET' and route == '/api/auth/me':
        return 200, {'user': user['display'] if user else None}, None
    if method == 'POST' and route == '/api/auth/logout':
        if token:
            SESSIONS.pop(token, None)
        return 204, None, 'scheduler_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + ('; Secure' if COOKIE_SECURE else '')
    if not user:
        raise Problem(401, 'Please sign in to continue.')
    with LOCK, connect() as db:
        uid, role = user['id'], user['role']
        if method == 'GET' and route == '/api/instructors':
            rows = db.execute('SELECT instructor_id AS id,full_name AS name,department,current_status AS status FROM instructor ORDER BY full_name').fetchall()
            return 200, [dict(r) for r in rows], None
        if method == 'GET' and route == '/api/availability':
            instructor_id = uid if role == 'instructor' else (query.get('instructorId') or [''])[0]
            try:
                instructor_id = int(instructor_id)
            except (TypeError, ValueError):
                raise Problem(400, 'Choose an instructor.')
            row = db.execute('SELECT * FROM instructor WHERE instructor_id=?', (instructor_id,)).fetchone()
            if not row:
                raise Problem(404, 'Instructor not found.')
            return 200, {'status': row['current_status'], 'instructor': {'name': row['full_name'], 'department': row['department']}}, None
        if method == 'PUT' and route == '/api/availability':
            require_role(user, 'instructor')
            status = body.get('status')
            if status not in STATUS:
                raise Problem(400, 'Invalid status.')
            with db:
                previous = db.execute('SELECT current_status,full_name FROM instructor WHERE instructor_id=?', (uid,)).fetchone()
                if previous['current_status'] != status:
                    db.execute('UPDATE instructor SET current_status=? WHERE instructor_id=?', (status,uid))
                    log = db.execute('INSERT INTO status_log (instructor_id,previous_status,new_status) VALUES (?,?,?)',
                                     (uid,previous['current_status'],status)).lastrowid
                    affected = db.execute('''SELECT DISTINCT student_id FROM consultation_request
                                             WHERE instructor_id=? AND status='Confirmed' AND request_date >= ?''',
                                          (uid, day_today())).fetchall()
                    for recipient in affected:
                        notify(db, recipient['student_id'],
                               f'{previous["full_name"]} changed availability from {previous["current_status"]} to {status}. Please check before traveling to campus.', log)
            broadcast()
            return 200, {'status': status}, None
        if method == 'GET' and route == '/api/consultations':
            column = 'c.student_id' if role == 'student' else 'c.instructor_id'
            rows = db.execute(f'{JOINED} WHERE {column}=? ORDER BY c.created_at DESC,c.request_id DESC', (uid,)).fetchall()
            return 200, [display_consultation(r,role) for r in rows], None
        if method == 'POST' and route == '/api/consultations':
            require_role(user,'student')
            date = parse_date(body.get('date'))
            start, end = parse_time(body.get('start')), parse_time(body.get('end'))
            if end - start != 30 or start < 8 * 60 or end > 17 * 60 or start % 30 != 0:
                raise Problem(400, 'Choose one 30-minute slot between 8 AM and 5 PM.')
            check_future_slot(date, start)
            reason = body.get('reason')
            if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 500:
                raise Problem(400, 'Enter a reason (1–500 characters).')
            try:
                instructor_id = int(body.get('instructorId'))
            except (ValueError,TypeError):
                raise Problem(400,'Choose an instructor.')
            with db:
                chosen = db.execute('SELECT instructor_id FROM instructor WHERE instructor_id=?', (instructor_id,)).fetchone()
                if not chosen:
                    raise Problem(404,'Selected instructor was not found.')
                duplicate = db.execute('''SELECT 1 FROM consultation_request WHERE student_id=? AND instructor_id=?
                                          AND status IN ('Pending','Confirmed') LIMIT 1''', (uid,instructor_id)).fetchone()
                if duplicate:
                    raise Problem(409,'You already have a Pending or Confirmed request with this instructor. Cancel it or wait for its outcome.')
                conflict = db.execute('''SELECT 1 FROM consultation_request WHERE instructor_id=? AND request_date=?
                                         AND status='Confirmed' AND start_time < ? AND end_time > ? LIMIT 1''',
                                      (instructor_id,date,end,start)).fetchone()
                if conflict:
                    raise Problem(409,'This time overlaps another confirmed consultation. Choose a different time.')
                request_id = db.execute('''INSERT INTO consultation_request
                      (student_id,instructor_id,request_date,start_time,end_time,reason) VALUES (?,?,?,?,?,?)''',
                      (uid,instructor_id,date,start,end,reason.strip())).lastrowid
                row = db.execute(f'{JOINED} WHERE c.request_id=?', (request_id,)).fetchone()
            broadcast()
            return 201, pair(row), None
        status_match = re.fullmatch(r'/api/consultations/(\d+)/status',route)
        if method == 'PATCH' and status_match:
            request_id = int(status_match.group(1))
            status = body.get('status')
            if status not in ('Confirmed','Declined','Cancelled'):
                raise Problem(400,'Invalid request status.')
            if role == 'student' and status != 'Cancelled':
                raise Problem(403,'Only an instructor can approve or decline.')
            if role == 'instructor' and status == 'Cancelled':
                raise Problem(403,'Only students can cancel their requests.')
            with db:
                row = db.execute(f'{JOINED} WHERE c.request_id=?',(request_id,)).fetchone()
                if row is None or row['student_id' if role=='student' else 'instructor_id'] != uid:
                    raise Problem(404,'Consultation not found.')
                if (role == 'instructor' and row['status'] != 'Pending') or (role == 'student' and row['status'] not in ('Pending','Confirmed')):
                    raise Problem(409,'This request can no longer be changed.')
                if status == 'Confirmed':
                    check_future_slot(row['request_date'], row['start_time'])
                    if row['request_date'] < day_today():
                        raise Problem(409, 'Past consultations cannot be confirmed.')
                    conflict = db.execute('''SELECT 1 FROM consultation_request WHERE request_id<>? AND instructor_id=?
                                             AND request_date=? AND status='Confirmed' AND start_time < ? AND end_time > ? LIMIT 1''',
                                          (request_id,row['instructor_id'],row['request_date'],row['end_time'],row['start_time'])).fetchone()
                    if conflict:
                        raise Problem(409,'A consultation is already confirmed for this time slot.')
                db.execute('UPDATE consultation_request SET status=? WHERE request_id=?',(status,request_id))
                if role == 'instructor':
                    verb = 'confirmed' if status == 'Confirmed' else 'declined'
                    booking_notify(db,row['student_id'],request_id,f'{row["instructor_name"]} {verb} your consultation on {row["request_date"]} '
                           f'({show_time(row["start_time"])}–{show_time(row["end_time"])}).')
                result = db.execute(f'{JOINED} WHERE c.request_id=?',(request_id,)).fetchone()
            broadcast()
            return 200, pair(result), None
        if method == 'GET' and route == '/api/notifications':
            require_role(user,'student')
            rows = db.execute('''
              SELECT 'status-'||notification_id AS id,message,sent_at AS sentAt,is_read AS isRead
                FROM notification WHERE student_id=?
              UNION ALL
              SELECT 'booking-'||notice_id AS id,message,sent_at AS sentAt,is_read AS isRead
                FROM booking_notice WHERE student_id=?
              ORDER BY sentAt DESC,id DESC LIMIT 150
            ''',(uid,uid)).fetchall()
            return 200, [dict(id=str(r['id']), message=r['message'], sentAt=r['sentAt'], isRead=bool(r['isRead'])) for r in rows], None
        if method == 'POST' and route == '/api/notifications/read-all':
            require_role(user,'student')
            with db:
                db.execute('UPDATE notification SET is_read=1 WHERE student_id=?',(uid,))
                db.execute('UPDATE booking_notice SET is_read=1 WHERE student_id=?',(uid,))
            broadcast()
            return 204,None,None
    raise Problem(404,'API route not found.')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        if not self.path.startswith('/api/health'):
            super().log_message(format,*args)

    def send_json(self,code,payload,cookie=None):
        raw = b'' if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(raw)))
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def current_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
        except Exception:
            return None,None
        token = cookie['scheduler_session'].value if 'scheduler_session' in cookie else None
        user = SESSIONS.get(token)
        if user and user['expires'] <= time.time():
            SESSIONS.pop(token,None)
            return None,None
        return user,token

    def stream_events(self):
        # Server-Sent Events make status and approval changes visible immediately in open browsers.
        user, token = self.current_session()
        if not user:
            self.send_json(401, {'error': 'Please sign in.'})
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        try:
            self.wfile.write(b': connected\n\n')
            self.wfile.flush()
            seen = CHANGE_VERSION
            while user['expires'] > time.time() and token in SESSIONS:
                with CHANGES:
                    CHANGES.wait_for(lambda: CHANGE_VERSION != seen, timeout=15)
                    fresh = CHANGE_VERSION
                if fresh != seen:
                    seen = fresh
                    self.wfile.write(b'event: change\ndata: update\n\n')
                else:
                    self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self.close_connection = True

    def handle_request(self):
        path = urlparse(self.path).path
        if path == '/api/events' and self.command == 'GET':
            self.stream_events()
            return
        if path.startswith('/api/'):
            if self.command not in ('GET','POST','PUT','PATCH'):
                self.send_json(405, {'error':'Method not allowed.'})
                return
            # CSRF defense: browsers may only mutate data from this same site.
            # Localhost and HTTPS Railway domains both work without a hardcoded URL.
            if self.command != 'GET':
                origin = self.headers.get('Origin')
                if origin:
                    source = urlparse(origin)
                    host = self.headers.get('Host', '').lower()
                    if source.scheme not in ('http', 'https') or source.netloc.lower() != host:
                        raise Problem(403, 'Requests must come from this application.')
            if self.command != 'GET':
                try:
                    length = int(self.headers.get('Content-Length','0'))
                except ValueError:
                    raise Problem(400,'Invalid request body.')
                if length > 16384 or length < 0:
                    raise Problem(413,'Request body is too large.')
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw) if raw else {}
                except (ValueError,UnicodeDecodeError):
                    raise Problem(400,'Request must contain valid JSON.')
                if not isinstance(body,dict):
                    raise Problem(400,'Invalid request body.')
            else:
                body = {}
            user,token = self.current_session()
            code,response,set_cookie = api(self.command,self.path,body,user,token)
            self.send_json(code,response,set_cookie)
            return
        if self.command != 'GET':
            self.send_error(405,'Method not allowed')
            return
        file = STATIC / (unquote(path).lstrip('/') if path != '/' else 'index.html')
        try:
            resolved = file.resolve()
            if not resolved.is_relative_to(STATIC.resolve()) or not resolved.is_file():
                self.send_error(404,'Not found')
                return
            contents = resolved.read_bytes()
            mime = mimetypes.guess_type(str(resolved))[0] or 'application/octet-stream'
            if str(resolved).endswith('.js'): mime='application/javascript'
            self.send_response(200)
            self.send_header('Content-Type',mime+'; charset=utf-8' if mime.startswith(('text/','application/javascript','application/json')) else mime)
            self.send_header('Content-Length',str(len(contents)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            self.wfile.write(contents)
        except OSError:
            self.send_error(404,'Not found')

    def do_GET(self): self._guarded()
    def do_POST(self): self._guarded()
    def do_PUT(self): self._guarded()
    def do_PATCH(self): self._guarded()

    def _guarded(self):
        try:
            self.handle_request()
        except Problem as ex:
            self.send_json(ex.code,{'error':ex.message})
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            self.send_json(500,{'error':'A server error occurred. Please try again.'})


def main():
    if sys.version_info < (3,9):
        sys.exit('Python 3.9 or newer is required.')
    if ON_RAILWAY and not (os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or os.environ.get('SCHEDULER_DATA_DIR')):
        print('WARNING: No Railway persistent volume detected. SQLite changes would be lost after redeploy!', flush=True)
    init_database()
    try:
        server = ThreadingHTTPServer((HOST,PORT),Handler)
        server.daemon_threads = True
    except OSError as ex:
        print(f'Cannot start server on {HOST}:{PORT}: {ex}', flush=True)
        sys.exit(1)
    print('\nStudent Consultation Scheduler is running.',flush=True)
    print(f'Listening on {HOST}:{PORT}',flush=True)
    if not ON_RAILWAY:
        print('Keep this window open. Press Ctrl+C to stop.\n',flush=True)
        threading.Timer(1.0, lambda: webbrowser.open(f'http://{HOST}:{PORT}')).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print('\nStopped.',flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
