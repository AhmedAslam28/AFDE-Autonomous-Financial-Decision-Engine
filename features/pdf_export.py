"""
features/pdf_export.py

Generate a professional PDF report using reportlab.
Pure Python — no system dependencies (no GTK, Cairo, or wkhtmltopdf needed).
Works on Windows, Mac, and Linux identically.
"""
from __future__ import annotations
from datetime import datetime
import io

# ── Colour palette (RGB 0-1) ──────────────────────────────────────
def _hex(h: str):
    """Convert hex colour to reportlab RGB tuple (0-1 range)."""
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

C = {
    'bg':      _hex('0A0A0F'),
    'panel':   _hex('111827'),
    'border':  _hex('1E293B'),
    'text':    _hex('CBD5E1'),
    'muted':   _hex('4B5563'),
    'dim':     _hex('374151'),
    'buy':     _hex('22C55E'),
    'sell':    _hex('EF4444'),
    'hold':    _hex('F59E0B'),
    'blue':    _hex('3B82F6'),
    'pink':    _hex('EC4899'),
    'green':   _hex('22C55E'),
    'purple':  _hex('8B5CF6'),
    'navy':    _hex('1D4ED8'),
    'white':   _hex('E2E8F0'),
    'gold':    _hex('FCD34D'),
    'teal':    _hex('22D3EE'),
}

AGENT_COLORS = {
    'fundamental': C['blue'],
    'sentiment':   C['pink'],
    'insider':     C['green'],
    'macro':       C['purple'],
}

def _decision_color(decision: str):
    return {'BUY':C['buy'],'SELL':C['sell'],'HOLD':C['hold'],
            'BULLISH':C['buy'],'BEARISH':C['sell'],'NEUTRAL':C['hold']}.get(
        str(decision).upper(), C['muted'])


def generate_pdf(result: dict) -> bytes:
    """
    Generate a PDF report from an analysis result dict.
    Returns raw PDF bytes ready to send as HTTP response.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import Color, HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib import colors

    # ── Setup ──────────────────────────────────────────────────────
    buf    = io.BytesIO()
    W, H   = A4
    margin = 20 * mm

    def rgb(*t): return Color(t[0], t[1], t[2])

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin)

    # ── Styles ─────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def sty(name, **kw):
        base = kw.pop('parent', 'Normal')
        s = ParagraphStyle(name, parent=styles[base], **kw)
        return s

    bg_color    = rgb(*C['bg'])
    panel_color = rgb(*C['panel'])
    border_c    = rgb(*C['border'])
    text_c      = rgb(*C['text'])
    muted_c     = rgb(*C['muted'])
    dim_c       = rgb(*C['dim'])

    s_h1 = sty('H1', fontSize=22, textColor=rgb(*C['white']),
                fontName='Helvetica-Bold', spaceAfter=4, leading=26)
    s_h2 = sty('H2', fontSize=14, textColor=rgb(*C['white']),
                fontName='Helvetica-Bold', spaceAfter=4, leading=18)
    s_h3 = sty('H3', fontSize=11, textColor=rgb(*C['white']),
                fontName='Helvetica-Bold', spaceAfter=3, leading=14)
    s_body= sty('Body', fontSize=9, textColor=muted_c,
                fontName='Helvetica', spaceAfter=3, leading=12)
    s_small=sty('Small', fontSize=8, textColor=dim_c,
                fontName='Helvetica', spaceAfter=2, leading=10)
    s_label=sty('Label', fontSize=8, textColor=dim_c,
                fontName='Helvetica-Bold', spaceAfter=2, leading=10)
    s_code =sty('Code', fontSize=8, textColor=rgb(*C['teal']),
                fontName='Courier', spaceAfter=2, leading=10)

    def para(text, style=s_body): return Paragraph(str(text), style)
    def sp(h=4): return Spacer(1, h * mm)
    def hr(): return HRFlowable(width='100%', thickness=0.5,
                                color=border_c, spaceAfter=4, spaceBefore=4)

    # ── Data extraction ────────────────────────────────────────────
    ticker   = result.get('ticker', result.get('winner', 'ANALYSIS'))
    decision = result.get('decision',
               result.get('overall_stance',
               result.get('winner_decision', '—')))
    conf     = float(result.get('confidence', 0))
    mode     = result.get('mode', 'single')
    goal     = result.get('goal', '')
    ts       = result.get('timestamp', datetime.now().isoformat())[:10]
    regime   = result.get('macro_regime', '—')
    rn       = result.get('regime_note', '')
    dec_col  = _decision_color(str(decision))
    reasoning= result.get('reasoning', {})
    audit_ag = result.get('audit_trail', {}).get('agents', {})
    sources  = result.get('audit_trail', {}).get('sources_used', [])
    ref_links= result.get('audit_trail', {}).get('reference_links', {})

    # ── Table helpers ──────────────────────────────────────────────
    cw = (W - 2*margin)

    def colored_table(data, col_widths, styles_extra=None):
        ts_base = [
            ('BACKGROUND', (0,0), (-1,0), panel_color),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [bg_color, panel_color]),
            ('GRID', (0,0), (-1,-1), 0.3, border_c),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]
        if styles_extra:
            ts_base += styles_extra
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle(ts_base))
        return t

    # ── Story ──────────────────────────────────────────────────────
    story = []

    # Header bar
    story.append(para('AFDE — Autonomous Financial Decision Engine', s_small))
    story.append(hr())
    story.append(sp(1))

    # Title
    story.append(para(f'{ticker} — {decision}', s_h1))
    story.append(para(f'{goal}', s_body))
    story.append(para(f'Generated: {ts}  ·  Mode: {mode}', s_small))
    story.append(sp(2))

    # Verdict card
    dec_col_rl = rgb(*dec_col)
    verdict_data = [
        ['Decision', 'Confidence', 'Macro Regime'],
        [decision,   f'{conf:.0f}%', regime],
    ]
    verdict_styles = [
        ('TEXTCOLOR',  (0,1), (0,1), dec_col_rl),
        ('FONTNAME',   (0,1), (0,1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,1), (0,1), 18),
        ('TEXTCOLOR',  (1,1), (1,1), dec_col_rl),
        ('FONTNAME',   (1,1), (1,1), 'Helvetica-Bold'),
        ('FONTSIZE',   (1,1), (1,1), 14),
    ]
    if rn:
        verdict_data.append(['Regime adjustment', rn, ''])
        verdict_styles.append(('TEXTCOLOR', (1,2), (1,2), rgb(*C['gold'])))
    story.append(colored_table(verdict_data,
                               [cw*0.25, cw*0.25, cw*0.5],
                               verdict_styles))
    story.append(sp(3))

    # Signal cards — one table row per agent
    if reasoning:
        story.append(para('Agent Signals', s_h2))
        story.append(sp(1))

        s_agent_sum = sty('AgentSum', fontSize=8, textColor=muted_c,
                           fontName='Helvetica', spaceAfter=0, leading=11,
                           wordWrap='CJK')
        s_agent_hdr = sty('AgentSumHdr', fontSize=8, textColor=rgb(*C['white']),
                           fontName='Helvetica-Bold', spaceAfter=0, leading=11)

        agent_rows = [[ 
            Paragraph('Agent',   s_agent_hdr),
            Paragraph('Weight',  s_agent_hdr),
            Paragraph('Score',   s_agent_hdr),
            Paragraph('Source',  s_agent_hdr),
            Paragraph('Summary', s_agent_hdr),
        ]]
        WEIGHTS = {'fundamental':'2×','sentiment':'1×','insider':'3×','macro':'1.5×'}
        for agent_name, summary in reasoning.items():
            au     = audit_ag.get(agent_name, {})
            src    = au.get('source_label', 'live')
            weight = WEIGHTS.get(agent_name, '1×')
            # Infer score from summary text
            sl = summary.lower()
            if agent_name == 'insider':
                score_val = '80+' if 'cluster' in sl else '25' if 'sell' in sl else '50'
            elif any(w in sl for w in ['strong','bullish','robust','excellent']):
                score_val = '75+'
            elif any(w in sl for w in ['weak','bearish','concern','negative']):
                score_val = '35'
            else:
                score_val = '55'

            agent_col = rgb(*AGENT_COLORS.get(agent_name, C['blue']))
            s_name = sty(f'AgName_{agent_name}', fontSize=8,
                         textColor=agent_col, fontName='Helvetica-Bold',
                         spaceAfter=0, leading=11)

            agent_rows.append([
                Paragraph(agent_name.upper(), s_name),
                Paragraph(weight,    s_agent_sum),
                Paragraph(score_val, s_agent_sum),
                Paragraph('doc' if 'document' in src else 'live', s_agent_sum),
                Paragraph(summary,   s_agent_sum),   # no truncation — Paragraph wraps
            ])

        agent_styles = [
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]
        story.append(colored_table(agent_rows,
                                   [cw*0.13, cw*0.07, cw*0.07, cw*0.07, cw*0.66],
                                   agent_styles))
        story.append(sp(2))

        # Data points with source links
        story.append(para('Data Points & Sources', s_h3))
        for agent_name, _ in reasoning.items():
            au  = audit_ag.get(agent_name, {})
            dps = au.get('data_points', [])
            if not dps:
                continue
            col = rgb(*AGENT_COLORS.get(agent_name, C['blue']))
            story.append(Spacer(1, 2*mm))
            story.append(para(agent_name.upper(), sty(f'AgH_{agent_name}',
                              fontSize=8, fontName='Helvetica-Bold',
                              textColor=col, spaceAfter=2, leading=10)))
            # Use Paragraph objects in cells so source column renders as clean text
            # (raw <link> tags only work inside Paragraph, not plain Table strings)
            s_dp_text = sty(f'dp_t_{agent_name}', fontSize=7,
                            textColor=muted_c, fontName='Helvetica',
                            spaceAfter=0, leading=9)
            s_dp_src  = sty(f'dp_s_{agent_name}', fontSize=7,
                            textColor=rgb(*C['blue']), fontName='Helvetica',
                            spaceAfter=0, leading=9)
            dp_rows = []
            for dp in dps[:5]:
                raw_text = dp.get('text', '')[:80]
                dp_src   = dp.get('source', '')
                dp_url   = dp.get('url', '')
                # Build source cell: clickable link text, clean display
                if dp_url:
                    src_cell = Paragraph(
                        f'<link href="{dp_url}" color="#3B82F6">{dp_src}</link>',
                        s_dp_src)
                else:
                    src_cell = Paragraph(dp_src, s_dp_src)
                dp_rows.append([
                    Paragraph(raw_text, s_dp_text),
                    src_cell,
                ])
            if dp_rows:
                dp_table = Table(dp_rows, colWidths=[cw*0.65, cw*0.35])
                dp_table.setStyle(TableStyle([
                    ('ROWBACKGROUNDS',(0,0), (-1,-1), [bg_color, panel_color]),
                    ('GRID',          (0,0), (-1,-1), 0.2, border_c),
                    ('TOPPADDING',    (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                    ('LEFTPADDING',   (0,0), (-1,-1), 5),
                    ('RIGHTPADDING',  (0,0), (-1,-1), 5),
                    ('VALIGN',        (0,0), (-1,-1), 'TOP'),
                ]))
                story.append(dp_table)
        story.append(sp(3))

    # Debate section
    bull = result.get('bull_case', '')
    bear = result.get('bear_case', '')
    judge= result.get('judge_reasoning', '')
    bs   = result.get('debate', {}).get('bull_score', 50)
    bs2  = result.get('debate', {}).get('bear_score', 50)

    if bull or bear:
        story.append(para('Bull vs Bear Debate', s_h2))
        story.append(sp(1))
        s_bull = sty('BullTxt', fontSize=8, textColor=muted_c,
                        fontName='Helvetica', spaceAfter=0, leading=11)
        s_bear = sty('BearTxt', fontSize=8, textColor=muted_c,
                        fontName='Helvetica', spaceAfter=0, leading=11)
        debate_data = [
            [f'BULL CASE  {bs:.0f}%', f'BEAR CASE  {bs2:.0f}%'],
            [Paragraph(bull if bull else '—', s_bull),
             Paragraph(bear if bear else '—', s_bear)],
        ]
        debate_styles = [
            ('TEXTCOLOR',  (0,0), (0,0), rgb(*C['green'])),
            ('TEXTCOLOR',  (1,0), (1,0), rgb(*C['sell'])),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,0), 9),
            ('BACKGROUND', (0,0), (0,-1), _hex_bg('#0A1F0A')),
            ('BACKGROUND', (1,0), (1,-1), _hex_bg('#1A0808')),
        ]
        story.append(colored_table(debate_data, [cw*0.5, cw*0.5], debate_styles))

        if judge:
            story.append(sp(1))
            story.append(para('JUDGE VERDICT', sty('JH', fontSize=9,
                              fontName='Helvetica-Bold',
                              textColor=rgb(*C['purple']), spaceAfter=2)))
            s_judge = sty('JudgeTxt', fontSize=8, textColor=muted_c,
                             fontName='Helvetica', spaceAfter=0, leading=11)
            judge_t = Table([[Paragraph(judge, s_judge)]], colWidths=[cw])
            judge_t.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), _hex_bg('#130E20')),
                ('TEXTCOLOR',     (0,0), (-1,-1), muted_c),
                ('FONTSIZE',      (0,0), (-1,-1), 8),
                ('GRID',          (0,0), (-1,-1), 0.3, rgb(*C['purple'])),
                ('TOPPADDING',    (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ]))
            story.append(judge_t)
        story.append(sp(3))

    # Sources used
    if sources or ref_links:
        story.append(para('Data Sources', s_h3))
        story.append(sp(1))
        src_rows = [[s] for s in sources]
        for k, v in list(ref_links.items())[:4]:
            src_rows.append([f'{k}: {v}'])
        if src_rows:
            src_t = Table(src_rows, colWidths=[cw])
            src_t.setStyle(TableStyle([
                ('TEXTCOLOR',     (0,0), (-1,-1), rgb(*C['teal'])),
                ('FONTSIZE',      (0,0), (-1,-1), 7),
                ('FONTNAME',      (0,0), (-1,-1), 'Courier'),
                ('ROWBACKGROUNDS',(0,0), (-1,-1), [bg_color, panel_color]),
                ('TOPPADDING',    (0,0), (-1,-1), 2),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ]))
            story.append(src_t)
        story.append(sp(2))

    # Disclaimer
    story.append(hr())
    story.append(para(
        'AI-generated financial analysis for educational purposes only. '
        'Not financial advice. Always consult a licensed financial advisor '
        'before making investment decisions. Generated by AFDE.',
        sty('Dis', fontSize=7, textColor=dim_c, leading=10)))

    # ── Page background ────────────────────────────────────────────
    def on_page(canvas_obj, doc_obj):
        canvas_obj.saveState()
        canvas_obj.setFillColor(bg_color)
        canvas_obj.rect(0, 0, W, H, fill=1, stroke=0)
        # Top accent line
        canvas_obj.setFillColor(rgb(*C['navy']))
        canvas_obj.rect(0, H-2, W, 2, fill=1, stroke=0)
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _hex_bg(h: str):
    """Return a reportlab Color from hex for table backgrounds."""
    from reportlab.lib.colors import Color
    t = _hex(h)
    return Color(t[0], t[1], t[2])