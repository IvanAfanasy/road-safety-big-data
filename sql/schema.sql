CREATE TABLE IF NOT EXISTS public.collisions (
    collision_index TEXT PRIMARY KEY,
    collision_year SMALLINT NOT NULL,
    collision_severity SMALLINT,
    speed_limit SMALLINT,
    light_conditions SMALLINT,
    date DATE,
    time TIME,
    police_force SMALLINT
);

CREATE INDEX IF NOT EXISTS idx_collisions_year
    ON public.collisions (collision_year);