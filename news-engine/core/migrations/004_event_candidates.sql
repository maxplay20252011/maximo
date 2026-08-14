-- 004_event_candidates.sql
-- Candidatos de la autodeteccion de §6.2.
--
-- §6.2 dice: al dispararse un umbral de mercado, buscar noticias de severidad >=3
-- en la ventana de -24h, rankear, archivar la principal y marcar para revision
-- humana. El paso de atribucion necesita un archivo de noticias que hoy no
-- existe: la ingesta es la Tarea 7.
--
-- Sin ese archivo, un detector que igual escribiera en events_archive tendria que
-- inventar el titular y el tipo. Es exactamente lo que §14 prohibe. Entonces la
-- deteccion produce candidatos -- fecha, que umbral se disparo y con que
-- magnitud -- y la promocion a evento archivado exige una causa: una noticia
-- encontrada, o una revision humana que escriba el titular y el tipo.
--
-- Es una tabla mas alla de las 8 de §3. La alternativa era llenar el archivo
-- historico de titulares fabricados.

CREATE TABLE event_candidates (
    candidate_id      TEXT PRIMARY KEY,
    trigger_date      TEXT NOT NULL CHECK (trigger_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    triggers_json     TEXT NOT NULL CHECK (json_valid(triggers_json)),
    metrics_json      TEXT NOT NULL CHECK (json_valid(metrics_json)),
    detected_at_utc   TEXT NOT NULL
                      CHECK (detected_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    reviewed          INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0,1)),
    promoted_event_id TEXT REFERENCES events_archive(event_id) ON DELETE SET NULL,
    review_note       TEXT,
    -- Un candidato promovido esta revisado por definicion.
    CHECK (promoted_event_id IS NULL OR reviewed = 1)
);

CREATE INDEX idx_cand_date    ON event_candidates(trigger_date);
CREATE INDEX idx_cand_pending ON event_candidates(trigger_date) WHERE reviewed = 0;
