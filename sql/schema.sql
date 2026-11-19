-- Mulanje health facilities schema (PostgreSQL + PostGIS)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS mulanje_health;

CREATE TABLE IF NOT EXISTS mulanje_health.facility (
    id                 serial PRIMARY KEY,
    name               text NOT NULL,
    facility_type      text NOT NULL
        CHECK (facility_type IN ('Hospital','Health Centre','Dispensary','Health Post','Clinic')),
    ownership          text NOT NULL DEFAULT 'Government'
        CHECK (ownership IN ('Government','CHAM','Private','NGO')),
    traditional_authority text,
    beds               integer NOT NULL DEFAULT 0 CHECK (beds >= 0),
    staff_count        integer NOT NULL DEFAULT 0 CHECK (staff_count >= 0),
    catchment_population integer CHECK (catchment_population >= 0),
    services           text,
    has_ambulance      boolean NOT NULL DEFAULT false,
    has_electricity    boolean NOT NULL DEFAULT false,
    is_sample          boolean NOT NULL DEFAULT false,
    notes              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    geom               geometry(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS facility_geom_gix ON mulanje_health.facility USING gist (geom);
CREATE INDEX IF NOT EXISTS facility_type_idx ON mulanje_health.facility (facility_type);
