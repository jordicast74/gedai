import os
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("GEDAI_DATABASE", BASE_DIR / "gedai.db"))
DEFAULT_ACTUACION = "General"
DEFAULT_FASE = "Inicio"
FASES = ("Inicio", "Instrucción", "Finalización", "Resolución")
DEFAULT_TIPO_DATO = "texto"
TIPOS_DATO = (
    ("texto", "Texto"),
    ("texto_largo", "Texto largo"),
    ("numerico", "Numérico"),
    ("fecha", "Fecha"),
)


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tipos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                descripcion TEXT
            );

            CREATE TABLE IF NOT EXISTS actuaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                descripcion TEXT,
                fase TEXT NOT NULL DEFAULT 'Inicio',
                orden INTEGER
            );

            CREATE TABLE IF NOT EXISTS conjuntos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                actuacion TEXT NOT NULL DEFAULT 'General',
                id_actuacion INTEGER,
                tipo_dato TEXT NOT NULL DEFAULT 'texto',
                documento INTEGER NOT NULL DEFAULT 0,
                dato_sensible INTEGER NOT NULL DEFAULT 0,
                orden INTEGER,
                id_tipo INTEGER NOT NULL,
                FOREIGN KEY (id_actuacion)
                    REFERENCES actuaciones (id)
                    ON UPDATE CASCADE
                    ON DELETE SET NULL,
                FOREIGN KEY (id_tipo)
                    REFERENCES tipos (id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS conjuntos_comunes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                descripcion TEXT
            );

            CREATE TABLE IF NOT EXISTS clasificaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                descripcion TEXT
            );

            CREATE TABLE IF NOT EXISTS conjunto_clasificacion (
                id_conjunto INTEGER NOT NULL,
                id_clasificacion INTEGER NOT NULL,
                PRIMARY KEY (id_conjunto, id_clasificacion),
                FOREIGN KEY (id_conjunto)
                    REFERENCES conjuntos (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
                FOREIGN KEY (id_clasificacion)
                    REFERENCES clasificaciones (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS conjunto_comun_clasificacion (
                id_conjunto_comun INTEGER NOT NULL,
                id_clasificacion INTEGER NOT NULL,
                PRIMARY KEY (id_conjunto_comun, id_clasificacion),
                FOREIGN KEY (id_conjunto_comun)
                    REFERENCES conjuntos_comunes (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
                FOREIGN KEY (id_clasificacion)
                    REFERENCES clasificaciones (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS expedientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_tipo INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Abierto',
                fecha_creacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                fecha_actualizacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_tipo)
                    REFERENCES tipos (id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS expediente_valores_comunes (
                id_expediente INTEGER NOT NULL,
                id_conjunto_comun INTEGER NOT NULL,
                valor TEXT,
                PRIMARY KEY (id_expediente, id_conjunto_comun),
                FOREIGN KEY (id_expediente)
                    REFERENCES expedientes (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
                FOREIGN KEY (id_conjunto_comun)
                    REFERENCES conjuntos_comunes (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS expediente_valores (
                id_expediente INTEGER NOT NULL,
                id_conjunto INTEGER NOT NULL,
                valor TEXT,
                documento INTEGER NOT NULL DEFAULT 0,
                dato_sensible INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (id_expediente, id_conjunto),
                FOREIGN KEY (id_expediente)
                    REFERENCES expedientes (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
                FOREIGN KEY (id_conjunto)
                    REFERENCES conjuntos (id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            );
            """
        )
        _asegurar_columna_actuacion(connection)
        _asegurar_columna_fase_actuacion(connection)
        _asegurar_columna_orden_actuacion(connection)
        _normalizar_actuaciones_existentes(connection)
        _asegurar_columna_id_actuacion(connection)
        _asegurar_columna_tipo_dato(connection)
        _asegurar_columna_documento(connection)
        _asegurar_columna_dato_sensible(connection)
        _asegurar_columna_orden(connection)
        columna_valor_documento_creada = _asegurar_columna_valor_documento(connection)
        columna_valor_dato_sensible_creada = (
            _asegurar_columna_valor_dato_sensible(connection)
        )
        _sincronizar_actuaciones_existentes(connection)
        _normalizar_orden_actuaciones(connection)
        _normalizar_orden_conjuntos(connection)
        if columna_valor_documento_creada or columna_valor_dato_sensible_creada:
            _sincronizar_metadatos_valores_existentes(connection)


def crear_tipo(nombre, descripcion):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO tipos (nombre, descripcion) VALUES (?, ?)",
            (nombre, descripcion),
        )


def listar_tipos():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                t.id,
                t.nombre,
                t.descripcion,
                COUNT(c.id) AS total_conjuntos
            FROM tipos AS t
            LEFT JOIN conjuntos AS c ON c.id_tipo = t.id
            GROUP BY t.id
            ORDER BY t.nombre
            """
        ).fetchall()


def obtener_tipo(id_tipo):
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, nombre, descripcion FROM tipos WHERE id = ?",
            (id_tipo,),
        ).fetchone()


def crear_actuacion(nombre, descripcion, fase=DEFAULT_FASE):
    fase = _normalizar_fase(fase)
    with get_connection() as connection:
        orden = _siguiente_orden_actuacion(connection)
        cursor = connection.execute(
            """
            INSERT INTO actuaciones (nombre, descripcion, fase, orden)
            VALUES (?, ?, ?, ?)
            """,
            (nombre, descripcion, fase, orden),
        )
        return cursor.lastrowid


def actualizar_actuacion(id_actuacion, nombre, descripcion, fase=DEFAULT_FASE):
    nombre = _texto_obligatorio(nombre, "nombre")
    descripcion = _texto_opcional(descripcion)
    fase = _normalizar_fase(fase)

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE actuaciones
            SET nombre = ?, descripcion = ?, fase = ?
            WHERE id = ?
            """,
            (nombre, descripcion, fase, id_actuacion),
        )
        if not cursor.rowcount:
            return False

        connection.execute(
            """
            UPDATE conjuntos
            SET actuacion = ?
            WHERE id_actuacion = ?
            """,
            (nombre, id_actuacion),
        )
        return True


def eliminar_actuacion(id_actuacion):
    with get_connection() as connection:
        actuacion = connection.execute(
            """
            SELECT id, nombre
            FROM actuaciones
            WHERE id = ?
            """,
            (id_actuacion,),
        ).fetchone()

        if not actuacion:
            return False

        total_asociados = connection.execute(
            "SELECT COUNT(*) FROM conjuntos WHERE id_actuacion = ?",
            (id_actuacion,),
        ).fetchone()[0]

        if total_asociados:
            id_general = None
            if actuacion["nombre"].strip().lower() != DEFAULT_ACTUACION.lower():
                id_general = _crear_o_actualizar_actuacion(
                    connection,
                    DEFAULT_ACTUACION,
                    "",
                )
            connection.execute(
                """
                UPDATE conjuntos
                SET id_actuacion = ?, actuacion = ?
                WHERE id_actuacion = ?
                """,
                (id_general, DEFAULT_ACTUACION, id_actuacion),
            )

        connection.execute(
            "DELETE FROM actuaciones WHERE id = ?",
            (id_actuacion,),
        )
        return True


def listar_actuaciones():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                a.id,
                a.nombre,
                a.descripcion,
                a.fase,
                a.orden,
                COUNT(c.id) AS total_conjuntos
            FROM actuaciones AS a
            LEFT JOIN conjuntos AS c ON c.id_actuacion = a.id
            GROUP BY a.id
            ORDER BY
                CASE a.fase
                    WHEN 'Inicio' THEN 1
                    WHEN 'Instrucción' THEN 2
                    WHEN 'Finalización' THEN 3
                    WHEN 'Resolución' THEN 4
                    ELSE 5
                END,
                COALESCE(a.orden, a.id),
                a.nombre
            """
        ).fetchall()


def obtener_actuacion(id_actuacion):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, nombre, descripcion, fase, orden
            FROM actuaciones
            WHERE id = ?
            """,
            (id_actuacion,),
        ).fetchone()


def reordenar_actuaciones(ids_actuacion):
    ids_limpios = []
    vistos = set()
    for id_actuacion in ids_actuacion:
        try:
            id_entero = int(id_actuacion)
        except (TypeError, ValueError):
            continue
        if id_entero not in vistos:
            ids_limpios.append(id_entero)
            vistos.add(id_entero)

    if not ids_limpios:
        return 0

    with get_connection() as connection:
        connection.executemany(
            """
            UPDATE actuaciones
            SET orden = ?
            WHERE id = ?
            """,
            [
                ((posicion + 1) * 10, id_actuacion)
                for posicion, id_actuacion in enumerate(ids_limpios)
            ],
        )
        return connection.total_changes


def crear_conjunto(
    nombre,
    descripcion,
    id_tipo,
    actuacion=None,
    tipo_dato=DEFAULT_TIPO_DATO,
    documento=False,
    dato_sensible=False,
):
    actuacion = _texto_opcional(actuacion) or DEFAULT_ACTUACION
    tipo_dato = _normalizar_tipo_dato(tipo_dato)
    with get_connection() as connection:
        id_actuacion = _crear_o_actualizar_actuacion(connection, actuacion, "")
        orden = _siguiente_orden_conjunto(connection, id_tipo, actuacion)
        cursor = connection.execute(
            """
            INSERT INTO conjuntos
                (
                    nombre,
                    descripcion,
                    actuacion,
                    id_actuacion,
                    tipo_dato,
                    documento,
                    dato_sensible,
                    orden,
                    id_tipo
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nombre,
                descripcion,
                actuacion,
                id_actuacion,
                tipo_dato,
                _entero_booleano(documento),
                _entero_booleano(dato_sensible),
                orden,
                id_tipo,
            ),
        )
        return cursor.lastrowid


def crear_conjunto_comun(nombre, descripcion):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO conjuntos_comunes (nombre, descripcion)
            VALUES (?, ?)
            """,
            (nombre, descripcion),
        )
        return cursor.lastrowid


def listar_conjuntos_comunes():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, nombre, descripcion
            FROM conjuntos_comunes
            ORDER BY nombre
            """
        ).fetchall()


def listar_conjuntos():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                c.id,
                c.nombre,
                c.descripcion,
                COALESCE(
                    NULLIF(TRIM(a.nombre), ''),
                    NULLIF(TRIM(c.actuacion), ''),
                    ?
                ) AS actuacion,
                c.id_actuacion,
                c.tipo_dato,
                c.documento,
                c.dato_sensible,
                c.orden,
                c.id_tipo,
                t.nombre AS tipo_nombre
            FROM conjuntos AS c
            JOIN tipos AS t ON t.id = c.id_tipo
            LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
            ORDER BY t.nombre, actuacion, COALESCE(c.orden, c.id), c.nombre
            """,
            (DEFAULT_ACTUACION,),
        ).fetchall()


def listar_conjuntos_por_tipo(id_tipo, actuacion=None):
    with get_connection() as connection:
        parametros = [DEFAULT_ACTUACION, id_tipo]
        filtro_actuacion = ""

        if actuacion:
            filtro_actuacion = "AND actuacion = ?"
            parametros.append(actuacion)

        return connection.execute(
            f"""
            SELECT
                id,
                nombre,
                descripcion,
                actuacion,
                id_actuacion,
                tipo_dato,
                documento,
                dato_sensible,
                orden,
                id_tipo
            FROM (
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    COALESCE(
                        NULLIF(TRIM(a.nombre), ''),
                        NULLIF(TRIM(c.actuacion), ''),
                        ?
                    ) AS actuacion,
                    c.id_actuacion,
                    c.tipo_dato,
                    c.documento,
                    c.dato_sensible,
                    c.orden,
                    c.id_tipo
                FROM conjuntos AS c
                LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
            )
            WHERE id_tipo = ?
            {filtro_actuacion}
            ORDER BY actuacion, COALESCE(orden, id), nombre
            """,
            parametros,
        ).fetchall()


def obtener_conjunto(id_conjunto):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                c.id,
                c.nombre,
                c.descripcion,
                COALESCE(
                    NULLIF(TRIM(a.nombre), ''),
                    NULLIF(TRIM(c.actuacion), ''),
                    ?
                ) AS actuacion,
                c.id_actuacion,
                c.tipo_dato,
                c.documento,
                c.dato_sensible,
                c.orden,
                c.id_tipo,
                t.nombre AS tipo_nombre
            FROM conjuntos AS c
            JOIN tipos AS t ON t.id = c.id_tipo
            LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
            WHERE c.id = ?
            """,
            (DEFAULT_ACTUACION, id_conjunto),
        ).fetchone()


def actualizar_conjunto(
    id_conjunto,
    nombre,
    descripcion,
    id_tipo,
    actuacion,
    tipo_dato=DEFAULT_TIPO_DATO,
    documento=False,
    dato_sensible=False,
):
    nombre = _texto_obligatorio(nombre, "nombre")
    actuacion = _texto_opcional(actuacion) or DEFAULT_ACTUACION
    tipo_dato = _normalizar_tipo_dato(tipo_dato)

    with get_connection() as connection:
        conjunto = connection.execute(
            """
            SELECT id
            FROM conjuntos
            WHERE id = ?
            """,
            (id_conjunto,),
        ).fetchone()
        if not conjunto:
            return False

        id_actuacion = _crear_o_actualizar_actuacion(connection, actuacion, "")
        connection.execute(
            """
            UPDATE conjuntos
            SET
                nombre = ?,
                descripcion = ?,
                id_tipo = ?,
                actuacion = ?,
                id_actuacion = ?,
                tipo_dato = ?,
                documento = ?,
                dato_sensible = ?
            WHERE id = ?
            """,
            (
                nombre,
                _texto_opcional(descripcion),
                id_tipo,
                actuacion,
                id_actuacion,
                tipo_dato,
                _entero_booleano(documento),
                _entero_booleano(dato_sensible),
                id_conjunto,
            ),
        )
        return True


def reordenar_conjuntos(ids_conjunto):
    ids_limpios = []
    vistos = set()
    for id_conjunto in ids_conjunto:
        try:
            id_entero = int(id_conjunto)
        except (TypeError, ValueError):
            continue
        if id_entero not in vistos:
            ids_limpios.append(id_entero)
            vistos.add(id_entero)

    if not ids_limpios:
        return 0

    with get_connection() as connection:
        connection.executemany(
            """
            UPDATE conjuntos
            SET orden = ?
            WHERE id = ?
            """,
            [
                ((posicion + 1) * 10, id_conjunto)
                for posicion, id_conjunto in enumerate(ids_limpios)
            ],
        )
        return connection.total_changes


def listar_actuaciones_por_tipo(id_tipo):
    with get_connection() as connection:
        return [
            fila["actuacion"]
            for fila in connection.execute(
                """
                SELECT actuacion
                FROM (
                    SELECT
                        c.id,
                        a.fase,
                        a.orden,
                        COALESCE(
                            NULLIF(TRIM(a.nombre), ''),
                            NULLIF(TRIM(c.actuacion), ''),
                            ?
                        ) AS actuacion
                    FROM conjuntos AS c
                    LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
                    WHERE c.id_tipo = ?
                )
                GROUP BY actuacion
                ORDER BY
                    MIN(
                        CASE fase
                            WHEN 'Inicio' THEN 1
                            WHEN 'Instrucción' THEN 2
                            WHEN 'Finalización' THEN 3
                            WHEN 'Resolución' THEN 4
                            ELSE 5
                        END
                    ),
                    MIN(COALESCE(orden, id)),
                    MIN(id)
                """,
                (DEFAULT_ACTUACION, id_tipo),
            ).fetchall()
        ]


def crear_expediente(id_tipo, valores_comunes):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO expedientes (id_tipo, nombre)
            VALUES (?, ?)
            """,
            (id_tipo, "Nuevo expediente"),
        )
        id_expediente = cursor.lastrowid
        _guardar_valores_comunes(connection, id_expediente, valores_comunes)
        nombre = _nombre_expediente_desde_valores(connection, id_expediente)
        connection.execute(
            """
            UPDATE expedientes
            SET nombre = ?, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nombre, id_expediente),
        )
        return id_expediente


def listar_expedientes():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                e.id,
                e.nombre,
                e.estado,
                e.fecha_creacion,
                e.fecha_actualizacion,
                e.id_tipo,
                t.nombre AS tipo_nombre,
                COUNT(DISTINCT ev.id_conjunto) AS valores_especificos,
                COUNT(DISTINCT evc.id_conjunto_comun) AS valores_comunes
            FROM expedientes AS e
            JOIN tipos AS t ON t.id = e.id_tipo
            LEFT JOIN expediente_valores AS ev
                ON ev.id_expediente = e.id
                AND TRIM(COALESCE(ev.valor, '')) <> ''
            LEFT JOIN expediente_valores_comunes AS evc
                ON evc.id_expediente = e.id
                AND TRIM(COALESCE(evc.valor, '')) <> ''
            GROUP BY e.id
            ORDER BY e.fecha_actualizacion DESC, e.id DESC
            """
        ).fetchall()


def obtener_expediente(id_expediente):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                e.id,
                e.nombre,
                e.estado,
                e.fecha_creacion,
                e.fecha_actualizacion,
                e.id_tipo,
                t.nombre AS tipo_nombre
            FROM expedientes AS e
            JOIN tipos AS t ON t.id = e.id_tipo
            WHERE e.id = ?
            """,
            (id_expediente,),
        ).fetchone()


def obtener_valores_comunes_expediente(id_expediente):
    with get_connection() as connection:
        return {
            fila["id_conjunto_comun"]: fila["valor"] or ""
            for fila in connection.execute(
                """
                SELECT id_conjunto_comun, valor
                FROM expediente_valores_comunes
                WHERE id_expediente = ?
                """,
                (id_expediente,),
            ).fetchall()
        }


def guardar_datos_comunes_expediente(id_expediente, valores_comunes):
    with get_connection() as connection:
        _guardar_valores_comunes(connection, id_expediente, valores_comunes)
        nombre = _nombre_expediente_desde_valores(connection, id_expediente)
        connection.execute(
            """
            UPDATE expedientes
            SET nombre = ?, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nombre, id_expediente),
        )


def obtener_valores_actuacion_expediente(id_expediente, actuacion):
    with get_connection() as connection:
        expediente = connection.execute(
            "SELECT id_tipo FROM expedientes WHERE id = ?",
            (id_expediente,),
        ).fetchone()

        if not expediente:
            return {}

        return {
            fila["id_conjunto"]: {
                "valor": fila["valor"] or "",
                "documento": bool(fila["documento"]),
                "dato_sensible": bool(fila["dato_sensible"]),
            }
            for fila in connection.execute(
                """
                SELECT
                    ev.id_conjunto,
                    ev.valor,
                    ev.documento,
                    ev.dato_sensible
                FROM expediente_valores AS ev
                JOIN conjuntos AS c ON c.id = ev.id_conjunto
                LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
                WHERE ev.id_expediente = ?
                    AND c.id_tipo = ?
                    AND COALESCE(
                        NULLIF(TRIM(a.nombre), ''),
                        NULLIF(TRIM(c.actuacion), ''),
                        ?
                    ) = ?
                """,
                (id_expediente, expediente["id_tipo"], DEFAULT_ACTUACION, actuacion),
            ).fetchall()
        }


def guardar_valores_actuacion_expediente(id_expediente, valores):
    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO expediente_valores
                (id_expediente, id_conjunto, valor, documento, dato_sensible)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id_expediente, id_conjunto)
            DO UPDATE SET
                valor = excluded.valor,
                documento = excluded.documento,
                dato_sensible = excluded.dato_sensible
            """,
            [
                (
                    id_expediente,
                    id_conjunto,
                    dato["valor"],
                    _entero_booleano(dato["documento"]),
                    _entero_booleano(dato["dato_sensible"]),
                )
                for id_conjunto, dato in _normalizar_valores_actuacion(valores).items()
            ],
        )
        connection.execute(
            """
            UPDATE expedientes
            SET fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (id_expediente,),
        )


def listar_progreso_actuaciones(id_expediente):
    with get_connection() as connection:
        expediente = connection.execute(
            "SELECT id_tipo FROM expedientes WHERE id = ?",
            (id_expediente,),
        ).fetchone()

        if not expediente:
            return []

        return connection.execute(
            """
            SELECT
                datos.actuacion,
                MIN(datos.fase) AS fase,
                COUNT(datos.id) AS total_campos,
                SUM(
                    CASE
                        WHEN TRIM(COALESCE(ev.valor, '')) <> '' THEN 1
                        ELSE 0
                    END
                ) AS campos_rellenados
            FROM (
                SELECT
                    c.id,
                    c.id_tipo,
                    a.fase,
                    a.orden,
                    COALESCE(
                        NULLIF(TRIM(a.nombre), ''),
                        NULLIF(TRIM(c.actuacion), ''),
                        ?
                    ) AS actuacion
                FROM conjuntos AS c
                LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
            ) AS datos
            LEFT JOIN expediente_valores AS ev
                ON ev.id_conjunto = datos.id
                AND ev.id_expediente = ?
            WHERE datos.id_tipo = ?
            GROUP BY datos.actuacion
            ORDER BY
                MIN(
                    CASE datos.fase
                        WHEN 'Inicio' THEN 1
                        WHEN 'Instrucción' THEN 2
                        WHEN 'Finalización' THEN 3
                        WHEN 'Resolución' THEN 4
                        ELSE 5
                    END
                ),
                MIN(COALESCE(datos.orden, datos.id)),
                MIN(datos.id)
            """,
            (DEFAULT_ACTUACION, id_expediente, expediente["id_tipo"]),
        ).fetchall()


def obtener_resumen():
    with get_connection() as connection:
        tipos = connection.execute("SELECT COUNT(*) FROM tipos").fetchone()[0]
        conjuntos_especificos = connection.execute(
            "SELECT COUNT(*) FROM conjuntos"
        ).fetchone()[0]
        conjuntos_comunes = connection.execute(
            "SELECT COUNT(*) FROM conjuntos_comunes"
        ).fetchone()[0]
        actuaciones = connection.execute(
            "SELECT COUNT(*) FROM actuaciones"
        ).fetchone()[0]
        expedientes = connection.execute("SELECT COUNT(*) FROM expedientes").fetchone()[0]

    return {
        "expedientes": expedientes,
        "tipos": tipos,
        "conjuntos": conjuntos_especificos,
        "conjuntos_comunes": conjuntos_comunes,
        "actuaciones": actuaciones,
    }


def exportar_catalogo(id_tipo=None):
    with get_connection() as connection:
        parametros = ()
        filtro_tipo = ""

        if id_tipo is not None:
            filtro_tipo = "WHERE id = ?"
            parametros = (id_tipo,)

        tipos = connection.execute(
            f"""
            SELECT id, nombre, descripcion
            FROM tipos
            {filtro_tipo}
            ORDER BY nombre
            """,
            parametros,
        ).fetchall()

        catalogo = {
            "version": "3.0",
            "origen": "GEDAI",
            "datos_comunes_expediente": [
                {
                    "nombre": conjunto["nombre"],
                    "descripcion": conjunto["descripcion"] or "",
                }
                for conjunto in connection.execute(
                    """
                    SELECT nombre, descripcion
                    FROM conjuntos_comunes
                    ORDER BY nombre
                    """
                ).fetchall()
            ],
            "procedimientos": [],
        }

        for tipo in tipos:
            estructura = connection.execute(
                """
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    COALESCE(
                        NULLIF(TRIM(a.nombre), ''),
                        NULLIF(TRIM(c.actuacion), ''),
                        ?
                    ) AS actuacion,
                    a.descripcion AS actuacion_descripcion,
                    COALESCE(a.fase, ?) AS fase,
                    a.orden AS actuacion_orden,
                    c.tipo_dato,
                    c.documento,
                    c.dato_sensible,
                    c.orden
                FROM conjuntos AS c
                LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
                WHERE c.id_tipo = ?
                ORDER BY
                    CASE COALESCE(a.fase, ?)
                        WHEN 'Inicio' THEN 1
                        WHEN 'Instrucción' THEN 2
                        WHEN 'Finalización' THEN 3
                        WHEN 'Resolución' THEN 4
                        ELSE 5
                    END,
                    COALESCE(a.orden, c.id),
                    actuacion,
                    COALESCE(c.orden, c.id),
                    c.nombre
                """,
                (DEFAULT_ACTUACION, DEFAULT_FASE, tipo["id"], DEFAULT_FASE),
            ).fetchall()

            fases = {}
            for campo in estructura:
                nombre_actuacion = campo["actuacion"] or DEFAULT_ACTUACION
                fase = _normalizar_fase(campo["fase"])
                if fase not in fases:
                    fases[fase] = {
                        "nombre": fase,
                        "tramites_o_actuaciones": {},
                    }
                tramites = fases[fase]["tramites_o_actuaciones"]
                if nombre_actuacion not in tramites:
                    tramites[nombre_actuacion] = {
                        "nombre": nombre_actuacion,
                        "descripcion": campo["actuacion_descripcion"] or "",
                        "orden": campo["actuacion_orden"] or 0,
                        "datasets": [],
                    }

                tramites[nombre_actuacion]["datasets"].append(
                    {
                        "nombre": campo["nombre"],
                        "descripcion": campo["descripcion"] or "",
                        "tipo_dato": _normalizar_tipo_dato(campo["tipo_dato"]),
                        "documento": bool(campo["documento"]),
                        "dato_sensible": bool(campo["dato_sensible"]),
                        "orden": campo["orden"] or 0,
                    }
                )

            fases_exportadas = []
            for fase in FASES:
                if fase in fases:
                    fase_exportada = fases[fase]
                    fase_exportada["tramites_o_actuaciones"] = list(
                        fase_exportada["tramites_o_actuaciones"].values()
                    )
                    fases_exportadas.append(fase_exportada)

            catalogo["procedimientos"].append(
                {
                    "nombre": tipo["nombre"],
                    "descripcion": tipo["descripcion"] or "",
                    "fases": fases_exportadas,
                }
            )

        return catalogo


def importar_catalogo(datos):
    if not isinstance(datos, dict):
        raise ValueError("El JSON debe contener un objeto principal.")

    tipos = datos.get(
        "procedimientos",
        datos.get("conjuntos_datos", datos.get("tipos", [])),
    )
    actuaciones = datos.get(
        "tramites_o_actuaciones",
        datos.get("actuaciones", []),
    )
    conjuntos_comunes = datos.get(
        "datos_comunes_expediente",
        datos.get("conjuntos_comunes", []),
    )

    if not isinstance(tipos, list):
        raise ValueError(
            "El campo 'procedimientos' o 'conjuntos_datos' debe ser una lista."
        )
    if not isinstance(actuaciones, list):
        raise ValueError("El campo 'tramites_o_actuaciones' debe ser una lista.")
    if not isinstance(conjuntos_comunes, list):
        raise ValueError("El campo 'datos_comunes_expediente' debe ser una lista.")

    resultado = {
        "tipos_creados": 0,
        "tipos_actualizados": 0,
        "actuaciones_creadas": 0,
        "actuaciones_actualizadas": 0,
        "conjuntos_comunes_creados": 0,
        "conjuntos_comunes_actualizados": 0,
        "conjuntos_creados": 0,
        "conjuntos_actualizados": 0,
    }

    with get_connection() as connection:
        for posicion, actuacion in enumerate(actuaciones, start=1):
            nombre, descripcion, fase, orden = _leer_actuacion_importada(
                actuacion,
                f"tramites_o_actuaciones[{posicion}]",
                DEFAULT_FASE,
            )
            _crear_o_actualizar_actuacion(
                connection,
                nombre,
                descripcion,
                fase,
                resultado,
                orden,
            )

        for posicion, conjunto in enumerate(conjuntos_comunes, start=1):
            if not isinstance(conjunto, dict):
                raise ValueError(
                    f"datos_comunes_expediente[{posicion}] debe ser un objeto."
                )

            nombre_conjunto = _texto_obligatorio(
                conjunto.get("nombre"),
                f"datos_comunes_expediente[{posicion}].nombre",
            )
            descripcion_conjunto = _texto_opcional(conjunto.get("descripcion"))
            _crear_o_actualizar_conjunto_comun(
                connection,
                nombre_conjunto,
                descripcion_conjunto,
                resultado,
            )

        for posicion_tipo, tipo in enumerate(tipos, start=1):
            if not isinstance(tipo, dict):
                raise ValueError(
                    f"conjuntos_datos[{posicion_tipo}] debe ser un objeto."
                )

            nombre_tipo = _texto_obligatorio(
                tipo.get("nombre"),
                f"conjuntos_datos[{posicion_tipo}].nombre",
            )
            descripcion_tipo = _texto_opcional(tipo.get("descripcion"))
            id_tipo = _crear_o_actualizar_tipo(
                connection,
                nombre_tipo,
                descripcion_tipo,
                resultado,
            )

            conjuntos = _leer_conjuntos_importados(tipo, posicion_tipo)

            for posicion_conjunto, (
                conjunto,
                actuacion_por_bloque,
                descripcion_actuacion,
                fase_actuacion,
                orden_actuacion,
            ) in enumerate(conjuntos, start=1):
                if not isinstance(conjunto, dict):
                    raise ValueError(
                        (
                            f"conjuntos_datos[{posicion_tipo}].estructura"
                            f"[{posicion_conjunto}] debe ser un objeto."
                        )
                    )

                nombre_conjunto = _texto_obligatorio(
                    conjunto.get("nombre"),
                    (
                        f"conjuntos_datos[{posicion_tipo}].estructura"
                        f"[{posicion_conjunto}].nombre"
                    ),
                )
                descripcion_conjunto = _texto_opcional(conjunto.get("descripcion"))
                tipo_dato = _normalizar_tipo_dato(
                    conjunto.get(
                        "tipo_dato",
                        conjunto.get("tipoDato", conjunto.get("tipo")),
                    )
                )
                documento = _leer_booleano(conjunto.get("documento"))
                dato_sensible = _leer_booleano(
                    conjunto.get("dato_sensible", conjunto.get("datoSensible"))
                )
                orden_conjunto = _leer_orden_importado(
                    conjunto.get("orden"),
                    (
                        f"conjuntos_datos[{posicion_tipo}].estructura"
                        f"[{posicion_conjunto}].orden"
                    ),
                )
                actuacion_conjunto = (
                    _texto_opcional(conjunto.get("tramite_o_actuacion"))
                    or _texto_opcional(conjunto.get("actuacion"))
                    or actuacion_por_bloque
                    or _inferir_actuacion(nombre_conjunto, descripcion_conjunto)
                )
                _crear_o_actualizar_conjunto(
                    connection,
                    nombre_conjunto,
                    descripcion_conjunto,
                    actuacion_conjunto,
                    descripcion_actuacion,
                    id_tipo,
                    tipo_dato,
                    documento,
                    dato_sensible,
                    resultado,
                    fase_actuacion=fase_actuacion,
                    orden_actuacion=orden_actuacion,
                    orden=orden_conjunto,
                )

    return resultado


def _crear_o_actualizar_tipo(connection, nombre, descripcion, resultado):
    fila = connection.execute(
        "SELECT id, descripcion FROM tipos WHERE LOWER(nombre) = LOWER(?)",
        (nombre,),
    ).fetchone()

    if fila:
        if descripcion and descripcion != (fila["descripcion"] or ""):
            connection.execute(
                "UPDATE tipos SET descripcion = ? WHERE id = ?",
                (descripcion, fila["id"]),
            )
            resultado["tipos_actualizados"] += 1
        return fila["id"]

    cursor = connection.execute(
        "INSERT INTO tipos (nombre, descripcion) VALUES (?, ?)",
        (nombre, descripcion),
    )
    resultado["tipos_creados"] += 1
    return cursor.lastrowid


def _crear_o_actualizar_conjunto(
    connection,
    nombre,
    descripcion,
    actuacion,
    descripcion_actuacion,
    id_tipo,
    tipo_dato,
    documento,
    dato_sensible,
    resultado,
    fase_actuacion=None,
    orden_actuacion=None,
    orden=None,
):
    actuacion = _texto_opcional(actuacion) or DEFAULT_ACTUACION
    tipo_dato = _normalizar_tipo_dato(tipo_dato)
    id_actuacion = _crear_o_actualizar_actuacion(
        connection,
        actuacion,
        descripcion_actuacion,
        fase_actuacion,
        resultado=resultado,
        orden=orden_actuacion,
    )
    fila = connection.execute(
        """
        SELECT
            id,
            descripcion,
            actuacion,
            id_actuacion,
            tipo_dato,
            documento,
            dato_sensible,
            orden
        FROM conjuntos
        WHERE LOWER(nombre) = LOWER(?) AND id_tipo = ? AND id_actuacion = ?
        """,
        (nombre, id_tipo, id_actuacion),
    ).fetchone()

    if fila:
        cambios = {}

        if descripcion and descripcion != (fila["descripcion"] or ""):
            cambios["descripcion"] = descripcion
        if actuacion and actuacion != (fila["actuacion"] or DEFAULT_ACTUACION):
            cambios["actuacion"] = actuacion
        if id_actuacion != fila["id_actuacion"]:
            cambios["id_actuacion"] = id_actuacion
        if tipo_dato != (fila["tipo_dato"] or DEFAULT_TIPO_DATO):
            cambios["tipo_dato"] = tipo_dato
        if _entero_booleano(documento) != fila["documento"]:
            cambios["documento"] = _entero_booleano(documento)
        if _entero_booleano(dato_sensible) != fila["dato_sensible"]:
            cambios["dato_sensible"] = _entero_booleano(dato_sensible)
        if orden is not None and orden != fila["orden"]:
            cambios["orden"] = orden

        if cambios:
            asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
            connection.execute(
                f"UPDATE conjuntos SET {asignaciones} WHERE id = ?",
                [*cambios.values(), fila["id"]],
            )
            resultado["conjuntos_actualizados"] += 1
        return fila["id"]

    cursor = connection.execute(
        """
        INSERT INTO conjuntos
            (
                nombre,
                descripcion,
                actuacion,
                id_actuacion,
                tipo_dato,
                documento,
                dato_sensible,
                orden,
                id_tipo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nombre,
            descripcion,
            actuacion,
            id_actuacion,
            tipo_dato,
            _entero_booleano(documento),
            _entero_booleano(dato_sensible),
            orden
            if orden is not None
            else _siguiente_orden_conjunto(connection, id_tipo, actuacion),
            id_tipo,
        ),
    )
    resultado["conjuntos_creados"] += 1
    return cursor.lastrowid


def _crear_o_actualizar_conjunto_comun(connection, nombre, descripcion, resultado):
    fila = connection.execute(
        """
        SELECT id, descripcion
        FROM conjuntos_comunes
        WHERE LOWER(nombre) = LOWER(?)
        """,
        (nombre,),
    ).fetchone()

    if fila:
        if descripcion and descripcion != (fila["descripcion"] or ""):
            connection.execute(
                "UPDATE conjuntos_comunes SET descripcion = ? WHERE id = ?",
                (descripcion, fila["id"]),
            )
            resultado["conjuntos_comunes_actualizados"] += 1
        return fila["id"]

    cursor = connection.execute(
        """
        INSERT INTO conjuntos_comunes (nombre, descripcion)
        VALUES (?, ?)
        """,
        (nombre, descripcion),
    )
    resultado["conjuntos_comunes_creados"] += 1
    return cursor.lastrowid


def _crear_o_actualizar_actuacion(
    connection,
    nombre,
    descripcion,
    fase=None,
    resultado=None,
    orden=None,
):
    nombre = _texto_obligatorio(nombre, "tramite_o_actuacion")
    descripcion = _texto_opcional(descripcion)
    fila = connection.execute(
        """
        SELECT id, descripcion, fase, orden
        FROM actuaciones
        WHERE LOWER(nombre) = LOWER(?)
        """,
        (nombre,),
    ).fetchone()

    if fila:
        cambios = {}
        if descripcion and descripcion != (fila["descripcion"] or ""):
            cambios["descripcion"] = descripcion
        if fase is not None and _normalizar_fase(fase) != (fila["fase"] or DEFAULT_FASE):
            cambios["fase"] = _normalizar_fase(fase)
        if orden is not None and orden != fila["orden"]:
            cambios["orden"] = orden

        if cambios:
            asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
            connection.execute(
                f"UPDATE actuaciones SET {asignaciones} WHERE id = ?",
                [*cambios.values(), fila["id"]],
            )
            if resultado is not None:
                resultado["actuaciones_actualizadas"] += 1
        return fila["id"]

    orden_final = orden if orden is not None else _siguiente_orden_actuacion(connection)
    cursor = connection.execute(
        """
        INSERT INTO actuaciones (nombre, descripcion, fase, orden)
        VALUES (?, ?, ?, ?)
        """,
        (nombre, descripcion, _normalizar_fase(fase), orden_final),
    )
    if resultado is not None:
        resultado["actuaciones_creadas"] += 1
    return cursor.lastrowid


def _leer_actuacion_importada(valor, campo, fase_default=None):
    if isinstance(valor, str):
        return (
            _texto_obligatorio(valor, campo),
            "",
            _fase_importada(None, fase_default),
            None,
        )
    if isinstance(valor, dict):
        return (
            _texto_obligatorio(valor.get("nombre"), f"{campo}.nombre"),
            _texto_opcional(valor.get("descripcion")),
            _fase_importada(valor.get("fase"), fase_default),
            _leer_orden_importado(valor.get("orden"), f"{campo}.orden"),
        )
    raise ValueError(f"{campo} debe ser texto u objeto.")


def _leer_conjuntos_importados(tipo, posicion_tipo):
    conjuntos_importados = []
    conjuntos = tipo.get("estructura", tipo.get("conjuntos", tipo.get("datasets", [])))
    fases = tipo.get("fases", [])
    actuaciones = tipo.get(
        "tramites_o_actuaciones",
        tipo.get("tramites_actuaciones", tipo.get("actuaciones", [])),
    )

    if not isinstance(conjuntos, list):
        raise ValueError(
            f"conjuntos_datos[{posicion_tipo}].estructura debe ser una lista."
        )
    if not isinstance(actuaciones, list):
        raise ValueError(
            (
                f"conjuntos_datos[{posicion_tipo}].tramites_o_actuaciones"
                " debe ser una lista."
            )
        )
    if not isinstance(fases, list):
        raise ValueError(
            f"conjuntos_datos[{posicion_tipo}].fases debe ser una lista."
        )

    conjuntos_importados.extend((conjunto, "", "", None, None) for conjunto in conjuntos)

    for posicion_actuacion, actuacion in enumerate(actuaciones, start=1):
        if not isinstance(actuacion, dict):
            raise ValueError(
                (
                    f"conjuntos_datos[{posicion_tipo}].tramites_o_actuaciones"
                    f"[{posicion_actuacion}] debe ser un objeto."
                )
            )

        campo_actuacion = (
            f"conjuntos_datos[{posicion_tipo}].tramites_o_actuaciones"
            f"[{posicion_actuacion}]"
        )
        conjuntos_importados.extend(
            _leer_conjuntos_de_actuacion(actuacion, campo_actuacion)
        )

    for posicion_fase, fase in enumerate(fases, start=1):
        if not isinstance(fase, dict):
            raise ValueError(
                (
                    f"conjuntos_datos[{posicion_tipo}].fases"
                    f"[{posicion_fase}] debe ser un objeto."
                )
            )

        nombre_fase = _normalizar_fase(fase.get("nombre", fase.get("fase")))
        tramites = fase.get(
            "tramites_o_actuaciones",
            fase.get("tramites_actuaciones", fase.get("actuaciones", [])),
        )

        if not isinstance(tramites, list):
            raise ValueError(
                (
                    f"conjuntos_datos[{posicion_tipo}].fases"
                    f"[{posicion_fase}].tramites_o_actuaciones debe ser una lista."
                )
            )

        for posicion_actuacion, actuacion in enumerate(tramites, start=1):
            if not isinstance(actuacion, dict):
                raise ValueError(
                    (
                        f"conjuntos_datos[{posicion_tipo}].fases"
                        f"[{posicion_fase}].tramites_o_actuaciones"
                        f"[{posicion_actuacion}] debe ser un objeto."
                    )
                )

            campo_actuacion = (
                f"conjuntos_datos[{posicion_tipo}].fases"
                f"[{posicion_fase}].tramites_o_actuaciones"
                f"[{posicion_actuacion}]"
            )
            conjuntos_importados.extend(
                _leer_conjuntos_de_actuacion(
                    actuacion,
                    campo_actuacion,
                    nombre_fase,
                )
            )

    return conjuntos_importados


def _leer_conjuntos_de_actuacion(actuacion, campo_actuacion, fase_default=None):
    nombre_actuacion, descripcion_actuacion, fase_actuacion, orden_actuacion = (
        _leer_actuacion_importada(
            actuacion,
            campo_actuacion,
            fase_default,
        )
    )
    conjuntos_actuacion = actuacion.get(
        "datasets",
        actuacion.get("estructura", actuacion.get("conjuntos", [])),
    )

    if not isinstance(conjuntos_actuacion, list):
        raise ValueError(f"{campo_actuacion}.datasets debe ser una lista.")

    return [
        (
            conjunto,
            nombre_actuacion,
            descripcion_actuacion,
            fase_actuacion,
            orden_actuacion,
        )
        for conjunto in conjuntos_actuacion
    ]


def _guardar_valores_comunes(connection, id_expediente, valores_comunes):
    connection.executemany(
        """
        INSERT INTO expediente_valores_comunes
            (id_expediente, id_conjunto_comun, valor)
        VALUES (?, ?, ?)
        ON CONFLICT(id_expediente, id_conjunto_comun)
        DO UPDATE SET valor = excluded.valor
        """,
        [
            (id_expediente, id_conjunto_comun, valor)
            for id_conjunto_comun, valor in valores_comunes.items()
        ],
    )


def _normalizar_valores_actuacion(valores):
    valores_normalizados = {}

    for id_conjunto, dato in valores.items():
        if isinstance(dato, dict):
            valores_normalizados[id_conjunto] = {
                "valor": _texto_opcional(dato.get("valor")),
                "documento": _leer_booleano(dato.get("documento")),
                "dato_sensible": _leer_booleano(dato.get("dato_sensible")),
            }
        else:
            valores_normalizados[id_conjunto] = {
                "valor": _texto_opcional(dato),
                "documento": False,
                "dato_sensible": False,
            }

    return valores_normalizados


def _nombre_expediente_desde_valores(connection, id_expediente):
    fila_titulo = connection.execute(
        """
        SELECT evc.valor
        FROM expediente_valores_comunes AS evc
        JOIN conjuntos_comunes AS cc ON cc.id = evc.id_conjunto_comun
        WHERE evc.id_expediente = ?
            AND (
                LOWER(cc.nombre) LIKE '%titulo%'
                OR LOWER(cc.nombre) LIKE '%título%'
            )
            AND TRIM(COALESCE(evc.valor, '')) <> ''
        ORDER BY cc.id
        LIMIT 1
        """,
        (id_expediente,),
    ).fetchone()

    if fila_titulo:
        return fila_titulo["valor"].strip()

    return f"Expediente {id_expediente}"


def _texto_obligatorio(valor, campo):
    texto = _texto_opcional(valor)
    if not texto:
        raise ValueError(f"El campo '{campo}' es obligatorio.")
    return texto


def _texto_opcional(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def _entero_booleano(valor):
    return 1 if bool(valor) else 0


def _leer_booleano(valor):
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False

    texto = str(valor).strip().lower()
    return texto in ("1", "true", "si", "sí", "yes", "on", "x")


def _fase_importada(valor, fase_default=None):
    if _texto_opcional(valor):
        return _normalizar_fase(valor)
    if fase_default is not None:
        return _normalizar_fase(fase_default)
    return None


def _leer_orden_importado(valor, campo):
    if valor is None or _texto_opcional(valor) == "":
        return None

    try:
        return int(valor)
    except (TypeError, ValueError) as error:
        raise ValueError(f"El campo '{campo}' debe ser un numero entero.") from error


def _normalizar_fase(valor):
    texto = _texto_opcional(valor).lower()
    equivalencias = {
        "inicio": "Inicio",
        "instruccion": "Instrucción",
        "instrucción": "Instrucción",
        "finalizacion": "Finalización",
        "finalización": "Finalización",
        "resolucion": "Resolución",
        "resolución": "Resolución",
    }
    return equivalencias.get(texto, DEFAULT_FASE)


def _normalizar_tipo_dato(valor):
    texto = _texto_opcional(valor).lower().replace("-", "_").replace(" ", "_")
    equivalencias = {
        "texto": "texto",
        "text": "texto",
        "string": "texto",
        "texto_largo": "texto_largo",
        "textolargo": "texto_largo",
        "textarea": "texto_largo",
        "wysiwyg": "texto_largo",
        "html": "texto_largo",
        "numero": "numerico",
        "número": "numerico",
        "numeric": "numerico",
        "numerico": "numerico",
        "numérico": "numerico",
        "number": "numerico",
        "fecha": "fecha",
        "date": "fecha",
    }
    return equivalencias.get(texto, DEFAULT_TIPO_DATO)


def _asegurar_columna_actuacion(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "actuacion" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN actuacion TEXT NOT NULL DEFAULT 'General'
            """
        )


def _asegurar_columna_fase_actuacion(connection):
    columnas = _columnas_tabla(connection, "actuaciones")
    if "fase" not in columnas:
        connection.execute(
            """
            ALTER TABLE actuaciones
            ADD COLUMN fase TEXT NOT NULL DEFAULT 'Inicio'
            """
        )


def _asegurar_columna_orden_actuacion(connection):
    columnas = _columnas_tabla(connection, "actuaciones")
    if "orden" not in columnas:
        connection.execute(
            """
            ALTER TABLE actuaciones
            ADD COLUMN orden INTEGER
            """
        )


def _asegurar_columna_id_actuacion(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "id_actuacion" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN id_actuacion INTEGER
            """
        )


def _asegurar_columna_tipo_dato(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "tipo_dato" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN tipo_dato TEXT NOT NULL DEFAULT 'texto'
            """
        )


def _asegurar_columna_documento(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "documento" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN documento INTEGER NOT NULL DEFAULT 0
            """
        )


def _asegurar_columna_dato_sensible(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "dato_sensible" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN dato_sensible INTEGER NOT NULL DEFAULT 0
            """
        )


def _asegurar_columna_orden(connection):
    columnas = _columnas_tabla(connection, "conjuntos")
    if "orden" not in columnas:
        connection.execute(
            """
            ALTER TABLE conjuntos
            ADD COLUMN orden INTEGER
            """
        )


def _asegurar_columna_valor_documento(connection):
    columnas = _columnas_tabla(connection, "expediente_valores")
    if "documento" not in columnas:
        connection.execute(
            """
            ALTER TABLE expediente_valores
            ADD COLUMN documento INTEGER NOT NULL DEFAULT 0
            """
        )
        return True
    return False


def _asegurar_columna_valor_dato_sensible(connection):
    columnas = _columnas_tabla(connection, "expediente_valores")
    if "dato_sensible" not in columnas:
        connection.execute(
            """
            ALTER TABLE expediente_valores
            ADD COLUMN dato_sensible INTEGER NOT NULL DEFAULT 0
            """
        )
        return True
    return False


def _columnas_tabla(connection, tabla):
    return {
        fila["name"]
        for fila in connection.execute(f"PRAGMA table_info({tabla})").fetchall()
    }


def _normalizar_actuaciones_existentes(connection):
    filas = connection.execute(
        """
        SELECT id, nombre, descripcion, actuacion
        FROM conjuntos
        WHERE actuacion IS NULL
            OR TRIM(actuacion) = ''
            OR actuacion = ?
        """,
        (DEFAULT_ACTUACION,),
    ).fetchall()

    for fila in filas:
        actuacion = _texto_opcional(fila["actuacion"])
        actuacion_inferida = _inferir_actuacion(fila["nombre"], fila["descripcion"])
        actuacion_final = actuacion_inferida or actuacion or DEFAULT_ACTUACION

        if actuacion_final != actuacion:
            connection.execute(
                "UPDATE conjuntos SET actuacion = ? WHERE id = ?",
                (actuacion_final, fila["id"]),
            )


def _sincronizar_actuaciones_existentes(connection):
    filas = connection.execute(
        """
        SELECT id, actuacion
        FROM conjuntos
        WHERE id_actuacion IS NULL
            OR id_actuacion NOT IN (SELECT id FROM actuaciones)
        """
    ).fetchall()

    for fila in filas:
        actuacion = _texto_opcional(fila["actuacion"]) or DEFAULT_ACTUACION
        id_actuacion = _crear_o_actualizar_actuacion(connection, actuacion, "")
        connection.execute(
            """
            UPDATE conjuntos
            SET actuacion = ?, id_actuacion = ?
            WHERE id = ?
            """,
            (actuacion, id_actuacion, fila["id"]),
        )


def _normalizar_orden_conjuntos(connection):
    filas = connection.execute(
        """
        SELECT
            c.id,
            c.orden
        FROM conjuntos AS c
        LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
        ORDER BY
            c.id_tipo,
            COALESCE(
                NULLIF(TRIM(a.nombre), ''),
                NULLIF(TRIM(c.actuacion), ''),
                ?
            ),
            COALESCE(c.orden, c.id),
            c.id
        """,
        (DEFAULT_ACTUACION,),
    ).fetchall()

    for posicion, fila in enumerate(filas, start=1):
        if fila["orden"] is None:
            connection.execute(
                """
                UPDATE conjuntos
                SET orden = ?
                WHERE id = ?
                """,
                (posicion * 10, fila["id"]),
            )


def _normalizar_orden_actuaciones(connection):
    filas = connection.execute(
        """
        SELECT id, fase, orden
        FROM actuaciones
        ORDER BY
            CASE fase
                WHEN 'Inicio' THEN 1
                WHEN 'Instrucción' THEN 2
                WHEN 'Finalización' THEN 3
                WHEN 'Resolución' THEN 4
                ELSE 5
            END,
            COALESCE(orden, id),
            id
        """
    ).fetchall()

    for posicion, fila in enumerate(filas, start=1):
        fase = _normalizar_fase(fila["fase"])
        if fila["orden"] is None or fila["fase"] != fase:
            connection.execute(
                """
                UPDATE actuaciones
                SET fase = ?, orden = COALESCE(orden, ?)
                WHERE id = ?
                """,
                (fase, posicion * 10, fila["id"]),
            )


def _sincronizar_metadatos_valores_existentes(connection):
    connection.execute(
        """
        UPDATE expediente_valores
        SET documento = COALESCE(
            (
                SELECT c.documento
                FROM conjuntos AS c
                WHERE c.id = expediente_valores.id_conjunto
            ),
            0
        )
        """
    )
    connection.execute(
        """
        UPDATE expediente_valores
        SET dato_sensible = COALESCE(
            (
                SELECT c.dato_sensible
                FROM conjuntos AS c
                WHERE c.id = expediente_valores.id_conjunto
            ),
            0
        )
        """
    )


def _siguiente_orden_conjunto(connection, id_tipo, actuacion):
    fila = connection.execute(
        """
        SELECT COALESCE(MAX(c.orden), 0) AS orden
        FROM conjuntos AS c
        LEFT JOIN actuaciones AS a ON a.id = c.id_actuacion
        WHERE c.id_tipo = ?
            AND COALESCE(
                NULLIF(TRIM(a.nombre), ''),
                NULLIF(TRIM(c.actuacion), ''),
                ?
            ) = ?
        """,
        (id_tipo, DEFAULT_ACTUACION, actuacion),
    ).fetchone()

    return (fila["orden"] or 0) + 10


def _siguiente_orden_actuacion(connection):
    fila = connection.execute(
        "SELECT COALESCE(MAX(orden), 0) AS orden FROM actuaciones"
    ).fetchone()
    return (fila["orden"] or 0) + 10


def _inferir_actuacion(nombre, descripcion):
    descripcion = _texto_opcional(descripcion)

    for prefijo in ("actuacion:", "actuación:", "tramite:", "trámite:"):
        if descripcion.lower().startswith(prefijo):
            resto = descripcion.split(":", 1)[1].strip()
            actuacion = resto.split(".", 1)[0].strip()
            if actuacion:
                return actuacion[:120]

    return DEFAULT_ACTUACION
