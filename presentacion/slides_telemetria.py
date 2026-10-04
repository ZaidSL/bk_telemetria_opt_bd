#!/usr/bin/env python3
"""
slides_telemetria.py
=============================================================================
MÓDULO 2: OBSERVABILIDAD Y TELEMETRÍA EN SERVIDOR DESACOPLADO
Responsable: Estudiante 2
=============================================================================
Contenido:
- Qué es la telemetría y qué problema resuelve.
- Flujo: PostgreSQL -> Promtail -> Loki -> Grafana.
- Por qué se eligió una arquitectura desacoplada.
- Demostración: actividad operativa frente a datos de negocio.

Este archivo se puede ejecutar de forma INDEPENDIENTE para generar una vista
previa exclusiva de este módulo:
    python presentacion/slides_telemetria.py
"""

import os
from pptx.util import Inches
import matplotlib.pyplot as plt
import numpy as np

from estilo_base import (
    ASSETS_DIR, SCRIPT_DIR, create_empty_deck, create_base_slide,
    add_card, add_structured_item, save_deck_safe
)

def generar_grafico_paradoja_logs():
    """Genera gráfico comparativo: Crecimiento de Logs vs Crecimiento de Tabla"""
    path = os.path.join(ASSETS_DIR, "grafico_paradoja_logs.png")
    fig, ax = plt.subplots(figsize=(6.4, 4.0), facecolor='#1E293B')
    ax.set_facecolor('#1E293B')

    updates = np.array([0, 50, 100, 200, 350, 500, 750, 1000])
    tabla_mb = np.array([12.1, 12.12, 12.15, 12.18, 12.22, 12.25, 12.29, 12.33])
    logs_mb = np.array([0.1, 8.5, 18.2, 39.5, 71.0, 105.4, 162.8, 224.0])

    ax.plot(updates, logs_mb, color='#F87171', linewidth=2.5, marker='o', markersize=4.5,
            label='Logs de Transacciones y WALs (MB)', zorder=4)
    ax.plot(updates, tabla_mb, color='#38BDF8', linewidth=2.5, marker='s', markersize=4.5,
            label='Espacio de Datos en Disco (MB)', zorder=4)
    ax.fill_between(updates, logs_mb, color='#F87171', alpha=0.10)

    ax.set_title("Crecimiento de Logs vs Almacenamiento de Tabla", color='#F8FAFC',
                 fontsize=11.5, fontweight='bold', pad=14, fontfamily='sans-serif')
    ax.set_xlabel("Sentencias Transaccionales Ejecutadas (UPDATES)", color='#94A3B8', fontsize=9.5)
    ax.set_ylabel("Espacio de Almacenamiento (MB)", color='#94A3B8', fontsize=9.5)
    ax.tick_params(colors='#E2E8F0', labelsize=8.5)
    ax.grid(True, linestyle=':', alpha=0.25, color='#64748B')

    for spine in ax.spines.values():
        spine.set_color('#334155')

    legend = ax.legend(facecolor='#0F172A', edgecolor='#334155', fontsize=8.5)
    for text in legend.get_texts():
        text.set_color('#E2E8F0')

    plt.tight_layout()
    plt.savefig(path, dpi=200, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    return path

def agregar_slides_telemetria(prs):
    """Inserta las cuatro diapositivas del módulo independiente de Telemetría."""
    img_paradoja = generar_grafico_paradoja_logs()

    # --------------------------------------------------------------------------
    # SLIDE T1: CONCEPTO
    # --------------------------------------------------------------------------
    s1 = create_base_slide(prs, "Módulo 2 · Telemetría", "¿Qué es la telemetría?")

    add_card(s1, Inches(0.8), Inches(1.65), Inches(5.7), Inches(5.1), "Observar el sistema mientras trabaja")
    tb = s1.shapes.add_textbox(Inches(1.05), Inches(2.25), Inches(5.2), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "Definición:", "Es recopilar señales del sistema para entender su estado, comportamiento y problemas.", 12)
    add_structured_item(tf, "Señales:", "Pueden ser logs, métricas o trazas. En este proyecto usamos principalmente logs de PostgreSQL.", 12)
    add_structured_item(tf, "Pregunta que responde:", "¿Qué está ocurriendo ahora y qué ocurrió antes de un error?", 12)
    add_structured_item(tf, "Valor:", "Convierte actividad técnica en evidencia visible para diagnosticar y tomar decisiones.", 12)

    add_card(s1, Inches(6.8), Inches(1.65), Inches(5.7), Inches(5.1), "Nuestra señal principal")
    tb = s1.shapes.add_textbox(Inches(7.05), Inches(2.25), Inches(5.2), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "PostgreSQL:", "Registra las sentencias SQL y su duración en archivos de log.", 12)
    add_structured_item(tf, "Qué observamos:", "SELECT, INSERT, UPDATE, errores y volumen de actividad.", 12)
    add_structured_item(tf, "Resultado:", "Un dashboard permite ver el comportamiento sin revisar archivos manualmente.", 12)
    add_structured_item(tf, "Idea clave:", "Telemetría no modifica el negocio; observa y explica lo que sucede.", 12)

    # --------------------------------------------------------------------------
    # SLIDE T2: FUNCIONAMIENTO
    # --------------------------------------------------------------------------
    s2 = create_base_slide(prs, "Módulo 2 · Telemetría", "¿Cómo funciona nuestra implementación?")

    add_card(s2, Inches(0.8), Inches(1.65), Inches(5.7), Inches(5.1), "Flujo de extremo a extremo")
    tb = s2.shapes.add_textbox(Inches(1.05), Inches(2.25), Inches(5.2), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "1. PostgreSQL:", "Ejecuta la consulta y escribe el evento en postgresql.log.", 12)
    add_structured_item(tf, "2. Promtail:", "Lee el archivo en streaming y lo envía sin modificar las tablas.", 12)
    add_structured_item(tf, "3. Loki:", "Recibe y conserva los eventos para poder buscarlos posteriormente.", 12)
    add_structured_item(tf, "4. Grafana:", "Consulta Loki y presenta contadores, tasas, errores y logs en vivo.", 12)

    add_card(s2, Inches(6.8), Inches(1.65), Inches(5.7), Inches(5.1), "Qué ocurre con una consulta")
    tb = s2.shapes.add_textbox(Inches(7.05), Inches(2.25), Inches(5.2), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "Actividad normal:", "El evento aparece como una línea y aumenta el contador del dashboard.", 12)
    add_structured_item(tf, "Actividad de escritura:", "INSERT y UPDATE permiten observar cambios sobre los datos.", 12)
    add_structured_item(tf, "Error:", "La consulta intencionalmente inválida aparece en el panel de errores.", 12)
    add_structured_item(tf, "Tiempo real:", "El dashboard se actualiza cada 5 segundos mientras llega actividad.", 12)

    # --------------------------------------------------------------------------
    # SLIDE T3: DECISIÓN ARQUITECTÓNICA
    # --------------------------------------------------------------------------
    s3 = create_base_slide(prs, "Módulo 2 · Telemetría", "¿Por qué usamos una arquitectura desacoplada?")

    add_card(s3, Inches(0.8), Inches(1.65), Inches(5.7), Inches(5.1), "Decisiones de diseño")
    tb = s3.shapes.add_textbox(Inches(1.05), Inches(2.25), Inches(5.0), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "Separación:", "Los datos de negocio permanecen en PostgreSQL y los logs se consultan en Loki.", 12)
    add_structured_item(tf, "Menor interferencia:", "Promtail lee en solo lectura y no abre bloqueos sobre las tablas.", 12)
    add_structured_item(tf, "Visibilidad central:", "Grafana reúne la actividad y evita revisar archivos dentro del contenedor.", 12)
    add_structured_item(tf, "Escalabilidad:", "Podemos añadir más fuentes de logs sin convertirlas en tablas de negocio.", 12)
    add_structured_item(tf, "Decisión consciente:", "Es una arquitectura de laboratorio; en producción añadiríamos seguridad, retención y réplicas.", 12)

    add_card(s3, Inches(6.8), Inches(1.65), Inches(5.7), Inches(5.1), "Qué evitamos")
    tb = s3.shapes.add_textbox(Inches(7.05), Inches(2.25), Inches(5.2), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "Mezclar responsabilidades:", "No usamos las tablas transaccionales como sistema de logs.", 12)
    add_structured_item(tf, "Perder contexto:", "Conservamos timestamp, usuario, base, proceso y nivel del evento.", 12)
    add_structured_item(tf, "Diagnóstico manual:", "El dashboard permite ver patrones y errores rápidamente.", 12)
    add_structured_item(tf, "Confusión conceptual:", "WAL sirve para recuperación; Loki sirve para observabilidad.", 12)

    # --------------------------------------------------------------------------
    # SLIDE T4: DEMOSTRACIÓN
    # --------------------------------------------------------------------------
    s4 = create_base_slide(prs, "Módulo 2 · Telemetría", "¿Qué demostramos en vivo?")

    add_card(s4, Inches(0.8), Inches(1.65), Inches(5.5), Inches(5.1), "Experimento de actividad")
    tb = s4.shapes.add_textbox(Inches(1.05), Inches(2.25), Inches(5.0), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    add_structured_item(tf, "Preparación:", "Poblamos cuentas de prueba para que existan datos reales.", 12)
    add_structured_item(tf, "Tráfico:", "El generador ejecuta SELECT, UPDATE e INSERT durante 60 segundos.", 12)
    add_structured_item(tf, "Error controlado:", "Cada cierto número de iteraciones consulta una tabla inexistente.", 12)
    add_structured_item(tf, "Observación:", "Grafana muestra el aumento de actividad y el error en tiempo casi real.", 12)
    add_structured_item(tf, "Comparación:", "El modo growth actualiza una fila muchas veces y evidencia el volumen de logs.", 12)

    s4.shapes.add_picture(img_paradoja, Inches(6.6), Inches(1.8), width=Inches(5.9))

if __name__ == "__main__":
    print(">>> Generando vista previa independiente del MÓDULO TELEMETRÍA...")
    preview_prs = create_empty_deck()
    agregar_slides_telemetria(preview_prs)
    preview_path = os.path.join(SCRIPT_DIR, "preview_modulo_telemetria.pptx")
    save_deck_safe(preview_prs, preview_path)
