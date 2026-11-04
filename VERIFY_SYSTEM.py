"""Offline regression checks. Uses a throwaway SQLite database; never edits your live data."""
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import app


def must_reject(db, statement, params):
    try:
        db.execute(statement, params)
    except sqlite3.IntegrityError:
        return
    raise AssertionError('Expected SQLite to reject an invalid change.')


def main():
    with tempfile.TemporaryDirectory(prefix='scheduler_verify_') as temporary:
        app.DATA = Path(temporary)
        app.DB_FILE = app.DATA / 'consultations.sqlite'
        app.init_database()
        with app.connect() as db:
            assert db.execute('SELECT count(*) FROM student').fetchone()[0] == 3
            assert db.execute('SELECT count(*) FROM instructor').fetchone()[0] == 3
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            date = (datetime.now(app.MANILA) + timedelta(days=3)).strftime('%Y-%m-%d')
            student, another = [r[0] for r in db.execute('SELECT student_id FROM student ORDER BY student_id LIMIT 2')]
            teacher = db.execute('SELECT instructor_id FROM instructor LIMIT 1').fetchone()[0]
            insert = '''INSERT INTO consultation_request
              (student_id,instructor_id,request_date,start_time,end_time,reason,status)
              VALUES (?,?,?,?,?,?,?)'''
            db.execute(insert, (student, teacher, date, 600, 630, 'Test request', 'Confirmed'))
            must_reject(db, insert, (student, teacher, date, 660, 690, 'Another active request', 'Pending'))
            must_reject(db, insert, (another, teacher, date, 600, 630, 'Overlaps confirmed', 'Pending'))
            must_reject(db, insert, (another, teacher, '2026-02-30', 660, 690, 'Bad date', 'Pending'))
            must_reject(db, insert, (another, teacher, date, 'invalid', 690, 'Wrong type', 'Pending'))
            must_reject(db, insert, (another, teacher, date, 660, 690, '  ', 'Pending'))
            must_reject(db, insert, (another, 999999, date, 660, 690, 'Missing teacher', 'Pending'))
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print('\nPASS: Six accounts, required foreign keys, unique active booking,')
    print('      no overlap with confirmed times, valid date/time and nonblank reason.')
    print('Checked a temporary database. Your project records were not changed.')


if __name__ == '__main__':
    main()
