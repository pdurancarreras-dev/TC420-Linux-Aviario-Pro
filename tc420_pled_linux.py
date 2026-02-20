import sys, time, datetime, json, hid
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QLabel, QMessageBox, QListWidget, 
                             QSplitter, QFrame, QFileDialog, QDialog, QSlider, QTimeEdit)
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtGui import QColor
import plotly.graph_objects as go
from PyQt6.QtWebEngineWidgets import QWebEngineView

# --- MOTOR USB MM32 (0888:4000) REVISADO ---
class TC420Device:
    def __init__(self):
        self.vendor_id, self.product_id, self.device = 0x0888, 0x4000, None

    def connect(self):
        try:
            if self.device: self.device.close()
            self.device = hid.device()
            self.device.open(self.vendor_id, self.product_id)
            return True
        except: return False

    def send_packet(self, data):
        if not self.device: return False
        # Report ID 0x00 + 64 bytes exactos
        pkt = [0x00] + list(data)
        if len(pkt) < 65: pkt += [0x00] * (65 - len(pkt))
        try:
            self.device.write(pkt[:65])
            return True
        except: return False

    def sync_time(self):
        if not self.connect(): return False
        n = datetime.datetime.now()
        pkt = [0x00] * 64
        # Protocolo exacto para que PITE (0x55 0xAA 0x01)
        pkt[0:9] = [0x55, 0xAA, 0x01, n.hour, n.minute, n.second, n.day, n.month, n.year - 2000]
        # Checksum en la posición 63 (Suma de los anteriores)
        pkt[63] = sum(pkt[0:63]) & 0xFF
        res = self.send_packet(pkt)
        time.sleep(0.1) # Pausa para que el chip procese el pitido
        return res

    def upload_program(self, steps):
        if not self.connect(): return False
        # 1. Inicio (0x02)
        start = [0x00] * 64
        start[0:4] = [0x55, 0xAA, 0x02, len(steps)]
        start[63] = sum(start[0:63]) & 0xFF
        self.send_packet(start)
        time.sleep(0.6) # Tiempo para borrar flash

        # 2. Pasos (0x04)
        for i, s in enumerate(steps):
            pkt = [0x00] * 64
            pkt[0:6] = [0x55, 0xAA, 0x04, i, s['h'], s['m']]
            for ch, val in enumerate(s['v']): pkt[6 + ch] = val
            pkt[63] = sum(pkt[0:63]) & 0xFF
            self.send_packet(pkt)
            time.sleep(0.15)
        
        # 3. Fin (0x03) -> Dispara el pitido final
        end = [0x00] * 64
        end[0:3] = [0x55, 0xAA, 0x03]
        end[63] = sum(end[0:63]) & 0xFF
        return self.send_packet(end)

# --- VENTANA DE EDICIÓN (ESTILO SLIDERS PLED) ---
class StepDialog(QDialog):
    def __init__(self, h="12:00", v=[0,0,0,0,0], colors=[]):
        super().__init__()
        self.setWindowTitle("Edit Step Info")
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        
        h_lay = QHBoxLayout(); h_lay.addWidget(QLabel("Step Time: "))
        self.time_edit = QTimeEdit(QTime.fromString(h, "HH:mm"))
        h_lay.addWidget(self.time_edit); layout.addLayout(h_lay)
        
        self.sliders = []
        for i in range(5):
            container = QFrame(); container.setStyleSheet("background: #e1e1e1; border: 1px solid #adadad;")
            c_lay = QVBoxLayout(container)
            info = QHBoxLayout()
            name = QLabel(f"<b>CH{i+1}</b>"); name.setStyleSheet(f"color: {colors[i]};")
            val_lbl = QLabel(f"{v[i]}%"); val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            info.addWidget(name); info.addWidget(val_lbl)
            
            sl = QSlider(Qt.Orientation.Horizontal); sl.setRange(0, 100); sl.setValue(v[i])
            sl.valueChanged.connect(lambda val, l=val_lbl: l.setText(f"{val}%"))
            c_lay.addLayout(info); c_lay.addWidget(sl); layout.addWidget(container)
            self.sliders.append(sl)

        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.clicked.connect(self.accept)
        can = QPushButton("Cancel"); can.clicked.connect(self.reject)
        btns.addWidget(ok); btns.addWidget(can); layout.addLayout(btns)

    def get_data(self):
        return self.time_edit.time().toString("HH:mm"), [s.value() for s in self.sliders]

# --- INTERFAZ PRINCIPAL (RÉPLICA 100% PLED) ---
class PledApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PLed - [Aviario Pro v2.0]")
        self.setFixedSize(1200, 780)
        self.device = TC420Device()
        self.ch_colors = ['#FF0000', '#00AA00', '#0000FF', '#AAAA00', '#AA00AA']
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #f0f0f0; color: black; font-family: 'Tahoma', Arial; }
            QPushButton { background-color: #e1e1e1; border: 1px solid #707070; padding: 5px; min-width: 80px; }
            QPushButton:hover { background-color: #e5f1fb; border-color: #0078d7; }
            QTableWidget { background-color: white; gridline-color: #d0d0d0; }
            QListWidget { background-color: white; border: 1px solid #707070; }
            QHeaderView::section { background-color: #e1e1e1; border: 1px solid #adadad; font-weight: bold; }
        """)
        
        main_lay = QVBoxLayout(self)
        tbar = QHBoxLayout()
        for t, f in [("Open", self.load_file), ("Save", self.save_file), ("Sync Time", self.action_sync), ("Download", self.action_upload)]:
            b = QPushButton(t); b.clicked.connect(f); tbar.addWidget(b)
        tbar.addStretch(); main_lay.addLayout(tbar)

        split = QSplitter(Qt.Orientation.Horizontal)
        # Lado Izquierdo: Modos
        left = QFrame(); l_lay = QVBoxLayout(left); l_lay.addWidget(QLabel("Mode List:"))
        self.modes = QListWidget(); self.modes.addItem("Mode 1")
        self.modes.setEditTriggers(QListWidget.EditTrigger.DoubleClicked)
        l_lay.addWidget(self.modes)
        
        m_btns = QHBoxLayout()
        b_add = QPushButton("+"); b_add.setFixedWidth(30); b_add.clicked.connect(lambda: self.modes.addItem("New Mode"))
        b_del = QPushButton("-"); b_del.setFixedWidth(30); b_del.clicked.connect(lambda: self.modes.takeItem(self.modes.currentRow()))
        m_btns.addWidget(b_add); m_btns.addWidget(b_del); m_btns.addStretch(); l_lay.addLayout(m_btns)
        split.addWidget(left)

        # Lado Derecho: Editor
        right = QFrame(); r_lay = QVBoxLayout(right)
        s_btns = QHBoxLayout()
        b_as = QPushButton("Add Step"); b_as.clicked.connect(self.add_step_dialog)
        b_ds = QPushButton("Delete Step"); b_ds.clicked.connect(self.del_step)
        s_btns.addWidget(b_as); s_btns.addWidget(b_ds); s_btns.addStretch(); r_lay.addLayout(s_btns)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Time", "CH1", "CH2", "CH3", "CH4", "CH5"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(self.edit_step_dialog)
        r_lay.addWidget(self.table)

        self.web = QWebEngineView(); self.web.setFixedHeight(320); r_lay.addWidget(self.web)
        split.addWidget(right); split.setStretchFactor(1, 4)
        main_lay.addWidget(split)

        self.status = QLabel("  Status: USB Checking..."); self.status.setStyleSheet("background: #ddd; border-top: 1px solid #999; padding: 3px;")
        main_lay.addWidget(self.status)

        self.add_step("08:00", [0,0,0,0,0])
        self.check_usb()

    def check_usb(self):
        if self.device.connect():
            self.status.setText("  Status: TC420 Connected (0888:4000)")
            self.status.setStyleSheet("color: green; background: #ddd; font-weight: bold;")
        else:
            self.status.setText("  Status: USB Disconnected")
            self.status.setStyleSheet("color: red; background: #ddd;")

    def add_step_dialog(self):
        dlg = StepDialog(colors=self.ch_colors)
        if dlg.exec():
            h, v = dlg.get_data(); self.add_step(h, v)

    def edit_step_dialog(self, item):
        row = item.row()
        h = self.table.item(row,0).text()
        v = [int(self.table.item(row, c).text().replace('%','')) for c in range(1,6)]
        dlg = StepDialog(h, v, self.ch_colors)
        if dlg.exec():
            nh, nv = dlg.get_data(); self.table.item(row,0).setText(nh)
            for i, val in enumerate(nv):
                it = QTableWidgetItem(f"{val}%"); it.setForeground(QColor(self.ch_colors[i]))
                self.table.setItem(row, i+1, it)
            self.update_chart()

    def add_step(self, h, v):
        self.table.blockSignals(True); r = self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(h))
        for i, val in enumerate(v):
            it = QTableWidgetItem(f"{val}%"); it.setForeground(QColor(self.ch_colors[i]))
            self.table.setItem(r, i+1, it)
        self.table.blockSignals(False); self.update_chart()

    def del_step(self):
        row = self.table.currentRow()
        if row >= 0: self.table.removeRow(row); self.update_chart()

    def update_chart(self):
        pts = []
        for r in range(self.table.rowCount()):
            try:
                t = self.table.item(r,0).text().split(':')
                pts.append({'m': int(t)*60 + int(t), 'v': [int(self.table.item(r,c).text().replace('%','')) for c in range(1,6)]})
            except: continue
        pts.sort(key=lambda x: x['m'])
        if not pts: return
        fig = go.Figure()
        for i in range(5):
            fig.add_trace(go.Scatter(x=[p['m']/60 for p in pts], y=[p['v'][i] for p in pts], name=f"CH{i+1}", line=dict(color=self.ch_colors[i], width=3)))
        fig.update_layout(template="plotly_white", margin=dict(l=5,r=5,t=5,b=5), xaxis=dict(range=[0,24], dtick=2))
        self.web.setHtml(fig.to_html(include_plotlyjs='cdn', config={'displayModeBar': False}))

    def action_sync(self):
        if self.device.sync_time(): 
            QMessageBox.information(self, "TC420", "¡Sincronizado! (BIP)")
            self.check_usb()
        else: QMessageBox.warning(self, "Error", "No detectado. Revisa el cable.")

    def action_upload(self):
        steps = []
        for r in range(self.table.rowCount()):
            t = self.table.item(r,0).text().split(':')
            steps.append({'h': int(t[0]), 'm': int(t[1]), 'v': [int(self.table.item(r,c).text().replace('%','')) for c in range(1,6)]})
        if self.device.upload_program(steps): QMessageBox.information(self, "TC420", "Download OK! (BIP)")
        else: QMessageBox.critical(self, "Error", "Fallo al subir.")

    def save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save", "", "Pled Files (*.pmf)")
        if path:
            data = [{'t': self.table.item(r,0).text(), 'v': [self.table.item(r,c).text() for c in range(1,6)]} for r in range(self.table.rowCount())]
            with open(path, 'w') as f: json.dump(data, f)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", "Pled Files (*.pmf)")
        if path:
            with open(path, 'r') as f:
                data = json.load(f); self.table.blockSignals(True); self.table.setRowCount(0)
                for it in data: self.add_step(it['t'], [int(x.replace('%','')) for x in it['v']])
                self.table.blockSignals(False); self.update_chart()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = PledApp(); win.show(); sys.exit(app.exec())
