import sys, time, datetime, json
import hid
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QLabel, QMessageBox, QListWidget, 
                             QSplitter, QFrame, QFileDialog)
from PyQt6.QtCore import Qt
import plotly.graph_objects as go
from PyQt6.QtWebEngineWidgets import QWebEngineView

# --- MOTOR DE COMUNICACIÓN MM32 (0888:4000) ---
class TC420Device:
    def __init__(self):
        self.vendor_id = 0x0888 
        self.product_id = 0x4000
        self.device = None

    def connect(self):
        try:
            self.device = hid.device()
            self.device.open(self.vendor_id, self.product_id)
            return True
        except: return False

    def send_packet(self, data):
        if not self.device: return False
        full = [0x00] + list(data) # Report ID 0x00 + 64 bytes
        try:
            self.device.write(full)
            return True
        except: return False

    def sync_time(self):
        if not self.connect(): return False
        n = datetime.datetime.now()
        pkt = [0x00] * 64
        pkt[0], pkt[1], pkt[2] = 0x55, 0xAA, 0x01
        pkt[3], pkt[4], pkt[5] = n.hour, n.minute, n.second
        pkt[6], pkt[7], pkt[8] = n.day, n.month, n.year - 2000
        pkt[63] = sum(pkt[0:63]) & 0xFF
        return self.send_packet(pkt)

    def upload_program(self, steps):
        if not self.connect(): return False
        # 1. Handshake Inicio (0x02)
        start = [0x00] * 64
        start[0], start[1], start[2], start[3] = 0x55, 0xAA, 0x02, len(steps)
        start[63] = sum(start[0:63]) & 0xFF
        self.send_packet(start)
        time.sleep(0.5)
        # 2. Envío de Pasos (0x04)
        for i, s in enumerate(steps):
            pkt = [0x00] * 64
            pkt[0], pkt[1], pkt[2], pkt[3] = 0x55, 0xAA, 0x04, i
            pkt[4], pkt[5] = s['h'], s['m']
            for ch, val in enumerate(s['v']): pkt[6 + ch] = val
            pkt[63] = sum(pkt[0:63]) & 0xFF
            self.send_packet(pkt)
            time.sleep(0.1)
        # 3. Fin y Pitido (0x03)
        end = [0x00] * 64
        end[0], end[1], end[2] = 0x55, 0xAA, 0x03
        end[63] = sum(end[0:63]) & 0xFF
        return self.send_packet(end)

# --- INTERFAZ CLON PLED.EXE ---
class PledApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PLed - [Untitled.pmf]")
        self.setFixedSize(1200, 700)
        self.device = TC420Device()
        self.ch_colors = ['#FFFFFF', '#38bdf8', '#f87171', '#4ade80', '#fbbf24']
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #f0f0f0; color: black; font-family: 'Segoe UI', Arial; }
            QPushButton { background-color: #e1e1e1; border: 1px solid #adadad; padding: 6px; min-width: 90px; }
            QPushButton:hover { background-color: #e5f1fb; border-color: #0078d7; }
            QTableWidget { background-color: white; gridline-color: #d0d0d0; }
            QHeaderView::section { background-color: #f0f0f0; border: 1px solid #d0d0d0; }
            QListWidget { background-color: white; border: 1px solid #adadad; }
        """)

        layout = QVBoxLayout(self)

        # 1. TOOLBAR (Estilo Windows)
        tbar = QHBoxLayout()
        self.btn_open = QPushButton("Open"); self.btn_open.clicked.connect(self.load_file)
        self.btn_save = QPushButton("Save"); self.btn_save.clicked.connect(self.save_file)
        self.btn_sync = QPushButton("Sync Time"); self.btn_sync.clicked.connect(self.action_sync)
        self.btn_down = QPushButton("Download"); self.btn_down.clicked.connect(self.action_upload)
        
        tbar.addWidget(self.btn_open); tbar.addWidget(self.btn_save); tbar.addSpacing(30)
        tbar.addWidget(self.btn_sync); tbar.addWidget(self.btn_down); tbar.addStretch()
        layout.addLayout(tbar)

        # 2. CUERPO PRINCIPAL
        split = QSplitter(Qt.Orientation.Horizontal)

        # Izquierda: Modos
        left = QFrame(); l_lay = QVBoxLayout(left)
        l_lay.addWidget(QLabel("<b>Mode List:</b>"))
        self.modes = QListWidget(); self.modes.addItem("Default Mode")
        l_lay.addWidget(self.modes); split.addWidget(left)

        # Derecha: Editor
        right = QFrame(); r_lay = QVBoxLayout(right)
        btn_lay = QHBoxLayout()
        btn_add = QPushButton("Add Step"); btn_add.clicked.connect(lambda: self.add_step())
        btn_del = QPushButton("Delete Step"); btn_del.clicked.connect(self.del_step)
        btn_lay.addWidget(btn_add); btn_lay.addWidget(btn_del); btn_lay.addStretch()
        r_lay.addLayout(btn_lay)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Time", "CH1", "CH2", "CH3", "CH4", "CH5"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.update_chart)
        r_lay.addWidget(self.table)

        self.web = QWebEngineView(); self.web.setFixedHeight(300); r_lay.addWidget(self.web)
        split.addWidget(right); split.setStretchFactor(1, 4)
        layout.addWidget(split)

        self.add_step("08:00", [0]*5); self.add_step("20:00", [0]*5)

    def add_step(self, h="12:00", v=None):
        v = v or [0]*5
        self.table.blockSignals(True)
        r = self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(h))
        for i, val in enumerate(v): self.table.setItem(r, i+1, QTableWidgetItem(str(val)))
        self.table.blockSignals(False); self.update_chart()

    def del_step(self):
        curr = self.table.currentRow()
        if curr >= 0: self.table.removeRow(curr)

    def update_chart(self):
        pts = []
        for r in range(self.table.rowCount()):
            try:
                t = self.table.item(r,0).text().split(':')
                pts.append({'m': int(t[0])*60 + int(t[1]), 'v': [int(self.table.item(r,c).text()) for c in range(1,6)]})
            except: continue
        pts.sort(key=lambda x: x['m'])
        if not pts: return
        fig = go.Figure()
        for ch in range(5):
            fig.add_trace(go.Scatter(x=[p['m']/60 for p in pts], y=[p['v'][ch] for p in pts], name=f"CH{ch+1}", line=dict(color=self.ch_colors[ch])))
        fig.update_layout(template="plotly_white", margin=dict(l=10,r=10,t=10,b=10), xaxis=dict(range=[0,24]))
        self.web.setHtml(fig.to_html(include_plotlyjs='cdn', config={'displayModeBar': False}))

    def action_sync(self):
        if self.device.sync_time(): QMessageBox.information(self, "TC420", "Time Synced!")

    def action_upload(self):
        steps = []
        try:
            for r in range(self.table.rowCount()):
                t = self.table.item(r,0).text().split(':')
                steps.append({'h': int(t[0]), 'm': int(t[1]), 'v': [int(self.table.item(r,c).text()) for c in range(1,6)]})
            if self.device.upload_program(steps): QMessageBox.information(self, "TC420", "Download Successful!")
        except Exception as e: QMessageBox.critical(self, "Error", f"Bad data: {e}")

    def save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "Pled Files (*.pmf)")
        if path:
            data = []
            for r in range(self.table.rowCount()):
                data.append({'t': self.table.item(r,0).text(), 'v': [self.table.item(r,c).text() for c in range(1,6)]})
            with open(path, 'w') as f: json.dump(data, f)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "Pled Files (*.pmf)")
        if path:
            with open(path, 'r') as f:
                data = json.load(f)
                self.table.setRowCount(0)
                for item in data: self.add_step(item['t'], [int(x) for x in item['v']])

if __name__ == "__main__":
    app = QApplication(sys.argv); win = PledApp(); win.show(); sys.exit(app.exec())
