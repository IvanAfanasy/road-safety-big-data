CREATE OR REPLACE VIEW public.collisions_dashboard AS
SELECT
    collision_index, collision_year, date AS collision_date,
    EXTRACT(HOUR FROM time)::integer AS hour,
    EXTRACT(ISODOW FROM date)::integer AS weekday,
    speed_limit, light_conditions, police_force, collision_severity,
    CASE WHEN collision_severity IN (1, 2) THEN 1
         WHEN collision_severity = 3 THEN 0 END AS severe,
    CASE WHEN speed_limit IN (50, 60, 70) THEN '50–70 mph'
         WHEN speed_limit IN (20, 30) THEN '20–30 mph'
         WHEN speed_limit = 40 THEN '40 mph'
         ELSE 'Неизвестно/другое' END AS speed_group,
    CASE WHEN light_conditions = 1 THEN 'Дневной свет'
         WHEN light_conditions = 6 THEN 'Без освещения'
         ELSE 'Другие/неизвестные условия' END AS lighting_group
FROM public.collisions;
