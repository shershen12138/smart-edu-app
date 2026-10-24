from .rosters import students_in


def roster_rows(work):
    """Latest attempt is authoritative; infrastructure failures are never zero marks."""
    latest = {}
    for entry in work.entries.select_related('student').order_by('-sequence', '-pk'):
        latest.setdefault(entry.student_id, entry)
    members = students_in(work.classroom)
    rows = [{'student': u, 'entry': latest.get(u.pk)} for u in members]
    graded = [r['entry'].total for r in rows if r['entry'] and r['entry'].status == 'done']
    max_score = work.max_score
    average_score = f'{sum(graded) / len(graded):.1f}' if graded else '—'
    stats = [
        ('在班学生', len(rows)),
        ('已提交', sum(bool(r['entry']) for r in rows)),
        ('已批阅', len(graded)),
        ('均分/总分', f'{average_score} / {max_score}'),
        ('最高分', f'{max(graded):.1f}' if graded else '—'),
        ('最低分', f'{min(graded):.1f}' if graded else '—'),
    ]
    return rows, stats


def score_distribution(work, rows):
    """Group latest graded scores by percentage so assignments with different totals compare cleanly."""
    buckets = [
        {'label': '90%～100%', 'minimum': 90, 'count': 0},
        {'label': '80%～89%', 'minimum': 80, 'count': 0},
        {'label': '70%～79%', 'minimum': 70, 'count': 0},
        {'label': '60%～69%', 'minimum': 60, 'count': 0},
        {'label': '60%以下', 'minimum': None, 'count': 0},
    ]
    graded_count = 0
    fallback_total = work.max_score
    for row in rows:
        entry = row['entry']
        if not entry or entry.status != 'done' or entry.total is None:
            continue
        total = entry.snapshot.get('max_score') or fallback_total
        if not total:
            continue
        percent = float(entry.total) * 100 / float(total)
        graded_count += 1
        for bucket in buckets:
            if bucket['minimum'] is None or percent >= bucket['minimum']:
                bucket['count'] += 1
                break
    for bucket in buckets:
        bucket['percent'] = round(bucket['count'] * 100 / graded_count, 1) if graded_count else 0
    return buckets, graded_count
