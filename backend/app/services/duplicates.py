"""Conservative, incremental duplicate suggestions; never delete automatically."""
import re
from collections import Counter
from sqlalchemy import text as sql
from ..models import PPTPage, DuplicatePair


def text_overlap(a, b):
    def grams(text):
        text = re.sub(r'[^\w\u4e00-\u9fff]', '', (text or '').lower())
        return Counter(text[i:i+3] for i in range(len(text)-2))
    x,y=grams(a),grams(b)
    if not x or not y:
        return 0.0
    return 2 * sum((x & y).values()) / (sum(x.values()) + sum(y.values()))


def duplicate_reason(page, other, similarity):
    if page.image_hash and page.image_hash == other['image_hash']:
        return '页面图像完全一致'
    # Same theme/template is insufficient. Require independently strong content overlap.
    if similarity >= .975 and min(len(page.text or ''),len(other['text'] or '')) >= 40:
        if text_overlap(page.text, other['text']) >= .90:
            return '语义与正文内容均高度相似'
    return None


def detect(db, run):
    pages = db.query(PPTPage).filter(PPTPage.id.in_(run.page_ids)).all()
    if any(p.embedding_status != 'done' or p.embedding is None for p in pages):
        run.duplicate_status = 'waiting_vectors'
        return
    for p in pages:
        # Exact images are also checked, including older pages without vectors.
        candidates = db.execute(sql('''
            SELECT id, text, image_hash,
                   CASE WHEN embedding IS NULL THEN 0 ELSE 1 - (embedding <=> CAST(:vec AS vector)) END AS score
            FROM ppt_pages
            WHERE id <= :baseline AND id != :pid
              AND (image_hash = :hash AND image_hash != '' OR
                   embedding IS NOT NULL AND 1 - (embedding <=> CAST(:vec AS vector)) >= 0.975)
            ORDER BY id
        '''), {'vec':str(list(map(float,p.embedding))), 'baseline':run.baseline_page_id,
               'pid':p.id, 'hash':p.image_hash or ''}).mappings().all()
        for other in candidates:
            reason = duplicate_reason(p, other, float(other['score']))
            if reason and not db.query(DuplicatePair).filter_by(new_page_id=p.id,old_page_id=other['id']).first():
                db.add(DuplicatePair(run_id=run.id,new_page_id=p.id,old_page_id=other['id'],
                                     similarity=1 if reason == '页面图像完全一致' else float(other['score']),reason=reason))
    run.duplicate_status = 'done'
