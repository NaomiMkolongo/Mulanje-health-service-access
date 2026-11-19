"""Mulanje Health Facilities - QGIS plugin (UI + QGIS integration)."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QMessageBox, QPlainTextEdit, QDialogButtonBox,
    QGroupBox, QHeaderView)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsDataSourceUri, QgsSettings,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsPointXY, QgsRectangle)
from qgis.gui import QgsMapToolEmitPoint

from .db import Database, DbError, FACILITY_TYPES, OWNERSHIPS, HAS_PSYCOPG2, SCHEMA, TABLE

LAYER_NAME = "Mulanje health facilities"
SETTINGS_KEY = "MulanjeHealth/"
TYPE_COLOURS = {
    "Hospital": "#d7191c", "Health Centre": "#2b83ba", "Dispensary": "#fdae61",
    "Health Post": "#7b3294", "Clinic": "#1a9641",
}
MULANJE_EXTENT = (35.30, -16.20, 35.80, -15.85)  # lon/lat bbox for zooming


class FacilityForm(QDialog):
    """Add/edit form. Non-modal so the user can click the map to pick coordinates."""

    def __init__(self, iface, record=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Edit facility" if record else "Add facility")
        self.tool = None

        self.name = QLineEdit()
        self.ftype = QComboBox(); self.ftype.addItems(FACILITY_TYPES)
        self.own = QComboBox(); self.own.addItems(OWNERSHIPS)
        self.ta = QLineEdit()
        self.beds = QSpinBox(); self.beds.setRange(0, 5000)
        self.staff = QSpinBox(); self.staff.setRange(0, 5000)
        self.pop = QSpinBox(); self.pop.setRange(0, 10000000); self.pop.setSingleStep(1000)
        self.services = QLineEdit()
        self.amb = QCheckBox("Has ambulance")
        self.elec = QCheckBox("Has electricity")
        self.lat = QDoubleSpinBox(); self.lat.setDecimals(6); self.lat.setRange(-90, 90)
        self.lon = QDoubleSpinBox(); self.lon.setDecimals(6); self.lon.setRange(-180, 180)
        self.lat.setValue(-16.03); self.lon.setValue(35.50)
        self.notes = QPlainTextEdit(); self.notes.setFixedHeight(50)
        pick = QPushButton("Pick on map…")
        pick.clicked.connect(self._pick)

        form = QFormLayout()
        form.addRow("Name *", self.name)
        form.addRow("Type", self.ftype)
        form.addRow("Ownership", self.own)
        form.addRow("Traditional Authority", self.ta)
        form.addRow("Beds", self.beds)
        form.addRow("Staff", self.staff)
        form.addRow("Catchment population", self.pop)
        form.addRow("Services", self.services)
        form.addRow("", self.amb)
        form.addRow("", self.elec)
        form.addRow("Latitude (WGS84)", self.lat)
        form.addRow("Longitude (WGS84)", self.lon)
        form.addRow("", pick)
        form.addRow("Notes", self.notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

        if record:
            self.name.setText(record["name"] or "")
            self.ftype.setCurrentText(record["facility_type"])
            self.own.setCurrentText(record["ownership"])
            self.ta.setText(record["traditional_authority"] or "")
            self.beds.setValue(record["beds"] or 0)
            self.staff.setValue(record["staff_count"] or 0)
            self.pop.setValue(record["catchment_population"] or 0)
            self.services.setText(record["services"] or "")
            self.amb.setChecked(bool(record["has_ambulance"]))
            self.elec.setChecked(bool(record["has_electricity"]))
            self.lat.setValue(record["lat"]); self.lon.setValue(record["lon"])
            self.notes.setPlainText(record["notes"] or "")

    def _validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Please enter the facility name.")
            return
        self.accept()

    def values(self):
        return {
            "name": self.name.text().strip(),
            "facility_type": self.ftype.currentText(),
            "ownership": self.own.currentText(),
            "traditional_authority": self.ta.text().strip() or None,
            "beds": self.beds.value(),
            "staff_count": self.staff.value(),
            "catchment_population": self.pop.value() or None,
            "services": self.services.text().strip() or None,
            "has_ambulance": self.amb.isChecked(),
            "has_electricity": self.elec.isChecked(),
            "lat": self.lat.value(),
            "lon": self.lon.value(),
            "notes": self.notes.toPlainText().strip() or None,
        }

    def _pick(self):
        canvas = self.iface.mapCanvas()
        self.tool = QgsMapToolEmitPoint(canvas)
        self.tool.canvasClicked.connect(self._picked)
        canvas.setMapTool(self.tool)
        self.hide()
        self.iface.messageBar().pushInfo("Mulanje Health", "Click the map to set the facility location.")

    def _picked(self, point, _button):
        lonlat = to_wgs84(self.iface, point)
        self.lon.setValue(lonlat.x()); self.lat.setValue(lonlat.y())
        self.iface.mapCanvas().unsetMapTool(self.tool)
        self.show(); self.raise_()


def to_wgs84(iface, point):
    src = iface.mapCanvas().mapSettings().destinationCrs()
    dst = QgsCoordinateReferenceSystem("EPSG:4326")
    return QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(QgsPointXY(point))


class MainDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.db = Database()
        self.form = None
        self.near_tool = None
        self.setWindowTitle("Mulanje Health Facilities")
        self.resize(900, 600)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connection_tab(), "1. Database")
        self.tabs.addTab(self._build_facilities_tab(), "2. Facilities")
        self.tabs.addTab(self._build_map_tab(), "3. Map && analysis")
        self.tabs.addTab(self._build_about_tab(), "About")
        self.status = QLabel("Not connected")
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(self.status)
        self._set_connected(False)
        self._load_settings()

    # ---- tab builders ------------------------------------------------
    def _build_connection_tab(self):
        w = QWidget()
        self.host = QLineEdit("localhost")
        self.port = QLineEdit("5432")
        self.dbname = QLineEdit("mulanjehealth")
        self.user = QLineEdit("postgres")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("Host", self.host); form.addRow("Port", self.port)
        form.addRow("Database", self.dbname); form.addRow("User", self.user)
        form.addRow("Password", self.password)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_schema = QPushButton("Create schema (PostGIS)")
        self.btn_schema.clicked.connect(self.on_create_schema)
        self.btn_seed = QPushButton("Load temporary sample data")
        self.btn_seed.clicked.connect(self.on_seed)
        self.btn_drop = QPushButton("Delete schema…")
        self.btn_drop.clicked.connect(self.on_drop)
        row = QHBoxLayout()
        for b in (self.btn_connect, self.btn_schema, self.btn_seed, self.btn_drop):
            row.addWidget(b)
        hint = QLabel(
            "The database must already exist and have the PostGIS extension available "
            "(e.g. <code>CREATE DATABASE mulanjehealth;</code>). Sample rows are flagged "
            "<i>is_sample</i>; reloading sample data replaces only those rows. "
            "The password is not saved.")
        hint.setWordWrap(True)
        lay = QVBoxLayout(w)
        lay.addLayout(form); lay.addLayout(row); lay.addWidget(hint); lay.addStretch()
        if not HAS_PSYCOPG2:
            lay.addWidget(QLabel("<b style='color:red'>psycopg2 is not available in this QGIS installation.</b>"))
        return w

    def _build_facilities_tab(self):
        w = QWidget()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search name, TA or service…")
        self.f_type = QComboBox(); self.f_type.addItem("All types", ""); [self.f_type.addItem(t, t) for t in FACILITY_TYPES]
        self.f_own = QComboBox(); self.f_own.addItem("All ownership", ""); [self.f_own.addItem(t, t) for t in OWNERSHIPS]
        for sig in (self.search.textChanged, self.f_type.currentIndexChanged, self.f_own.currentIndexChanged):
            sig.connect(self.refresh_table)
        top = QHBoxLayout()
        top.addWidget(self.search, 2); top.addWidget(self.f_type); top.addWidget(self.f_own)

        self.headers = ["ID", "Name", "Type", "Ownership", "TA", "Beds", "Staff", "Catchment",
                        "Ambulance", "Electricity", "Sample"]
        self.table = QTableWidget(0, len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.on_edit)

        b_add = QPushButton("Add…"); b_add.clicked.connect(self.on_add)
        b_edit = QPushButton("Edit…"); b_edit.clicked.connect(self.on_edit)
        b_del = QPushButton("Delete"); b_del.clicked.connect(self.on_delete)
        b_zoom = QPushButton("Zoom to"); b_zoom.clicked.connect(self.on_zoom)
        b_ref = QPushButton("Refresh"); b_ref.clicked.connect(self.refresh_table)
        row = QHBoxLayout()
        for b in (b_add, b_edit, b_del, b_zoom, b_ref):
            row.addWidget(b)
        self.count_label = QLabel("")
        lay = QVBoxLayout(w)
        lay.addLayout(top); lay.addWidget(self.table); lay.addLayout(row); lay.addWidget(self.count_label)
        return w

    def _build_map_tab(self):
        w = QWidget()
        b_layer = QPushButton("Add facilities layer to QGIS")
        b_layer.clicked.connect(self.on_add_layer)
        b_osm = QPushButton("Add OpenStreetMap basemap")
        b_osm.clicked.connect(self.on_add_osm)
        b_ext = QPushButton("Zoom to Mulanje")
        b_ext.clicked.connect(self.on_zoom_district)
        row = QHBoxLayout()
        for b in (b_layer, b_osm, b_ext):
            row.addWidget(b)

        box = QGroupBox("Summary by facility type")
        self.stats = QTableWidget(0, 7)
        self.stats.setHorizontalHeaderLabels(
            ["Type", "Facilities", "Beds", "Staff", "Catchment", "Ambulance", "Electricity"])
        self.stats.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stats.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        b_stats = QPushButton("Refresh summary"); b_stats.clicked.connect(self.refresh_stats)
        sl = QVBoxLayout(box); sl.addWidget(self.stats); sl.addWidget(b_stats)

        box2 = QGroupBox("Nearest facilities")
        b_near = QPushButton("Click a location on the map…")
        b_near.clicked.connect(self.on_nearest_tool)
        self.near_n = QSpinBox(); self.near_n.setRange(1, 20); self.near_n.setValue(5)
        self.near = QTableWidget(0, 4)
        self.near.setHorizontalHeaderLabels(["Facility", "Type", "Ownership", "Distance (km)"])
        self.near.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.near.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        nr = QHBoxLayout(); nr.addWidget(b_near); nr.addWidget(QLabel("How many:")); nr.addWidget(self.near_n)
        nl = QVBoxLayout(box2); nl.addLayout(nr); nl.addWidget(self.near)

        lay = QVBoxLayout(w)
        lay.addLayout(row); lay.addWidget(box); lay.addWidget(box2)
        return w

    def _build_about_tab(self):
        w = QWidget()
        txt = QLabel(
            "<h3>Mulanje Health Facilities</h3>"
            "<p>Stores health facilities of Mulanje District in PostgreSQL/PostGIS "
            "(schema <code>%s</code>, table <code>%s</code>, SRID 4326) and lets you manage and "
            "map them from QGIS.</p>"
            "<p><b>Temporary data:</b> the bundled sample records use plausible facility names but "
            "approximate placeholder coordinates. Replace with surveyed data before using results.</p>"
            "<p>Edited sample rows are automatically un-flagged as samples.</p>" % (SCHEMA, TABLE))
        txt.setWordWrap(True); txt.setTextFormat(Qt.RichText)
        lay = QVBoxLayout(w); lay.addWidget(txt); lay.addStretch()
        return w

    # ---- helpers -----------------------------------------------------
    def _load_settings(self):
        s = QgsSettings()
        for key, widget in (("host", self.host), ("port", self.port), ("db", self.dbname), ("user", self.user)):
            v = s.value(SETTINGS_KEY + key, "")
            if v:
                widget.setText(str(v))

    def _save_settings(self):
        s = QgsSettings()
        for key, widget in (("host", self.host), ("port", self.port), ("db", self.dbname), ("user", self.user)):
            s.setValue(SETTINGS_KEY + key, widget.text())

    def _set_connected(self, ok):
        for b in (self.btn_schema, self.btn_seed, self.btn_drop):
            b.setEnabled(ok)
        for i in (1, 2):
            self.tabs.setTabEnabled(i, ok)

    def _error(self, exc):
        QMessageBox.critical(self, "Database error", str(exc))
        self.status.setText("Error: " + str(exc).splitlines()[0])

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Select a facility", "Select a row first.")
            return None
        return int(self.table.item(rows[0].row(), 0).text())

    def _refresh_qgis_layers(self):
        for lyr in QgsProject.instance().mapLayersByName(LAYER_NAME):
            lyr.dataProvider().reloadData()
            lyr.triggerRepaint()

    # ---- connection actions ------------------------------------------
    def on_connect(self):
        try:
            self.db.connect(self.host.text().strip(), self.port.text().strip(),
                            self.dbname.text().strip(), self.user.text().strip(), self.password.text())
        except DbError as exc:
            self._set_connected(False)
            return self._error(exc)
        self._save_settings()
        self._set_connected(True)
        try:
            has = self.db.schema_exists()
        except DbError as exc:
            return self._error(exc)
        self.status.setText("Connected to %s@%s/%s" % (self.user.text(), self.host.text(), self.dbname.text())
                            + ("" if has else " - schema not created yet"))
        if has:
            self.refresh_table(); self.refresh_stats()
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(0)
            QMessageBox.information(self, "Schema missing",
                                    "Connected. Click 'Create schema' then 'Load temporary sample data'.")

    def on_create_schema(self):
        try:
            self.db.create_schema()
        except DbError as exc:
            return self._error(exc)
        self.status.setText("Schema created.")
        self.refresh_table(); self.refresh_stats()

    def on_seed(self):
        try:
            self.db.load_sample_data()
        except DbError as exc:
            return self._error(exc)
        self.status.setText("Temporary sample data loaded.")
        self.refresh_table(); self.refresh_stats(); self._refresh_qgis_layers()
        self.tabs.setCurrentIndex(1)

    def on_drop(self):
        if QMessageBox.question(self, "Delete schema",
                                "This permanently deletes schema '%s' and ALL its data. Continue?" % SCHEMA
                                ) != QMessageBox.Yes:
            return
        try:
            self.db.drop_schema()
        except DbError as exc:
            return self._error(exc)
        self.status.setText("Schema deleted.")
        self.table.setRowCount(0); self.stats.setRowCount(0)

    # ---- facilities --------------------------------------------------
    def refresh_table(self, *_):
        if not self.db.connected:
            return
        try:
            if not self.db.schema_exists():
                self.table.setRowCount(0)
                return
            rows = self.db.list_facilities(self.search.text().strip(),
                                           self.f_type.currentData() or "", self.f_own.currentData() or "")
        except DbError as exc:
            return self._error(exc)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            vals = [rec["id"], rec["name"], rec["facility_type"], rec["ownership"],
                    rec["traditional_authority"] or "", rec["beds"], rec["staff_count"],
                    rec["catchment_population"] or "", "Yes" if rec["has_ambulance"] else "No",
                    "Yes" if rec["has_electricity"] else "No", "Yes" if rec["is_sample"] else ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)  # numeric values sort numerically
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.count_label.setText("%d facilities shown" % len(rows))

    def on_add(self):
        self._open_form(None)

    def on_edit(self, *_):
        fid = self._selected_id()
        if fid is None:
            return
        try:
            rec = self.db.get_facility(fid)
        except DbError as exc:
            return self._error(exc)
        self._open_form(rec)

    def _open_form(self, rec):
        self.form = FacilityForm(self.iface, rec, self)
        self.form.setModal(False)
        self.form.accepted.connect(lambda: self._save_form(rec))
        self.form.show()

    def _save_form(self, rec):
        vals = self.form.values()
        try:
            if rec:
                self.db.update_facility(rec["id"], vals)
            else:
                self.db.insert_facility(vals)
        except DbError as exc:
            return self._error(exc)
        self.refresh_table(); self.refresh_stats(); self._refresh_qgis_layers()

    def on_delete(self):
        fid = self._selected_id()
        if fid is None:
            return
        if QMessageBox.question(self, "Delete facility", "Delete the selected facility?") != QMessageBox.Yes:
            return
        try:
            self.db.delete_facility(fid)
        except DbError as exc:
            return self._error(exc)
        self.refresh_table(); self.refresh_stats(); self._refresh_qgis_layers()

    def on_zoom(self):
        fid = self._selected_id()
        if fid is None:
            return
        try:
            rec = self.db.get_facility(fid)
        except DbError as exc:
            return self._error(exc)
        self._zoom_to_lonlat(rec["lon"], rec["lat"], 0.02)

    # ---- map ---------------------------------------------------------
    def _zoom_to_lonlat(self, lon, lat, pad):
        canvas = self.iface.mapCanvas()
        src = QgsCoordinateReferenceSystem("EPSG:4326")
        dst = canvas.mapSettings().destinationCrs()
        xf = QgsCoordinateTransform(src, dst, QgsProject.instance())
        rect = xf.transformBoundingBox(QgsRectangle(lon - pad, lat - pad, lon + pad, lat + pad))
        canvas.setExtent(rect); canvas.refresh()

    def on_zoom_district(self):
        x1, y1, x2, y2 = MULANJE_EXTENT
        self._zoom_to_lonlat((x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2)

    def on_add_osm(self):
        uri = "type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0"
        lyr = QgsRasterLayer(uri, "OpenStreetMap", "wms")
        if not lyr.isValid():
            return QMessageBox.warning(self, "Basemap", "Could not load the OpenStreetMap layer.")
        QgsProject.instance().addMapLayer(lyr, False)
        # append at the bottom of the layer tree so the facilities stay visible on top
        QgsProject.instance().layerTreeRoot().insertLayer(-1, lyr)

    def on_add_layer(self):
        if not self.db.connected:
            return
        try:
            if not self.db.schema_exists():
                return QMessageBox.information(self, "No data", "Create the schema first.")
        except DbError as exc:
            return self._error(exc)
        uri = QgsDataSourceUri()
        p = self.db.params
        uri.setConnection(p["host"], str(p["port"]), p["dbname"], p["user"], p["password"])
        uri.setDataSource(SCHEMA, TABLE, "geom", "", "id")
        lyr = QgsVectorLayer(uri.uri(False), LAYER_NAME, "postgres")
        if not lyr.isValid():
            return QMessageBox.warning(self, "Layer", "QGIS could not load the PostGIS layer.")
        cats = []
        for t, col in TYPE_COLOURS.items():
            sym = QgsSymbol.defaultSymbol(lyr.geometryType())
            sym.setColor(QColor(col)); sym.setSize(3.5 if t == "Hospital" else 2.8)
            cats.append(QgsRendererCategory(t, sym, t))
        lyr.setRenderer(QgsCategorizedSymbolRenderer("facility_type", cats))
        lab = QgsPalLayerSettings(); lab.fieldName = "name"; lab.enabled = True
        lyr.setLabeling(QgsVectorLayerSimpleLabeling(lab)); lyr.setLabelsEnabled(True)
        QgsProject.instance().addMapLayer(lyr)
        self.iface.setActiveLayer(lyr)
        self.on_zoom_district()

    def on_nearest_tool(self):
        canvas = self.iface.mapCanvas()
        self.near_tool = QgsMapToolEmitPoint(canvas)
        self.near_tool.canvasClicked.connect(self._nearest_clicked)
        canvas.setMapTool(self.near_tool)
        self.iface.messageBar().pushInfo("Mulanje Health", "Click a location on the map.")

    def _nearest_clicked(self, point, _button):
        ll = to_wgs84(self.iface, point)
        try:
            rows = self.db.nearest(ll.x(), ll.y(), self.near_n.value())
        except DbError as exc:
            return self._error(exc)
        self.near.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            for c, k in enumerate(("name", "facility_type", "ownership", "distance_km")):
                self.near.setItem(r, c, QTableWidgetItem(str(rec[k])))
        self.status.setText("Nearest facilities to %.5f, %.5f" % (ll.y(), ll.x()))
        self.tabs.setCurrentIndex(2)
        self.show(); self.raise_()

    def refresh_stats(self):
        if not self.db.connected:
            return
        try:
            if not self.db.schema_exists():
                return
            rows = self.db.stats_by_type()
        except DbError as exc:
            return self._error(exc)
        self.stats.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            for c, k in enumerate(("facility_type", "facilities", "beds", "staff", "catchment",
                                   "with_ambulance", "with_electricity")):
                self.stats.setItem(r, c, QTableWidgetItem(str(rec[k])))

    def closeEvent(self, event):
        if self.near_tool is not None:
            self.iface.mapCanvas().unsetMapTool(self.near_tool)
        super().closeEvent(event)


class MulanjeHealthPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.action = QAction(icon, "Mulanje Health Facilities", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToDatabaseMenu("&Mulanje Health Facilities", self.action)

    def unload(self):
        self.iface.removePluginDatabaseMenu("&Mulanje Health Facilities", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.db.close()
            self.dialog.close()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = MainDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
