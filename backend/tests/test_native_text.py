"""PPT原生文本：隐藏页映射、完整段落、多栏不串行。"""
import os
import sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pptx import Presentation
from pptx.util import Inches
from app.services.ppt_parser import extract_native_texts


def test_hidden_slides_do_not_shift_pdf_page_numbers(tmp_path):
    prs=Presentation()
    for title in ('第一页','隐藏页','第三页'):
        slide=prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_textbox(0,0,Inches(3),Inches(1)).text=title
    prs.slides[1]._element.set('show','0')
    path=tmp_path/'hidden.pptx';prs.save(path)
    assert extract_native_texts(str(path))==['第一页','第三页']


def test_columns_stay_as_complete_text_frames(tmp_path):
    prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(0,0,Inches(3),Inches(2)).text='发现违规无人机\n触发黑飞告警'
    slide.shapes.add_textbox(Inches(5),0,Inches(3),Inches(2)).text='对已申报飞行任务\n进行航线管理'
    path=tmp_path/'columns.pptx';prs.save(path)
    assert extract_native_texts(str(path))==['发现违规无人机\n触发黑飞告警\n对已申报飞行任务\n进行航线管理']


def test_unsupported_or_invalid_input_falls_back(tmp_path):
    path=tmp_path/'bad.pptx';path.write_bytes(b'not a presentation')
    assert extract_native_texts(str(path))==[]
    assert extract_native_texts(str(tmp_path/'old.ppt'))==[]
