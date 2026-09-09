"""从原始PPTX刷新可见页文本；默认只预览，应用前备份并防止覆盖并发更新。"""
import argparse
import json
import os
import sys
from pathlib import Path
from sqlalchemy import update, text as sql_text
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal
from app.models import PPTFile, PPTPage
from app.services.ppt_parser import extract_native_texts


def normalized(value):
    return ''.join(c for c in value if c.isalnum())


def refresh(backup_path=None):
    changes=[]
    with SessionLocal() as db:
        for file in db.query(PPTFile).all():
            texts=extract_native_texts(file.file_path)
            if len(texts)!=file.page_count:
                continue
            for page in file.pages:
                if not 1<=page.page_no<=len(texts):
                    continue
                new_text=texts[page.page_no-1]
                old_text=page.text or ''
                if (not normalized(page.title or '') or normalized(page.title) not in normalized(new_text)
                    or len(new_text.strip())<max(1,len(old_text.strip())*.7) or new_text==old_text):
                    continue
                changes.append({'id':page.id,'file_id':file.id,'page_no':page.page_no,
                                'text':old_text,'new_text':new_text})
        if backup_path is None:
            return {'eligible_pages':len(changes),'applied':False}
        # exclusive + 0600：备份不能覆盖旧文件，也不公开素材内容。
        fd=os.open(str(backup_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as output:
            json.dump(changes,output,ensure_ascii=False)
        changed=0
        for row in changes:
            result=db.execute(update(PPTPage).where(
                PPTPage.id==row['id'],PPTPage.file_id==row['file_id'],
                PPTPage.page_no==row['page_no'],PPTPage.text==row['text'],
            ).values(text=row['new_text'],text_tsv=sql_text(
                "to_tsvector('simple', coalesce(title,'') || ' ' || :new_page_text)"
            )),{'new_page_text':row['new_text']})
            changed+=result.rowcount
        db.commit()
        return {'eligible_pages':len(changes),'updated_pages':changed,'applied':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if args.apply and args.backup is None:
        parser.error('--apply requires --backup')
    print(json.dumps(refresh(args.backup if args.apply else None),ensure_ascii=False))
