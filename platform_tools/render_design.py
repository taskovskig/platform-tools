def main():
    """Render the editable platform design as a shareable PDF. Requires reportlab."""
    import argparse
    from pathlib import Path
    import re
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted, Table, TableStyle, KeepTogether
    
    parser = argparse.ArgumentParser(description='Render a platform design Markdown document as PDF.')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    OUT = args.output
    OUT.parent.mkdir(parents=True, exist_ok=True)
    NAVY = colors.HexColor('#142B43')
    TEAL = colors.HexColor('#007F82')
    GRAY = colors.HexColor('#526474')
    LIGHT = colors.HexColor('#EDF3F6')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyCustom', fontName='Helvetica', fontSize=10, leading=13.5, textColor=NAVY, spaceAfter=8, allowWidows=0, allowOrphans=0))
    styles.add(ParagraphStyle(name='SectionCustom', fontName='Helvetica-Bold', fontSize=17, leading=21, textColor=NAVY, spaceBefore=16, spaceAfter=10, keepWithNext=True))
    styles.add(ParagraphStyle(name='SubCustom', fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=TEAL, spaceBefore=12, spaceAfter=7, keepWithNext=True))
    styles.add(ParagraphStyle(name='TableCustom', fontName='Helvetica', fontSize=8.1, leading=11, textColor=NAVY))
    styles.add(ParagraphStyle(name='BulletCustom', parent=styles['BodyCustom'], leftIndent=12, firstLineIndent=-9))
    styles.add(ParagraphStyle(name='CodeCustom', fontName='Courier', fontSize=7.4, leading=10, textColor=NAVY, backColor=LIGHT, borderPadding=10, spaceBefore=6, spaceAfter=12))
    styles.add(ParagraphStyle(name='CoverTitle', fontName='Helvetica-Bold', fontSize=34, leading=39, textColor=NAVY, spaceAfter=22))
    styles.add(ParagraphStyle(name='CoverSub', fontName='Helvetica', fontSize=15, leading=22, textColor=GRAY, spaceAfter=20))
    
    def inline(text):
        text=escape(text)
        text=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<link href="\2" color="#007F82">\1</link>', text)
        text=re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', text)
        text=re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
        return text
    
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1.2)
        canvas.line(42, 43, A4[0]-42, 43)
        canvas.setFillColor(GRAY)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(42, 29, 'PLATFORM ENGINEERING / Testkube sample')
        canvas.drawRightString(A4[0]-42, 29, str(doc.page))
        if doc.page > 1:
            canvas.setFont('Helvetica', 7.5)
            canvas.drawString(42, A4[1]-29, 'DESIGN, TRADEOFFS AND DELIVERY')
        canvas.restoreState()
    
    story=[Spacer(1,48), Paragraph('PLATFORM ENGINEERING CASE STUDY',styles['SubCustom']), Spacer(1,18), Paragraph('From source code<br/>to a supported<br/>developer workflow',styles['CoverTitle']), Paragraph('A Kubernetes platform design and local MVP<br/>for the Testkube sample application.',styles['CoverSub']),Spacer(1,20)]
    boxes=Table([[Paragraph('<b>01 / DEVELOP</b><br/><br/>Edit source.<br/>Get fast feedback.',styles['BodyCustom']), Paragraph('<b>02 / DELIVER</b><br/><br/>Build, deploy and test<br/>through one workflow.',styles['BodyCustom']),Paragraph('<b>03 / OPERATE</b><br/><br/>Diagnose failures.<br/>Recover deliberately.',styles['BodyCustom'])]], colWidths=[170,170,171])
    boxes.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),LIGHT),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),16),('BOTTOMPADDING',(0,0),(-1,-1),12),('LINEAFTER',(0,0),(1,0),2,colors.white)]))
    story += [boxes,Spacer(1,28),Paragraph('<b>Design stance</b><br/>Start with a reliable path for one team. Make production responsibilities explicit. Add platform components when a demonstrated need justifies their operational cost.',styles['BodyCustom']),Spacer(1,24),Paragraph('Includes requirements analysis, architecture, ownership, delivery controls, tradeoffs and an incremental roadmap. The repository contains the executable MVP, developer guide and separate validation evidence.',styles['BodyCustom']),PageBreak()]
    lines=args.input.read_text().splitlines()
    i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip() or line.startswith('# ') or line.startswith('**Senior Platform'): i+=1;continue
        if line.startswith('## '):
            story.append(Paragraph(inline(line[3:]),styles['SectionCustom']));i+=1;continue
        if line.startswith('### '):
            story.append(Paragraph(inline(line[4:]),styles['SubCustom']));i+=1;continue
        if line.startswith('```'):
            i+=1; block=[]
            while i<len(lines) and not lines[i].startswith('```'): block.append(lines[i]);i+=1
            story.append(Preformatted('\n'.join(block), styles['CodeCustom']));i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                row=[c.strip() for c in lines[i].strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+', c) for c in row): rows.append(row)
                i+=1
            data=[[Paragraph(inline(c),styles['TableCustom']) for c in row] for row in rows]
            for j,c in enumerate(rows[0]): data[0][j]=Paragraph('<b>'+inline(c)+'</b>',styles['TableCustom'])
            table=Table(data,colWidths=[511/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#D5E9EB')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,LIGHT]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,0),1,TEAL)]))
            story.extend([table,Spacer(1,12)]);continue
        if line.startswith('- ') or re.match(r'^\d+\. ',line):
            story.append(Paragraph(inline(line),styles['BulletCustom']));i+=1;continue
        para=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','```','- ')) and not re.match(r'^\d+\. ',lines[i]): para.append(lines[i]);i+=1
        paragraph = Paragraph(inline(' '.join(para)),styles['BodyCustom'])
        if para[0].startswith('The application is a small three-tier system'): paragraph.keepWithNext = True
        story.append(paragraph)
    SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=49,bottomMargin=58,title='Developer platform design - Testkube sample',author='Platform engineering case study').build(story,onFirstPage=footer,onLaterPages=footer)
    print(OUT)
