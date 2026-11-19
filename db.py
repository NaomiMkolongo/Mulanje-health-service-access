"""PostgreSQL/PostGIS access layer for the Mulanje Health Facilities plugin."""
import os

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:  # pragma: no cover
    psycopg2 = None
    HAS_PSYCOPG2 = False

SCHEMA = "mulanje_health"
TABLE = "facility"
FACILITY_TYPES = ["Hospital", "Health Centre", "Dispensary", "Health Post", "Clinic"]
OWNERSHIPS = ["Government", "CHAM", "Private", "NGO"]

_SQL_DIR = os.path.join(os.path.dirname(__file__), "sql")

COLUMNS = ["id", "name", "facility_type", "ownership", "traditional_authority", "beds",
           "staff_count", "catchment_population", "services", "has_ambulance",
           "has_electricity", "is_sample", "notes"]

_SELECT = (
    "SELECT id, name, facility_type, ownership, traditional_authority, beds, staff_count, "
    "catchment_population, services, has_ambulance, has_electricity, is_sample, notes, "
    "ST_Y(geom) AS lat, ST_X(geom) AS lon "
    "FROM {s}.{t}".format(s=SCHEMA, t=TABLE)
)


class DbError(Exception):
    pass


def _read_sql(name):
    with open(os.path.join(_SQL_DIR, name), encoding="utf-8") as fh:
        return fh.read()


class Database:
    def __init__(self):
        self.conn = None
        self.params = {}

    # ---- connection -------------------------------------------------
    def connect(self, host, port, dbname, user, password):
        if not HAS_PSYCOPG2:
            raise DbError("The Python package 'psycopg2' is not available in this QGIS.")
        self.close()
        try:
            self.conn = psycopg2.connect(host=host, port=int(port), dbname=dbname,
                                         user=user, password=password, connect_timeout=8)
            self.conn.autocommit = False
        except Exception as exc:
            self.conn = None
            raise DbError(str(exc).strip())
        self.params = dict(host=host, port=int(port), dbname=dbname, user=user, password=password)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None

    @property
    def connected(self):
        return self.conn is not None and not self.conn.closed

    def _require(self):
        if not self.connected:
            raise DbError("Not connected to a database.")

    def _run(self, sql, args=None, fetch=None):
        self._require()
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, args)
                rows = cur.fetchall() if fetch == "all" else (cur.fetchone() if fetch == "one" else None)
            self.conn.commit()
            return rows
        except Exception as exc:
            self.conn.rollback()
            raise DbError(str(exc).strip())

    # ---- setup ------------------------------------------------------
    def schema_exists(self):
        row = self._run(
            "SELECT to_regclass(%s) IS NOT NULL AS ok", ("{}.{}".format(SCHEMA, TABLE),), "one")
        return bool(row["ok"])

    def create_schema(self):
        self._run(_read_sql("schema.sql"))

    def load_sample_data(self):
        """Replace previous sample rows with the bundled temporary data."""
        if not self.schema_exists():
            self.create_schema()
        self._run(_read_sql("seed.sql"))

    def drop_schema(self):
        self._run("DROP SCHEMA IF EXISTS {} CASCADE".format(SCHEMA))

    # ---- queries ----------------------------------------------------
    def list_facilities(self, text="", ftype="", ownership=""):
        where, args = [], []
        if text:
            where.append("(name ILIKE %s OR traditional_authority ILIKE %s OR services ILIKE %s)")
            like = "%{}%".format(text)
            args += [like, like, like]
        if ftype:
            where.append("facility_type = %s")
            args.append(ftype)
        if ownership:
            where.append("ownership = %s")
            args.append(ownership)
        sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY name"
        return self._run(sql, args, "all")

    def get_facility(self, fid):
        return self._run(_SELECT + " WHERE id = %s", (fid,), "one")

    def insert_facility(self, v):
        row = self._run(
            "INSERT INTO {s}.{t} (name, facility_type, ownership, traditional_authority, beds, "
            "staff_count, catchment_population, services, has_ambulance, has_electricity, notes, geom) "
            "VALUES (%(name)s, %(facility_type)s, %(ownership)s, %(traditional_authority)s, %(beds)s, "
            "%(staff_count)s, %(catchment_population)s, %(services)s, %(has_ambulance)s, "
            "%(has_electricity)s, %(notes)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)) "
            "RETURNING id".format(s=SCHEMA, t=TABLE), v, "one")
        return row["id"]

    def update_facility(self, fid, v):
        v = dict(v, id=fid)
        self._run(
            "UPDATE {s}.{t} SET name=%(name)s, facility_type=%(facility_type)s, "
            "ownership=%(ownership)s, traditional_authority=%(traditional_authority)s, "
            "beds=%(beds)s, staff_count=%(staff_count)s, "
            "catchment_population=%(catchment_population)s, services=%(services)s, "
            "has_ambulance=%(has_ambulance)s, has_electricity=%(has_electricity)s, "
            "notes=%(notes)s, is_sample=false, "
            "geom=ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) "
            "WHERE id=%(id)s".format(s=SCHEMA, t=TABLE), v)

    def delete_facility(self, fid):
        self._run("DELETE FROM {}.{} WHERE id = %s".format(SCHEMA, TABLE), (fid,))

    def stats_by_type(self):
        return self._run(
            "SELECT facility_type, count(*) AS facilities, COALESCE(sum(beds),0) AS beds, "
            "COALESCE(sum(staff_count),0) AS staff, COALESCE(sum(catchment_population),0) AS catchment, "
            "count(*) FILTER (WHERE has_ambulance) AS with_ambulance, "
            "count(*) FILTER (WHERE has_electricity) AS with_electricity "
            "FROM {}.{} GROUP BY facility_type ORDER BY facilities DESC".format(SCHEMA, TABLE),
            None, "all")

    def nearest(self, lon, lat, limit=5):
        return self._run(
            "SELECT name, facility_type, ownership, "
            "round((ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)/1000.0)::numeric, 2) "
            "AS distance_km FROM {}.{} ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) "
            "LIMIT %s".format(SCHEMA, TABLE),
            (lon, lat, lon, lat, limit), "all")
