import json
import sqlite3
from html import escape
from html.parser import HTMLParser

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from database import (
    FASES,
    TIPOS_DATO,
    actualizar_actuacion,
    actualizar_conjunto,
    crear_actuacion,
    crear_conjunto,
    crear_conjunto_comun,
    crear_expediente,
    crear_tipo,
    eliminar_actuacion,
    exportar_catalogo,
    guardar_datos_comunes_expediente,
    guardar_valores_actuacion_expediente,
    importar_catalogo,
    listar_actuaciones,
    listar_actuaciones_por_tipo,
    listar_conjuntos,
    listar_conjuntos_comunes,
    listar_conjuntos_por_tipo,
    listar_expedientes,
    listar_progreso_actuaciones,
    listar_tipos,
    obtener_expediente,
    obtener_resumen,
    obtener_actuacion,
    obtener_conjunto,
    obtener_tipo,
    obtener_valores_actuacion_expediente,
    obtener_valores_comunes_expediente,
    reordenar_actuaciones,
    reordenar_conjuntos,
)


bp = Blueprint("navegacion", __name__)


FASE_SLUGS = {
    "Inicio": "inicio",
    "Instrucción": "instruccion",
    "Finalización": "finalizacion",
    "Resolución": "resolucion",
}


class _SanitizadorHtmlBasico(HTMLParser):
    etiquetas_permitidas = {
        "b",
        "br",
        "div",
        "em",
        "i",
        "li",
        "ol",
        "p",
        "strong",
        "u",
        "ul",
    }
    etiquetas_vacias = {"br"}
    etiquetas_bloqueadas = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragmentos = []
        self.bloqueo = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.etiquetas_bloqueadas:
            self.bloqueo += 1
            return
        if self.bloqueo:
            return
        if tag in self.etiquetas_permitidas:
            self.fragmentos.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in self.etiquetas_bloqueadas:
            self.bloqueo = max(0, self.bloqueo - 1)
            return
        if self.bloqueo:
            return
        if tag in self.etiquetas_permitidas and tag not in self.etiquetas_vacias:
            self.fragmentos.append(f"</{tag}>")

    def handle_data(self, data):
        if self.bloqueo:
            return
        self.fragmentos.append(escape(data))

    def get_html(self):
        return "".join(self.fragmentos).strip()


def _sanitizar_html_basico(valor):
    html = str(valor or "").strip()
    if not html:
        return ""

    parser = _SanitizadorHtmlBasico()
    parser.feed(html)
    parser.close()
    return parser.get_html()


@bp.app_template_filter("rich_text")
def rich_text(valor):
    return Markup(_sanitizar_html_basico(valor))


def _fase_slug(fase):
    return FASE_SLUGS.get(str(fase or "").strip(), "inicio")


EJEMPLO_CATALOGO = {
    "version": "3.0",
    "origen": "GEDAI",
    "datos_comunes_expediente": [
        {
            "nombre": "Titulo del expediente",
            "descripcion": "Denominacion breve e identificativa del expediente.",
        },
        {
            "nombre": "Serie documental",
            "descripcion": "Serie documental o categoria archivistica del expediente.",
        },
        {
            "nombre": "Fecha limite de tramitacion",
            "descripcion": "Fecha maxima prevista para finalizar la tramitacion.",
        },
    ],
    "procedimientos": [
        {
            "nombre": "Contrataciones menores de servicios",
            "descripcion": "Procedimiento para expedientes de contratacion menor de servicios.",
            "fases": [
                {
                    "nombre": "Inicio",
                    "tramites_o_actuaciones": [
                        {
                            "nombre": "Inicio del expediente",
                            "descripcion": "Actuaciones iniciales de preparacion del expediente.",
                            "orden": 10,
                            "datasets": [
                                {
                                    "nombre": "Unidad promotora",
                                    "descripcion": "Area o servicio que impulsa la contratacion.",
                                    "tipo_dato": "texto",
                                    "documento": False,
                                    "dato_sensible": False,
                                    "orden": 10,
                                },
                                {
                                    "nombre": "Necesidad a satisfacer",
                                    "descripcion": "Justificacion de la necesidad del servicio.",
                                    "tipo_dato": "texto_largo",
                                    "documento": True,
                                    "dato_sensible": False,
                                    "orden": 20,
                                },
                            ],
                        }
                    ],
                },
                {
                    "nombre": "Instrucción",
                    "tramites_o_actuaciones": [
                        {
                            "nombre": "Aprobacion del gasto",
                            "descripcion": "Validacion economica previa a la adjudicacion.",
                            "orden": 20,
                            "datasets": [
                                {
                                    "nombre": "Importe estimado",
                                    "descripcion": "Importe previsto del contrato, sin IVA.",
                                    "tipo_dato": "numerico",
                                    "documento": False,
                                    "dato_sensible": False,
                                    "orden": 10,
                                },
                                {
                                    "nombre": "Aplicacion presupuestaria",
                                    "descripcion": "Partida o aplicacion que financia el gasto.",
                                    "tipo_dato": "texto",
                                    "documento": False,
                                    "dato_sensible": False,
                                    "orden": 20,
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    ],
}


@bp.app_context_processor
def inyectar_navegacion():
    return {
        "nav_items": [
            ("navegacion.inicio", "Inicio"),
            ("navegacion.expedientes", "Expedientes"),
            ("navegacion.tipos", "Procedimientos"),
            ("navegacion.conjuntos", "Datasets"),
            ("navegacion.actuaciones", "Trámite o actuación"),
            ("navegacion.interoperabilidad", "Importar/Exportar"),
        ]
    }


@bp.route("/")
def inicio():
    return render_template(
        "index.html",
        active_endpoint="navegacion.inicio",
        resumen=obtener_resumen(),
    )


@bp.route("/expedientes", methods=["GET", "POST"])
def expedientes():
    tipos_disponibles = listar_tipos()
    conjuntos_comunes = listar_conjuntos_comunes()

    if request.method == "POST":
        id_tipo = request.form.get("id_tipo", type=int)
        valores_comunes = _valores_comunes_desde_formulario(conjuntos_comunes)

        if not id_tipo:
            flash("Selecciona el conjunto de datos del expediente.", "error")
        else:
            try:
                id_expediente = crear_expediente(id_tipo, valores_comunes)
                flash("Expediente iniciado correctamente.", "success")
                return redirect(
                    url_for("navegacion.expediente_detalle", id_expediente=id_expediente)
                )
            except sqlite3.IntegrityError:
                flash("No se ha podido iniciar el expediente.", "error")

    return render_template(
        "expedientes.html",
        active_endpoint="navegacion.expedientes",
        tipos=tipos_disponibles,
        conjuntos_comunes=conjuntos_comunes,
        expedientes=listar_expedientes(),
    )


@bp.route("/expedientes/<int:id_expediente>", methods=["GET", "POST"])
def expediente_detalle(id_expediente):
    expediente = obtener_expediente(id_expediente)
    if not expediente:
        flash("El expediente solicitado no existe.", "error")
        return redirect(url_for("navegacion.expedientes"))

    conjuntos_comunes = listar_conjuntos_comunes()
    actuaciones = listar_actuaciones_por_tipo(expediente["id_tipo"])
    actuacion_seleccionada = request.values.get("actuacion", "").strip()

    if not actuacion_seleccionada and actuaciones:
        actuacion_seleccionada = actuaciones[0]

    if request.method == "POST":
        accion = request.form.get("accion", "")

        if accion == "guardar_comunes":
            valores_comunes = _valores_comunes_desde_formulario(conjuntos_comunes)
            guardar_datos_comunes_expediente(id_expediente, valores_comunes)
            flash("Datos comunes del expediente guardados.", "success")
            return redirect(
                url_for(
                    "navegacion.expediente_detalle",
                    id_expediente=id_expediente,
                    actuacion=actuacion_seleccionada,
                )
            )

        if accion == "guardar_actuacion" and actuacion_seleccionada:
            conjuntos_actuacion = listar_conjuntos_por_tipo(
                expediente["id_tipo"],
                actuacion_seleccionada,
            )
            valores = _valores_actuacion_desde_formulario(conjuntos_actuacion)
            guardar_valores_actuacion_expediente(id_expediente, valores)
            flash("Datos del trámite o actuación guardados.", "success")
            return redirect(
                url_for(
                    "navegacion.expediente_detalle",
                    id_expediente=id_expediente,
                    actuacion=actuacion_seleccionada,
                )
            )

    valores_comunes = obtener_valores_comunes_expediente(id_expediente)
    conjuntos = (
        listar_conjuntos_por_tipo(expediente["id_tipo"], actuacion_seleccionada)
        if actuacion_seleccionada
        else []
    )
    valores_actuacion = (
        obtener_valores_actuacion_expediente(id_expediente, actuacion_seleccionada)
        if actuacion_seleccionada
        else {}
    )

    progreso_actuaciones = [
        {
            **dict(progreso),
            "fase": progreso["fase"] or "Inicio",
            "fase_slug": _fase_slug(progreso["fase"]),
        }
        for progreso in listar_progreso_actuaciones(id_expediente)
    ]

    return render_template(
        "expediente_detalle.html",
        active_endpoint="navegacion.expedientes",
        expediente=expediente,
        conjuntos_comunes=conjuntos_comunes,
        valores_comunes=valores_comunes,
        actuaciones=actuaciones,
        actuacion_seleccionada=actuacion_seleccionada,
        conjuntos=conjuntos,
        valores_actuacion=valores_actuacion,
        progreso_actuaciones=progreso_actuaciones,
        fases=FASES,
        fases_filtro=[
            {"nombre": fase, "slug": _fase_slug(fase)}
            for fase in FASES
        ],
    )


@bp.route("/expedientes/<int:id_expediente>/documento", methods=["POST"])
def expediente_documento(id_expediente):
    expediente = obtener_expediente(id_expediente)
    if not expediente:
        flash("El expediente solicitado no existe.", "error")
        return redirect(url_for("navegacion.expedientes"))

    actuacion = request.form.get("actuacion", "").strip()
    if not actuacion:
        flash("Selecciona un trámite o actuación.", "error")
        return redirect(
            url_for("navegacion.expediente_detalle", id_expediente=id_expediente)
        )

    conjuntos = listar_conjuntos_por_tipo(expediente["id_tipo"], actuacion)
    valores = _valores_actuacion_desde_formulario(conjuntos)
    guardar_valores_actuacion_expediente(id_expediente, valores)

    campos_documento = [
        {
            "nombre": conjunto["nombre"],
            "valor": valores[conjunto["id"]]["valor"],
            "tipo_dato": conjunto["tipo_dato"],
            "dato_sensible": valores[conjunto["id"]]["dato_sensible"],
        }
        for conjunto in conjuntos
        if valores[conjunto["id"]]["documento"]
    ]
    titulo_documento = request.form.get("titulo_documento", "").strip()

    return render_template(
        "documento_expediente.html",
        expediente=expediente,
        actuacion=actuacion,
        titulo_documento=titulo_documento or "Documento",
        campos_documento=campos_documento,
    )


@bp.route("/tipos", methods=["GET", "POST"])
@bp.route("/conjuntos-datos", methods=["GET", "POST"])
def tipos():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()

        if not nombre:
            flash("El nombre del conjunto de datos es obligatorio.", "error")
        else:
            try:
                crear_tipo(nombre, descripcion)
                flash("Conjunto de datos creado correctamente.", "success")
                return redirect(url_for("navegacion.tipos"))
            except sqlite3.IntegrityError:
                flash("Ya existe un conjunto de datos con ese nombre.", "error")

    return render_template(
        "tipos.html",
        active_endpoint="navegacion.tipos",
        tipos=listar_tipos(),
    )


@bp.route("/conjuntos", methods=["GET", "POST"])
@bp.route("/estructura", methods=["GET", "POST"])
def conjuntos():
    tipos_disponibles = listar_tipos()
    actuaciones_disponibles = listar_actuaciones()

    if request.method == "POST":
        formulario = request.form.get("formulario", "especifico")
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        id_tipo = request.form.get("id_tipo", type=int)
        id_actuacion = request.form.get("id_actuacion", type=int)
        tipo_dato = request.form.get("tipo_dato", "").strip()
        documento = _checkbox_activo("documento")
        dato_sensible = _checkbox_activo("dato_sensible")

        if formulario == "comun":
            if not nombre:
                flash("El nombre del dato común es obligatorio.", "error")
            else:
                try:
                    crear_conjunto_comun(nombre, descripcion)
                    flash("Dato común del expediente creado correctamente.", "success")
                    return redirect(url_for("navegacion.conjuntos"))
                except sqlite3.IntegrityError:
                    flash("Ya existe un dato común con ese nombre.", "error")
        else:
            actuacion = _nombre_actuacion_desde_lista(
                actuaciones_disponibles,
                id_actuacion,
            )
            if not nombre or not id_tipo or not actuacion:
                flash(
                    "El nombre, el conjunto de datos y el trámite o actuación son obligatorios.",
                    "error",
                )
            else:
                try:
                    crear_conjunto(
                        nombre,
                        descripcion,
                        id_tipo,
                        actuacion,
                        tipo_dato,
                        documento,
                        dato_sensible,
                    )
                    flash("Dataset creado correctamente.", "success")
                    return redirect(url_for("navegacion.conjuntos"))
                except (ValueError, sqlite3.IntegrityError):
                    flash("No se ha podido crear la estructura.", "error")

    return render_template(
        "conjuntos.html",
        active_endpoint="navegacion.conjuntos",
        tipos=tipos_disponibles,
        actuaciones=actuaciones_disponibles,
        tipos_dato=TIPOS_DATO,
        conjuntos_comunes=listar_conjuntos_comunes(),
        conjuntos=listar_conjuntos(),
    )


@bp.route("/conjuntos/<int:id_conjunto>/editar", methods=["GET", "POST"])
def editar_conjunto(id_conjunto):
    conjunto = obtener_conjunto(id_conjunto)
    if not conjunto:
        flash("El campo de dataset solicitado no existe.", "error")
        return redirect(url_for("navegacion.conjuntos"))

    tipos_disponibles = listar_tipos()
    actuaciones_disponibles = listar_actuaciones()

    if request.method == "GET":
        return render_template(
            "conjunto_editar.html",
            active_endpoint="navegacion.conjuntos",
            conjunto=conjunto,
            tipos=tipos_disponibles,
            actuaciones=actuaciones_disponibles,
            tipos_dato=TIPOS_DATO,
        )

    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    id_tipo = request.form.get("id_tipo", type=int)
    id_actuacion = request.form.get("id_actuacion", type=int)
    tipo_dato = request.form.get("tipo_dato", "").strip()
    actuacion = _nombre_actuacion_desde_lista(actuaciones_disponibles, id_actuacion)

    if not nombre or not id_tipo or not actuacion:
        flash(
            "El nombre, el procedimiento y el trámite o actuación son obligatorios.",
            "error",
        )
    else:
        try:
            if actualizar_conjunto(
                id_conjunto,
                nombre,
                descripcion,
                id_tipo,
                actuacion,
                tipo_dato,
                _checkbox_activo("documento"),
                _checkbox_activo("dato_sensible"),
            ):
                flash("Campo de dataset actualizado correctamente.", "success")
                return redirect(url_for("navegacion.conjuntos"))

            flash("El campo de dataset solicitado no existe.", "error")
            return redirect(url_for("navegacion.conjuntos"))
        except sqlite3.IntegrityError:
            flash("No se ha podido actualizar el campo de dataset.", "error")
        except ValueError as error:
            flash(str(error), "error")

    conjunto_formulario = {
        "id": id_conjunto,
        "nombre": nombre,
        "descripcion": descripcion,
        "id_tipo": id_tipo,
        "id_actuacion": id_actuacion,
        "tipo_dato": tipo_dato,
        "documento": _checkbox_activo("documento"),
        "dato_sensible": _checkbox_activo("dato_sensible"),
    }
    return render_template(
        "conjunto_editar.html",
        active_endpoint="navegacion.conjuntos",
        conjunto=conjunto_formulario,
        tipos=tipos_disponibles,
        actuaciones=actuaciones_disponibles,
        tipos_dato=TIPOS_DATO,
    )


@bp.route("/conjuntos/reordenar", methods=["POST"])
def reordenar_conjuntos_ruta():
    ids_ordenados = request.form.getlist("orden")
    reordenar_conjuntos(ids_ordenados)
    flash("Orden de datasets actualizado correctamente.", "success")
    return redirect(url_for("navegacion.conjuntos"))


@bp.route("/tramites-actuaciones", methods=["GET", "POST"])
def actuaciones():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        fase = request.form.get("fase", "").strip()

        if not nombre:
            flash("El nombre del trámite o actuación es obligatorio.", "error")
        else:
            try:
                crear_actuacion(nombre, descripcion, fase)
                flash("Trámite o actuación creado correctamente.", "success")
                return redirect(url_for("navegacion.actuaciones"))
            except sqlite3.IntegrityError:
                flash("Ya existe un trámite o actuación con ese nombre.", "error")

    return render_template(
        "actuaciones.html",
        active_endpoint="navegacion.actuaciones",
        actuaciones=listar_actuaciones(),
        fases=FASES,
    )


@bp.route("/tramites-actuaciones/reordenar", methods=["POST"])
def reordenar_actuaciones_ruta():
    ids_ordenados = request.form.getlist("orden")
    reordenar_actuaciones(ids_ordenados)
    flash("Orden de trámites o actuaciones actualizado correctamente.", "success")
    return redirect(url_for("navegacion.actuaciones"))


@bp.route("/tramites-actuaciones/<int:id_actuacion>/editar", methods=["GET", "POST"])
def editar_actuacion(id_actuacion):
    actuacion = obtener_actuacion(id_actuacion)
    if not actuacion:
        flash("El trámite o actuación solicitado no existe.", "error")
        return redirect(url_for("navegacion.actuaciones"))

    if request.method == "GET":
        return render_template(
            "actuacion_editar.html",
            active_endpoint="navegacion.actuaciones",
            actuacion=actuacion,
            fases=FASES,
        )

    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    fase = request.form.get("fase", "").strip()

    if not nombre:
        flash("El nombre del trámite o actuación es obligatorio.", "error")
    else:
        try:
            if actualizar_actuacion(id_actuacion, nombre, descripcion, fase):
                flash("Trámite o actuación actualizado correctamente.", "success")
                return redirect(url_for("navegacion.actuaciones"))
            else:
                flash("El trámite o actuación solicitado no existe.", "error")
                return redirect(url_for("navegacion.actuaciones"))
        except sqlite3.IntegrityError:
            flash("Ya existe un trámite o actuación con ese nombre.", "error")
        except ValueError as error:
            flash(str(error), "error")

    return render_template(
        "actuacion_editar.html",
        active_endpoint="navegacion.actuaciones",
        actuacion={
            "id": id_actuacion,
            "nombre": nombre,
            "descripcion": descripcion,
            "fase": fase,
        },
        fases=FASES,
    )


@bp.route("/tramites-actuaciones/<int:id_actuacion>/eliminar", methods=["POST"])
def borrar_actuacion(id_actuacion):
    if eliminar_actuacion(id_actuacion):
        flash("Trámite o actuación eliminado correctamente.", "success")
    else:
        flash("El trámite o actuación solicitado no existe.", "error")

    return redirect(url_for("navegacion.actuaciones"))


@bp.route("/clasificaciones")
def clasificaciones():
    flash("Las clasificaciones han sido sustituidas por Trámite o actuación.", "success")
    return redirect(url_for("navegacion.actuaciones"))


@bp.route("/entrada-datos", methods=["GET", "POST"])
def entrada_datos():
    return redirect(url_for("navegacion.expedientes"))


@bp.route("/interoperabilidad", methods=["GET", "POST"])
def interoperabilidad():
    resultado_importacion = None

    if request.method == "POST":
        contenido, error_archivo = _leer_json_importado()

        if error_archivo:
            flash(error_archivo, "error")
        elif not contenido:
            flash("Selecciona un archivo JSON o pega el contenido en el formulario.", "error")
        else:
            try:
                datos = json.loads(contenido)
                resultado_importacion = importar_catalogo(datos)
                flash(_mensaje_importacion(resultado_importacion), "success")
            except json.JSONDecodeError as error:
                flash(f"JSON no valido: {error.msg}.", "error")
            except ValueError as error:
                flash(str(error), "error")
            except sqlite3.Error:
                flash("No se ha podido importar el catalogo en la base de datos.", "error")

    return render_template(
        "interoperabilidad.html",
        active_endpoint="navegacion.interoperabilidad",
        tipos=listar_tipos(),
        ejemplo_json=json.dumps(EJEMPLO_CATALOGO, indent=2, ensure_ascii=False),
        resultado_importacion=resultado_importacion,
    )


@bp.route("/interoperabilidad/exportar")
def descargar_catalogo():
    return _descargar_json(exportar_catalogo(), "gedai_catalogo.json")


@bp.route("/interoperabilidad/exportar/tipo/<int:id_tipo>")
def descargar_tipo(id_tipo):
    tipo = obtener_tipo(id_tipo)
    if not tipo:
        flash("El conjunto de datos solicitado no existe.", "error")
        return redirect(url_for("navegacion.interoperabilidad"))

    nombre_archivo = f"gedai_conjunto_{_nombre_archivo_seguro(tipo['nombre'])}.json"
    return _descargar_json(exportar_catalogo(id_tipo), nombre_archivo)


def _nombre_actuacion_desde_lista(actuaciones, id_actuacion):
    if not id_actuacion:
        return ""

    for actuacion in actuaciones:
        if actuacion["id"] == id_actuacion:
            return actuacion["nombre"]

    return ""


def _valores_comunes_desde_formulario(conjuntos_comunes):
    return {
        conjunto["id"]: request.form.get(f"comun_{conjunto['id']}", "").strip()
        for conjunto in conjuntos_comunes
    }


def _valores_actuacion_desde_formulario(conjuntos):
    valores = {}

    for conjunto in conjuntos:
        valor = request.form.get(f"dato_{conjunto['id']}", "").strip()
        if conjunto["tipo_dato"] == "texto_largo":
            valor = _sanitizar_html_basico(valor)

        valores[conjunto["id"]] = {
            "valor": valor,
            "documento": _checkbox_activo(f"documento_{conjunto['id']}"),
            "dato_sensible": _checkbox_activo(
                f"dato_sensible_{conjunto['id']}"
            ),
        }

    return valores


def _checkbox_activo(nombre_campo):
    return request.form.get(nombre_campo) == "on"


def _leer_json_importado():
    contenido = request.form.get("json_text", "").strip()
    archivo = request.files.get("json_file")

    if archivo and archivo.filename:
        try:
            contenido = archivo.read().decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return "", "El archivo debe estar codificado en UTF-8."

    return contenido, None


def _descargar_json(datos, nombre_archivo):
    contenido = json.dumps(datos, indent=2, ensure_ascii=False)
    return Response(
        contenido,
        mimetype="application/json",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}",
        },
    )


def _mensaje_importacion(resultado):
    return (
        "Importacion completada: "
        f"{resultado['tipos_creados']} conjuntos de datos creados, "
        f"{resultado['actuaciones_creadas']} trámites o actuaciones creados, "
        f"{resultado['conjuntos_comunes_creados']} datos comunes creados y "
        f"{resultado['conjuntos_creados']} elementos de estructura creados."
    )


def _nombre_archivo_seguro(texto):
    caracteres = []
    for caracter in texto.lower():
        if caracter.isascii() and caracter.isalnum():
            caracteres.append(caracter)
        elif caracter in (" ", "-", "_"):
            caracteres.append("_")

    nombre = "".join(caracteres).strip("_")
    return nombre or "conjunto_datos"
