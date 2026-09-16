# -*- coding: utf-8 -*-
"""应用样式表"""

ACCENT = "#FE2C55"
ACCENT_DARK = "#E01F45"
CYAN = "#25F4EE"

QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}}

QWidget {{
    color: #1F2329;
    font-size: 13px;
}}

/* ============ 侧边导航 ============ */
#sidebar {{
    background: #17191F;
    min-width: 178px;
    max-width: 178px;
}}
#appTitle {{
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
    padding: 20px 18px 6px 18px;
}}
#appSub {{
    color: #6B7280;
    font-size: 11px;
    padding: 0 18px 16px 18px;
}}
#navList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 4px 0;
}}
#navList::item {{
    height: 44px;
    color: #9CA3AF;
    padding-left: 16px;
    border-left: 3px solid transparent;
}}
#navList::item:hover {{
    background: #21242C;
    color: #E5E7EB;
}}
#navList::item:selected {{
    background: #23262F;
    color: #FFFFFF;
    border-left: 3px solid {ACCENT};
    font-weight: 600;
}}
#navFooter {{
    color: #4B5563;
    font-size: 11px;
    padding: 12px 18px;
}}

/* ============ 内容区 ============ */
#content {{
    background: #F5F6F8;
}}
QScrollArea {{ background: transparent; border: none; }}

QGroupBox {{
    background: #FFFFFF;
    border: 1px solid #E8EAED;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px 14px 12px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #374151;
}}

QLabel#hint {{
    color: #6B7280;
    font-size: 12px;
}}
QLabel#sectionTitle {{
    font-size: 16px;
    font-weight: 700;
    color: #111827;
}}

/* ============ 输入控件 ============ */
QLineEdit, QComboBox, QSpinBox {{
    background: #FFFFFF;
    border: 1px solid #D9DDE3;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 4px;
    background: #FFFFFF;
    selection-background-color: #FEE7EC;
}}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid #C9CED6;
    border-radius: 4px;
    background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    image: none;
}}

/* ============ 按钮 ============ */
QPushButton {{
    background: #FFFFFF;
    border: 1px solid #D9DDE3;
    border-radius: 8px;
    padding: 7px 15px;
    color: #374151;
}}
QPushButton:hover {{ background: #F3F4F6; border-color: #C9CED6; }}
QPushButton:pressed {{ background: #E9EBEF; }}
QPushButton:disabled {{
    background: #F3F4F6; color: #B0B5BD; border-color: #E5E7EB;
}}
QPushButton#primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #FFFFFF; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; border-color: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #F7B9C6; border-color: #F7B9C6; color: #FFFFFF; }}
QPushButton#danger {{
    color: {ACCENT}; border: 1px solid #F5C6D0;
}}
QPushButton#danger:hover {{ background: #FEF1F4; }}
QPushButton#ghost {{
    background: transparent; border: 1px solid transparent; color: #6B7280;
}}
QPushButton#ghost:hover {{ background: #F3F4F6; color: #111827; }}
QPushButton#iconBtn {{
    min-width: 32px; min-height: 30px; padding: 4px 8px;
}}

/* ============ 表格 ============ */
QTableWidget {{
    background: #FFFFFF;
    border: 1px solid #E8EAED;
    border-radius: 10px;
    gridline-color: #F0F1F3;
    outline: none;
}}
QTableWidget::item {{ padding: 4px 8px; }}
QTableWidget::item:selected {{ background: #FEE7EC; color: #111827; }}
QHeaderView::section {{
    background: #FAFBFC;
    border: none;
    border-bottom: 1px solid #E8EAED;
    padding: 8px;
    font-weight: 600;
    color: #4B5563;
}}
QTableCornerButton::section {{ background: #FAFBFC; border: none; }}

/* ============ 进度条 ============ */
QProgressBar {{
    background: #EEF0F3;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}

/* ============ 其它 ============ */
QStatusBar {{ background: #FFFFFF; border-top: 1px solid #E8EAED; color: #6B7280; }}
QToolTip {{
    background: #1F2329; color: #FFFFFF; border: none; padding: 5px 8px; border-radius: 5px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #D5D8DE; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #BFC4CC; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: #D5D8DE; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QTextBrowser {{
    background: #FFFFFF; border: 1px solid #E8EAED; border-radius: 8px; padding: 10px;
}}
QPlainTextEdit, QTextEdit {{
    background: #FFFFFF;
    border: 1px solid #D9DDE3;
    border-radius: 8px;
    padding: 8px;
    color: #1F2329;
    selection-background-color: {ACCENT};
}}
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QDialog {{ background: #F5F6F8; }}
QMessageBox {{ background: #FFFFFF; }}
"""
